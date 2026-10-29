interface LobbyProps {
  firstName: string;
  error: string;
  busy: boolean;
  onStart: () => void;
}

export function Lobby(props: LobbyProps) {
  const name = props.firstName || "Sam";
  return (
    <section className="lobby">
      <div className="lobby-copy">
        <p className="eyebrow">Technical interview</p>
        <h1>Hi {name}, are you ready for the interview?</h1>
        <p className="lede">
          Charlie is an AI. This session is led by an AI interviewer, not a person.
        </p>
        <div className="lobby-card">
          <p className="disclaimer">
            Charlie will join on video for introductions, two coding problems, then system design.
          </p>
          {props.error && <p className="error">{props.error}</p>}
          <button className="primary" type="button" onClick={props.onStart} disabled={props.busy}>
            {props.busy ? "Connecting…" : "I'm ready"}
          </button>
        </div>
      </div>
      <svg className="lobby-art" viewBox="70 20 620 580" aria-hidden="true">
        <defs>
          <linearGradient id="deloitte-ring" x1="0%" y1="80%" x2="100%" y2="10%">
            <stop offset="0%" stopColor="#86BC25" />
            <stop offset="42%" stopColor="#0D8390" />
            <stop offset="100%" stopColor="#43B02A" />
          </linearGradient>
        </defs>
        <path
          d="M118 548c70-20 120-70 132-132 20-110-40-250 90-320 130-70 280 10 300 150 18 130-70 250-190 290-70 24-150 8-210-30"
          fill="none"
          stroke="url(#deloitte-ring)"
          strokeWidth="44"
          strokeLinecap="round"
        />
      </svg>
    </section>
  );
}
