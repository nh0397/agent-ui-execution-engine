import { useState, type FormEvent } from "react";
import { request, type CatalogItem } from "./api";

type Reply = { matches: string[]; model_used: boolean; catalog_count: number };
type Turn = { question: string; reply?: Reply; error?: string };

export function Agent({
  catalog,
  csrf,
  viewer,
  replay,
  record,
}: {
  catalog: CatalogItem[];
  csrf: string;
  viewer: boolean;
  replay: (id: string) => void;
  record: () => void;
}) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = message.trim();
    if (!question || busy) return;
    setBusy(true);
    setMessage("");
    setTurns((previous) => [...previous, { question }]);
    try {
      const reply = await request<Reply>(
        "/agent/match",
        {
          method: "POST",
          body: JSON.stringify({ message: question }),
        },
        csrf,
      );
      setTurns((previous) => [...previous.slice(0, -1), { question, reply }]);
    } catch (error) {
      setTurns((previous) => [
        ...previous.slice(0, -1),
        { question, error: (error as Error).message },
      ]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel agent-panel">
      <p className="eyebrow">DESCRIBE · MATCH · REVIEW · RUN</p>
      <h2>What would you like to do?</h2>
      <p>
        Describe a banking task. I’ll check the {catalog.length} published
        workflows for a match, then ask you to supply its inputs. Nothing runs
        until you start it.
      </p>
      <div className="agent-examples">
        {[
          "Update a customer's mailing address",
          "Look up an account balance",
          "Freeze a debit card",
        ].map((example) => (
          <button
            className="button secondary"
            key={example}
            onClick={() => setMessage(example)}
          >
            {example}
          </button>
        ))}
      </div>
      <div className="agent-conversation" aria-live="polite">
        {turns.map((turn, index) => (
          <article className="agent-turn" key={index}>
            <div className="agent-question">
              <small>YOU</small>
              <p>{turn.question}</p>
            </div>
            <div className="agent-answer">
              <small>WORKFLOW AGENT</small>
              {turn.error ? (
                <p role="alert">{turn.error}</p>
              ) : !turn.reply ? (
                <p>Checking saved workflows with the local model…</p>
              ) : (
                <>
                  <p>
                    {turn.reply.matches.length
                      ? "I found these possible matches. Review the purpose and required inputs, then choose the workflow you want."
                      : turn.reply.catalog_count === 0
                        ? "There are no published workflows yet. Record a task, verify its result, and publish it. Then ask me again."
                        : "I couldn’t find a suitable saved workflow for that request. You can describe the task more specifically or record a new demonstration."}
                  </p>
                  {turn.reply.matches.map((id) => {
                    const item = catalog.find(
                      (candidate) => candidate.id === id,
                    );
                    return item ? (
                      <div className="agent-match" key={id}>
                        <h3>{item.capability.name}</h3>
                        <p>{item.capability.description}</p>
                        <small>
                          {item.capability.source === "human"
                            ? "Human recording"
                            : "LLM discovery"}{" "}
                          · Version {item.capability.version} ·{" "}
                          {item.capability.steps.length} actions
                        </small>
                        <p>
                          Required inputs:{" "}
                          {Object.keys(item.capability.inputs).join(", ") ||
                            "None"}
                        </p>
                        <button
                          className="button primary"
                          disabled={viewer}
                          onClick={() => replay(id)}
                        >
                          Use this workflow
                        </button>
                      </div>
                    ) : (
                      <p key={id}>
                        This workflow is no longer available. Search again.
                      </p>
                    );
                  })}
                  {!turn.reply.matches.length && (
                    <button
                      className="button primary"
                      disabled={viewer}
                      onClick={record}
                    >
                      Record a new workflow
                    </button>
                  )}
                  <p className="muted">
                    {turn.reply.model_used
                      ? "Matched by local Ollama. Replay uses no model decisions."
                      : "Catalog is empty; no model call was needed."}
                  </p>
                </>
              )}
            </div>
          </article>
        ))}
      </div>
      <form onSubmit={submit} className="agent-composer">
        <label htmlFor="agent-request">Describe your task</label>
        <textarea
          id="agent-request"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          maxLength={2000}
          rows={3}
          placeholder="I need to freeze a customer's debit card"
          required
        />
        <button
          className="button primary"
          disabled={busy || !csrf || !message.trim()}
        >
          {busy ? "Searching…" : "Find a workflow"}
        </button>
        <p className="muted">
          Each message is a new catalog search. Enter customer details in the
          input form after selecting a workflow. Messages stay in this page's
          memory.
        </p>
      </form>
    </section>
  );
}
