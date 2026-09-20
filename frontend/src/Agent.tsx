import { useState, type FormEvent } from "react";
import { request, type CatalogItem } from "./api";
type Message = { role: "you" | "agent"; text: string; matches?: string[] };
export function Agent({
  catalog,
  csrf,
  viewer,
  onRun,
  record,
}: {
  catalog: CatalogItem[];
  csrf: string;
  viewer: boolean;
  onRun: (id: string) => void;
  record: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<CatalogItem | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [approved, setApproved] = useState(false);
  const fields = Object.keys(selected?.capability.inputs || {});
  const missing = fields.find((field) => !values[field]);
  const say = (message: string, matches?: string[]) =>
    setMessages((old) => [...old, { role: "agent", text: message, matches }]);
  function choose(item: CatalogItem) {
    setSelected(item);
    setValues({});
    setApproved(false);
    const first = Object.keys(item.capability.inputs)[0];
    say(
      `Let's run ${item.capability.name}. ${first ? `What is the ${first.replaceAll("_", " ")}?` : "No inputs are needed. Review and start below."}`,
    );
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const input = text.trim();
    if (!input || busy) return;
    setText("");
    setMessages((old) => [...old, { role: "you", text: input }]);
    if (input.toLowerCase() === "cancel") {
      setSelected(null);
      setValues({});
      say("Cancelled this request. What would you like to do next?");
      return;
    }
    if (selected && missing) {
      const pattern = selected.capability.inputs[missing].pattern;
      if (
        input.length > 300 ||
        (pattern && !new RegExp(`^(?:${pattern})$`).test(input))
      ) {
        say(
          `That value doesn't match the required format${pattern ? ` (${pattern})` : ""}. Please enter ${missing} again.`,
        );
        return;
      }
      const updated = { ...values, [missing]: input };
      setValues(updated);
      const next = fields.find((field) => !updated[field]);
      say(
        next
          ? `What is the ${next.replaceAll("_", " ")}?`
          : "I have the required inputs. Review them below and select Run workflow. I won't execute until you do.",
      );
      return;
    }
    if (selected) {
      say(
        "Your workflow is ready below. Select Run workflow, or type cancel to start a different request.",
      );
      return;
    }
    setBusy(true);
    try {
      const reply = await request<{ matches: string[]; catalog_count: number }>(
        "/agent/match",
        { method: "POST", body: JSON.stringify({ message: input }) },
        csrf,
      );
      say(
        reply.matches.length
          ? "I found a saved workflow. Choose it below and I'll ask for its inputs."
          : "I don't have a matching published workflow. Record a demonstration using Record a workflow, then ask me again.",
        reply.matches,
      );
    } catch (error) {
      say((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function run() {
    if (!selected || missing || busy) return;
    setBusy(true);
    try {
      const result = await request<{ id: string }>(
        "/runs",
        {
          method: "POST",
          body: JSON.stringify({
            mode: "replay",
            capability_id: selected.id,
            inputs: values,
            approve_writes: approved,
          }),
        },
        csrf,
      );
      say(
        `Started ${selected.capability.name}. Watch the live browser below. Replay follows the saved steps without LLM decisions.`,
      );
      setSelected(null);
      setValues({});
      setApproved(false);
      onRun(result.id);
    } catch (error) {
      say((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel agent-panel">
      <p className="eyebrow">YOUR WORKFLOW ASSISTANT</p>
      <h2>What can I help you do?</h2>
      <p>
        Ask for a banking task. I'll find a saved workflow, ask for the inputs,
        and let you review before running it.
      </p>
      <div className="agent-examples">
        {[
          "Look up an account balance",
          "Update a mailing address",
          "Freeze a debit card",
        ].map((example) => (
          <button
            className="button secondary"
            key={example}
            disabled={!!selected || busy}
            onClick={() => setText(example)}
          >
            {example}
          </button>
        ))}
      </div>
      <div className="agent-conversation" aria-live="polite">
        {messages.map((message, index) => (
          <article
            key={index}
            className={
              message.role === "you" ? "agent-question" : "agent-answer"
            }
          >
            <small>{message.role === "you" ? "YOU" : "ASSISTANT"}</small>
            <p>{message.text}</p>
            {message.matches?.map((id) => {
              const item = catalog.find((candidate) => candidate.id === id);
              return item ? (
                <div className="agent-match" key={id}>
                  <h3>{item.capability.name}</h3>
                  <p>{item.capability.description}</p>
                  <small>
                    {item.capability.steps.length} recorded actions · Version{" "}
                    {item.capability.version}
                  </small>
                  <button
                    className="button primary"
                    disabled={viewer || !!selected || busy}
                    onClick={() => choose(item)}
                  >
                    Use this workflow
                  </button>
                </div>
              ) : null;
            })}
          </article>
        ))}
      </div>
      {selected && !missing && (
        <div className="agent-match">
          <h3>Review {selected.capability.name}</h3>
          <dl>
            {fields.map((field) => (
              <div key={field}>
                <dt>{field}</dt>
                <dd>{values[field]}</dd>
              </div>
            ))}
          </dl>
          <label>
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />{" "}
            Authorize changes for this synthetic run
          </label>
          <p>
            Leave unchecked to pause for human approval before a protected
            change.
          </p>
          <button
            className="button primary"
            disabled={busy || viewer}
            onClick={() => void run()}
          >
            Run workflow
          </button>
        </div>
      )}
      <form onSubmit={submit} className="agent-composer">
        <label htmlFor="agent-request">Message your assistant</label>
        <textarea
          id="agent-request"
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={2000}
          required
          placeholder={
            missing
              ? `Enter ${missing}`
              : "Describe a task, or type cancel to reset"
          }
        />
        <button
          className="button primary"
          disabled={busy || !csrf || !text.trim()}
        >
          {busy ? "Working…" : "Send message"}
        </button>
      </form>
      <button
        className="button secondary"
        disabled={viewer || busy}
        onClick={record}
      >
        Record a workflow
      </button>
      <p className="muted">
        Conversation stays in this page's memory. Local Ollama matches tasks;
        input collection and replay are deterministic.
      </p>
    </section>
  );
}
