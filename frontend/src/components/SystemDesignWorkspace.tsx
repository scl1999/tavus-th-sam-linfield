import { useEffect, useRef } from "react";
import type { ProblemView } from "../types";

interface SystemDesignWorkspaceProps {
  selected: ProblemView | null;
  frozen: boolean;
  initialXml: string;
  onXml: (xml: string) => void;
}
const ORIGIN = "https://embed.diagrams.net";
const EMBED = `${ORIGIN}/?embed=1&proto=json&spin=1&ui=min`;
const EMPTY =
  '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>';

export function SystemDesignWorkspace(props: SystemDesignWorkspaceProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const latest = useRef(props);
  latest.current = props;
  useEffect(() => {
    if (!frame.current) return;
    frame.current.inert = props.frozen;
    if (props.frozen) frame.current.blur();
  }, [props.frozen]);
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (
        event.origin !== ORIGIN ||
        event.source !== frame.current?.contentWindow
      )
        return;
      let payload: { event?: string; xml?: string };
      try {
        payload =
          typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }
      if (!payload || typeof payload !== "object") return;
      if (payload.event === "init") {
        frame.current?.contentWindow?.postMessage(
          JSON.stringify({
            action: "load",
            xml: latest.current.initialXml || EMPTY,
            autosave: 1,
          }),
          ORIGIN,
        );
      }
      if (
        !latest.current.frozen &&
        (payload.event === "save" || payload.event === "autosave") &&
        typeof payload.xml === "string"
      ) {
        latest.current.onXml(payload.xml);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);
  return (
    <section className="workspace design">
      <article className="problem">
        <p className="eyebrow">System design</p>
        <h2>{props.selected?.question_title}</h2>
        <p>{props.selected?.problem_statement}</p>
        <ul>
          {(props.selected?.functional_requirements ?? []).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
      <div className={props.frozen ? "diagram locked" : "diagram"}>
        <iframe ref={frame} title="draw.io" src={EMBED} />
      </div>
    </section>
  );
}
