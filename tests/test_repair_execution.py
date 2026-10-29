"""Real isolated runner checks using harmless synthetic host data."""

import ast
import json
import subprocess

import pytest

from tavus_cvi.adapters.config import REPO_ROOT
from tavus_cvi.domain.errors import WorkspaceExecutionError
from tavus_cvi.domain.starters import runnable_starter
from tavus_cvi.services.code_execution_service import CodeExecutionService


def test_runner_cannot_read_host_files_environment_or_network(tmp_path, monkeypatch):
    marker = tmp_path / "host-marker.txt"
    marker.write_text("synthetic host data")
    monkeypatch.setenv("SYNTHETIC_API_SECRET", "synthetic-only")
    runner = CodeExecutionService(tmp_path)
    source = f"""import os,socket
print(os.path.exists({str(marker)!r}), os.getenv('SYNTHETIC_API_SECRET'), os.getuid())
try:
 socket.create_connection(('1.1.1.1',80),timeout=0.3)
 print('NETWORK_OPEN')
except OSError:
 print('NETWORK_BLOCKED')
print(open('/sys/fs/cgroup/memory.max').read().strip())
print(open('/sys/fs/cgroup/pids.max').read().strip())
"""
    result = runner.run_code("sandbox", "python3", source)
    assert result.exit_code == 0
    assert "False None 65534" in result.stdout
    assert "NETWORK_BLOCKED" in result.stdout and "NETWORK_OPEN" not in result.stdout
    assert "268435456" in result.stdout and "32" in result.stdout
    with pytest.raises(WorkspaceExecutionError):
        runner.run_terminal("sandbox", f"cat {marker}")


def test_runner_caps_output_and_removes_descendants(tmp_path):
    runner = CodeExecutionService(tmp_path)
    with pytest.raises(WorkspaceExecutionError, match="Output exceeds"):
        runner.run_code("sandbox", "python3", "while True: print('x'*1000,flush=True)")
    with pytest.raises(WorkspaceExecutionError, match="timed out"):
        runner.run_code(
            "sandbox",
            "python3",
            "import subprocess,time; subprocess.Popen(['sleep','100']); time.sleep(100)",
        )
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=tavus-run-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert not result.stdout.strip()


def test_memory_is_bounded_and_typescript_runs(tmp_path):
    runner = CodeExecutionService(tmp_path)
    assert runner.run_code("sandbox", "python3", "data = bytearray(400*1024*1024)").exit_code != 0
    result = runner.run_code(
        "sandbox", "typescript", "const values: number[] = [1,2,3]; console.log(values.length);"
    )
    assert result.exit_code == 0 and result.stdout.strip() == "3"


def test_six_selected_starters_are_runnable_scaffolding(tmp_path):
    runner = CodeExecutionService(tmp_path)
    rows = json.loads((REPO_ROOT / "data/leetcode_first_100.json").read_text())
    selected = [row for row in rows if row["challenge_number"] in {1, 20, 26, 3, 11, 49}]
    assert len(selected) == 6
    for row in selected:
        for language in ("python3", "typescript"):
            source = runnable_starter(language, row["boilerplate_code"][language])
            if language == "python3":
                ast.parse(source)
            result = runner.run_code("scaffolds", language, source)
            assert result.exit_code == 0, result.stderr


def test_cancellation_removes_container_and_process_limit_is_enforced(tmp_path):
    from threading import Event, Timer

    runner = CodeExecutionService(tmp_path)
    stopped = Event()
    timer = Timer(0.7, stopped.set)
    timer.start()
    try:
        with pytest.raises(WorkspaceExecutionError, match="cancelled"):
            runner.run_code("cancelled", "python3", "import time;time.sleep(100)", stopped)
    finally:
        timer.join()
    source = """import os,time
children=[]
try:
 for _ in range(50):
  pid=os.fork()
  if pid==0: time.sleep(1);os._exit(0)
  children.append(pid)
except OSError:
 print('PROCESS_LIMIT',len(children))
for child in children:os.waitpid(child,0)
try:
 open('/etc/host-write','w').write('synthetic')
except OSError:print('READ_ONLY')
"""
    result = runner.run_code("limits", "python3", source)
    assert (
        result.exit_code == 0 and "PROCESS_LIMIT" in result.stdout and "READ_ONLY" in result.stdout
    )


def test_docker_unavailable_fails_closed_without_host_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    marker = tmp_path / "must-not-exist"
    with pytest.raises(WorkspaceExecutionError, match="could not finish"):
        CodeExecutionService(tmp_path).run_code(
            "offline", "python3", f"open({str(marker)!r},'w').write('bad')"
        )
    assert not marker.exists()
