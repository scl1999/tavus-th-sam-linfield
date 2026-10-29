export type Phase =
  | "intro"
  | "coding_easy"
  | "coding_medium"
  | "system_design"
  | "completed"
  | "terminated_rude"
  | "candidate_left";

export interface ProblemView {
  id?: number;
  challenge_number?: number;
  question_title: string;
  question?: string;
  difficulty_level?: string;
  hints?: string[];
  boilerplate_code?: Record<string, string>;
  question_number?: number;
  problem_statement?: string;
  functional_requirements?: string[];
  non_functional_requirements?: string[];
  evaluation_rubric?: string[];
}

export interface InterviewStatus {
  interview: {
    id: string;
    current_phase: Phase;
    conversation_url: string | null;
    conversation_id: string | null;
    started_at: string;
    ended_at?: string | null;
  };
  ready: boolean;
  setup_state: string;
  checkpoint_request?: string | null;
  workspace: {
    drafts: Record<string, string>;
    whiteboards: Record<string, string>;
    revisions: Record<string, number>;
    language: "python3" | "typescript";
    terminal: string;
  };
  elapsed_seconds: number;
  phase_deadline_seconds: number;
  frozen: boolean;
  easy: ProblemView | null;
  medium: ProblemView | null;
  system_design: ProblemView | null;
}

export interface DesignOption {
  id: number;
  question_number: number;
  question_title: string;
  problem_statement: string;
  functional_requirements?: string[];
  non_functional_requirements?: string[];
  evaluation_rubric?: string[];
}

export interface AppMessage {
  event_type: string;
  properties: Record<string, unknown>;
}

export interface TurnRow {
  turn_idx: number;
  role: string;
  input_tokens: number;
  output_tokens: number;
  utterance_text: string;
}
