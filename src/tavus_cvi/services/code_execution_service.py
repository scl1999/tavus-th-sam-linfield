"""Run candidate code only inside bounded disposable containers."""

from __future__ import annotations

import json
import logging
import os
import selectors
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import yaml

from tavus_cvi.adapters.config import REPO_ROOT
from tavus_cvi.domain.entities import ExecutionResult
from tavus_cvi.domain.errors import WorkspaceExecutionError

_TIMEOUT_SECONDS = 5
_OUTPUT_LIMIT = 65536


class CodeExecutionService:
    def __init__(self, recordings_dir: Path) -> None:
        self._root = recordings_dir / "workspaces"
        self._images: dict[str, str] = yaml.safe_load(
            (REPO_ROOT / "config/execution.yaml").read_text()
        )

    def run_code(
        self, interview_id: str, language: str, source: str, cancelled: Event | None = None
    ) -> ExecutionResult:
        if language not in self._images:
            raise WorkspaceExecutionError("Only python3 and typescript are enabled")
        if len(source.encode()) > 100_000:
            raise WorkspaceExecutionError("Code is too large")
        workdir = self._workdir(interview_id)
        filename = "solution.py" if language == "python3" else "solution.ts"
        (workdir / filename).write_text(source, encoding="utf-8")
        return self._run(
            language,
            ["python3", filename]
            if language == "python3"
            else ["node", "--experimental-strip-types", filename],
            workdir,
            cancelled,
        )

    def run_terminal(
        self, interview_id: str, command: str, cancelled: Event | None = None
    ) -> ExecutionResult:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise WorkspaceExecutionError("Invalid command") from exc
        allowed = {
            ("ls",),
            ("cat", "solution.py"),
            ("cat", "solution.ts"),
            ("python3", "solution.py"),
            ("node", "solution.ts"),
        }
        if tuple(parts) not in allowed:
            raise WorkspaceExecutionError(
                "Only ls, cat solution files, or running a solution is allowed"
            )
        # Terminal is retained for compatibility and uses the same isolation.
        language = "typescript" if "solution.ts" in parts else "python3"
        workdir = self._root / interview_id / "latest"
        if not workdir.is_dir():
            raise WorkspaceExecutionError("Run code first")
        return self._run(language, parts, workdir, cancelled)

    def _workdir(self, interview_id: str) -> Path:
        if (
            not interview_id
            or Path(interview_id).name != interview_id
            or interview_id in {".", ".."}
        ):
            raise WorkspaceExecutionError("Invalid workspace")
        base = self._root / interview_id
        path = base / uuid4().hex
        path.mkdir(parents=True)
        link = base / "latest"
        temporary = base / f"latest-{uuid4().hex}"
        temporary.symlink_to(path.name)
        temporary.replace(link)
        return path

    @staticmethod
    def _bootstrap(language: str) -> list[str]:
        if language == "python3":
            return [
                "python3",
                "-c",
                "import sys,json,os,subprocess; p=json.load(sys.stdin); "
                "os.mkdir('/tmp/work'); os.chdir('/tmp/work'); "
                "[open(k,'w').write(v) for k,v in p['files'].items()]; "
                "sys.exit(subprocess.call(p['command']))",
            ]
        return [
            "node",
            "-e",
            "const fs=require('fs'),cp=require('child_process'); "
            "const p=JSON.parse(fs.readFileSync(0,'utf8')); "
            "fs.mkdirSync('/tmp/work');process.chdir('/tmp/work');"
            "for(const [k,v] of Object.entries(p.files)) fs.writeFileSync(k,v);"
            "const r=cp.spawnSync(p.command[0],p.command.slice(1),{stdio:'inherit'});"
            "process.exit(r.status??1)",
        ]

    def _run(
        self, language: str, command: list[str], workdir: Path, cancelled: Event | None = None
    ) -> ExecutionResult:
        name = f"tavus-run-{uuid4().hex}"
        argv = [
            "docker",
            "create",
            "--interactive",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--cpus=1",
            "--memory=256m",
            "--memory-swap=256m",
            "--pids-limit=32",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--workdir=/tmp",
            "--log-driver=none",
            self._images[language],
            *self._bootstrap(language),
        ]
        started = time.monotonic()
        output: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        process: subprocess.Popen[bytes] | None = None
        try:
            created = subprocess.run(argv, capture_output=True, timeout=10, check=False)
            if created.returncode:
                raise WorkspaceExecutionError(
                    "Isolated runner unavailable; check Docker and pinned images"
                )
            started = time.monotonic()
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                start_new_session=True,
            )
            assert process.stdin
            files = {
                file.name: file.read_text()
                for file in workdir.iterdir()
                if file.name in {"solution.py", "solution.ts"} and file.is_file()
            }
            if command == ["python3", "solution.py"]:
                command = [
                    "python3",
                    "-c",
                    "import typing; "
                    "g={k:getattr(typing,k) for k in ('List','Optional','Dict','Set','Tuple')}; "
                    "g.update(__name__='__main__',__file__='solution.py'); "
                    "exec(compile(open('solution.py').read(),'solution.py','exec'),g)",
                ]
            payload = memoryview(json.dumps({"files": files, "command": command}).encode())
            os.set_blocking(process.stdin.fileno(), False)
            assert process.stdout and process.stderr
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                selector.register(process.stdin, selectors.EVENT_WRITE, "input")
                while selector.get_map():
                    if cancelled and cancelled.is_set():
                        raise WorkspaceExecutionError("Command cancelled")
                    if time.monotonic() - started > _TIMEOUT_SECONDS:
                        raise WorkspaceExecutionError("Command timed out")
                    for key, _ in selector.select(0.05):
                        if key.data == "input":
                            try:
                                sent = os.write(key.fd, payload[:4096])
                                payload = payload[sent:]
                            except BrokenPipeError:
                                payload = memoryview(b"")
                            if not payload:
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                            continue
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output[key.data].extend(chunk)
                        if sum(len(value) for value in output.values()) > _OUTPUT_LIMIT:
                            raise WorkspaceExecutionError("Output exceeds 64 KiB")
                code = process.wait(
                    timeout=max(0.1, _TIMEOUT_SECONDS - (time.monotonic() - started))
                )
            if code == 125:
                raise WorkspaceExecutionError(
                    "Isolated runner unavailable; check Docker and pinned images"
                )
            return ExecutionResult(
                output["stdout"].decode(errors="replace"),
                output["stderr"].decode(errors="replace"),
                code,
                int((time.monotonic() - started) * 1000),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceExecutionError("Isolated runner could not finish") from exc
        finally:
            # Remove the container, including all descendants, before reaping the CLI.
            try:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, timeout=3, check=False
                )
            except (OSError, subprocess.TimeoutExpired):
                logging.getLogger(__name__).warning(
                    "Container cleanup requires retry", extra={"container": name}
                )
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()

    @staticmethod
    def cleanup_stale() -> None:
        """Retry cleanup after worker/daemon failure; live runs cannot exceed 30 seconds."""
        try:
            listed = subprocess.run(
                ["docker", "ps", "-aq", "--filter", "name=^/tavus-run-"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            ids = listed.stdout.decode().split()[:100]
            if not ids:
                return
            inspected = subprocess.run(
                ["docker", "inspect", *ids],
                capture_output=True,
                timeout=3,
                check=False,
            )
            for row in json.loads(inspected.stdout or b"[]"):
                created = datetime.fromisoformat(row["Created"].replace("Z", "+00:00"))
                if (datetime.now(UTC) - created).total_seconds() > 30:
                    subprocess.run(
                        ["docker", "rm", "-f", row["Id"]],
                        capture_output=True,
                        timeout=3,
                        check=False,
                    )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            logging.getLogger(__name__).warning("Isolated runner cleanup unavailable")
