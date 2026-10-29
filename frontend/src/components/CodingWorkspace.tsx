import Editor from "@monaco-editor/react";
import { useState } from "react";

import { statementSections } from "../interviewUi";
import type { ProblemView } from "../types";

interface CodingWorkspaceProps {
  problem: ProblemView | null;
  language: "python3" | "typescript";
  code: string;
  terminal: string;
  frozen: boolean;
  running: boolean;
  onLanguage: (language: "python3" | "typescript") => void;
  onCode: (code: string) => void;
  onRun: () => void;
}

export function CodingWorkspace(props: CodingWorkspaceProps) {
  const [outputOpen, setOutputOpen] = useState(false);
  const problem = props.problem;
  return (
    <section className="workspace coding">
      <article className="problem coding-statement" aria-label="Problem description">
        <div className="pane-label">Problem {problem?.challenge_number ? `· ${problem.challenge_number}` : ""}</div>
        <div className="problem-heading">
          <h1>{problem?.question_title ?? "Coding problem"}</h1>
          <span className="badge">{problem?.difficulty_level}</span>
        </div>
        <div className="statement-body">
          {statementSections(problem?.question ?? "").map((section, index) => (
            <section key={index} className={section.title.startsWith("Example") ? "example-block" : "statement-section"}>
              {section.title && <h2>{section.title}</h2>}
              <p>{section.body.replace(/\s+(Input:|Output:|Explanation:)/g, "\n$1")}</p>
            </section>
          ))}
        </div>
      </article>
      <div className="code-pane">
        <div className="editor-bar">
          <span className="pane-label">Code</span>
          <label className="language-select">
            <span className="sr-only">Programming language</span>
            <select value={props.language} disabled={props.frozen || props.running}
              onChange={(event) => props.onLanguage(event.target.value as "python3" | "typescript")}>
              <option value="python3">Python</option>
              <option value="typescript">TypeScript</option>
            </select>
          </label>
          <button type="button" className="primary" onClick={() => { setOutputOpen(true); props.onRun(); }}
            disabled={props.frozen || props.running}>{props.running ? "Running…" : "Run code"}</button>
        </div>
        <div className="editor-frame">
          <Editor height="100%" language={props.language === "python3" ? "python" : "typescript"}
            theme="vs" value={props.code} onChange={(value) => props.onCode(value ?? "")}
            options={{ readOnly: props.frozen, minimap: { enabled: false }, fontSize: 15,
              padding: { top: 18 }, scrollBeyondLastLine: false, wordWrap: "on", automaticLayout: true }} />
        </div>
        <div className="output-panel">
          <button className="output-toggle" type="button" aria-expanded={outputOpen}
            onClick={() => setOutputOpen(!outputOpen)}>
            <span>Output</span><span>{outputOpen ? "Hide" : "Show"}</span>
          </button>
          {outputOpen && <pre role="log" aria-label="Code output">{props.terminal || "Run your code to see output. Add your own test calls to exercise the solution."}</pre>}
        </div>
        <p className="workspace-note">Run executes your code; add your own test calls. Think aloud at your own pace.</p>
      </div>
    </section>
  );
}
