export type Capability = {
  return_details?: boolean | null;
  name: string;
  source?: "human" | "llm";
  recording_actor?: "human" | "automated_demo";
  description: string;
  version: number;
  app: string;
  inputs: Record<string, { sensitive?: boolean; pattern?: string }>;
  outputs: Record<string, unknown>;
  steps: {
    kind: string;
    target: { name: string };
    input_key?: string;
    output_key?: string;
  }[];
  discovery_run: string;
};
export type Run = {
  explanation?: RunExplanation | null;
  trace?: {id: string; state: string; url: string | null; error: string | null} | null;
  return_details?: boolean | null;
  has_video?: boolean;
  id: string;
  draft?: Capability;
  recording?: {
    reviewing?: boolean;
    focused?: import("./BankFieldEditor").FocusedField | null;
    error?: string;
    headings?: string[];
    outputs?: string[];
    parameters?: Record<string, unknown>;
    steps?: {
      number: number;
      kind: string;
      before: string;
      after: string;
      action?: { kind: string; target: { name: string }; input_key?: string };
    }[];
  };
  name?: string;
  created: number;
  mode: string;
  status: string;
  code: string;
  profile: string;
  scenario: string;
  capability_id: string;
  actions: number;
  model_decisions: number;
  run_id?: string;
  result?: {
    outputs: Record<string, string>;
    human_assisted: boolean;
    observed?: string;
  };
  events: { event: string; time: string; [key: string]: unknown }[];
  live?: {
    owner: string;
    step: number;
    session_id: string;
    has_frame: boolean;
    takeover_requested?: boolean;
    intervention?: { reason: string; expected: unknown };
  };
};
export type RunExplanation = {
  task: string; mode: string; status: string; summary: string; next_step: string;
  error_code: string | null; elapsed_ms: number | null;
  completed_actions: number | null; attempted_actions: number;
  last_completed_action: string | null; stopped_at: string | null;
  model_calls: number; model_calls_basis: string; input_tokens: number; output_tokens: number;
  outputs_count: number; verification_passed: boolean | null; human_assisted: boolean;
  protected_write_attempts: number | null; write_note: string; limitations: string;
  timeline: {title:string; purpose?:string; operation:string; state:string; duration_ms?:number; explanation?:string; next_step?:string; action_number?:number}[];
};
export type CatalogItem = { id: string; capability: Capability };
export async function request<T>(
  path: string,
  options: RequestInit = {},
  csrf = "",
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status}). Check the inputs and try again.`,
    );
  }
  return response.json();
}
