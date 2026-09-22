export type Capability = {
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
