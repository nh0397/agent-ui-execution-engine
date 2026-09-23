import { useState, useEffect, useRef, type FormEvent } from "react";
import { ModelStatus, useConversationHistory, type ChatSnapshot } from "./ConversationHistory";
import { request, type Run, type CatalogItem } from "./api";
const discoveryId = "address-discovery";
type DiscoverySpec = Pick<CatalogItem["capability"], "name" | "description" | "inputs" | "outputs">;
const discoveryItem = (spec: DiscoverySpec): CatalogItem => ({id: discoveryId, capability: {...spec, version: 1, app: "customer-service", steps: [], discovery_run: ""}});
type Message = { role: "you" | "agent"; text: string; matches?: string[] | null; run_id?: string };
type MatchReply = { matches: string[]; catalog_count: number; intent?: "use_workflow" | "discover" };
// Only triggers a model intent check for a draft follow-up; never chooses an execution mode.
const mayRequestLearning = /\b(?:learn|discover|rediscover|discovery|from scratch|new workflow)\b/i;
export function Agent({
  catalog,
  csrf,
  viewer,
  onRun,
  record,
  discover,
  runs,
}: {
  catalog: CatalogItem[];
  csrf: string;
  viewer: boolean;
  onRun: (id: string) => void;
  record: () => void;
  discover: (goal: string) => void;
  runs: Run[];
}) {
  const conversation = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const [chatRun, setChatRun] = useState<string | null>(null);
  const reported = useRef(new Set<string>());
  const [noMatch, setNoMatch] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  useEffect(() => {
    const pane = conversation.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [messages]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [showWorkflows, setShowWorkflows] = useState(false);
  const [manual, setManual] = useState(false);
  const [initialRequest, setInitialRequest] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [discoveryDraft, setDiscoveryDraft] = useState<CatalogItem | null>(null);
  const selected = selectedId === discoveryId ? discoveryDraft : catalog.find(item => item.id === selectedId) || null;
  useEffect(() => {
    if (selectedId !== discoveryId || discoveryDraft || !csrf) return;
    let disposed = false;
    void request<DiscoverySpec>("/workflow-spec").then(spec => {if (!disposed) setDiscoveryDraft(discoveryItem(spec));}).catch(() => {if (!disposed) setMessages(old => [...old, {role:"agent", text:"I could not restore the discovery draft. Start a new request or retry after reconnecting."}]);});
    return () => {disposed = true;};
  }, [selectedId, discoveryDraft, csrf]);
  const setSelected = (item:CatalogItem|null) => setSelectedId(item?.id || null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [approved, setApproved] = useState(false);
  const history = useConversationHistory({messages,selected_id:selectedId,values,initial_request:initialRequest,run_id:chatRun}, (saved:ChatSnapshot) => {
    setMessages(saved.messages);setSelectedId(saved.selected_id);setValues(saved.values);
    setInitialRequest(saved.initial_request);setChatRun(saved.run_id);setApproved(false);
    setManual(!!saved.selected_id && saved.selected_id !== discoveryId);setNoMatch(false);setRetryMessage(null);setText("");setShowWorkflows(false);
  }, csrf);
  const fields = Object.keys(selected?.capability.inputs || {});
  const awaitingChoice = !selected && !busy && !!messages.at(-1)?.matches?.length;
  const missing = fields.find((field) => !values[field]);
  const say = (message: string, matches?: string[]) =>
    setMessages((old) => [...old, { role: "agent", text: message, matches }]);
  const execution = runs.find((run) => run.id === chatRun);
  useEffect(() => {
    if (!history.ready || !execution || execution.status === "running" || reported.current.has(execution.id) || messages.some(m => m.run_id === execution.id)) return;
    let disposed = false;
    const fallback = execution.status === "success"
      ? "This run completed, but its detailed answer is no longer available. Run a fresh inquiry to get the current result."
      : "I couldn't complete the task. Open the run details to see what happened before trying again.";
    const publish = (text: string) => {
      if (disposed) return;
      reported.current.add(execution.id);
      setMessages(old => old.some(m => m.run_id === execution.id) ? old : [...old, {role:"agent", text, run_id:execution.id}]);
    };
    void request<{message: string | null}>(`/runs/${execution.id}/answer`).then(reply => publish(reply.message || fallback)).catch(() => publish(fallback));
    return () => {disposed = true;};
  }, [execution?.id, execution?.status, history.ready, history.id, csrf, messages]);
  function newRequest() {
    void history.load("").then(() => composer.current?.focus());
  }
  async function readValues(
    item: CatalogItem,
    message: string,
    previous: Record<string, string>,
    checkIntent = true,
  ) {
    setBusy(true);
    setRetryMessage(null);
    try {
      if (checkIntent && item.id !== discoveryId && mayRequestLearning.test(message)) {
        const routing = await request<MatchReply>("/agent/match", {
          method: "POST", body: JSON.stringify({message}),
        }, csrf);
        if (routing.intent === "discover") {
          const context = JSON.stringify({earlier_task: initialRequest, supplied_details: previous});
          if (!await prepareDiscovery(message, context)) {
            setSelected(null); setValues({}); setApproved(false); setNoMatch(false);
            say("I can currently learn address changes. I can’t discover this task yet. You can record its steps instead; nothing has been run.");
          }
          return;
        }
      }
      const reply = await request<{ values: Record<string, string> }>(
        "/agent/inputs",
        {
          method: "POST",
          body: JSON.stringify({ capability_id: item.id, message }),
        },
        csrf,
      );
      const updated = { ...previous, ...reply.values };
      setValues(updated);
      setManual(false);
      setApproved(false);
      const remaining = Object.keys(item.capability.inputs).filter(
        (field) => !updated[field],
      );
      say(
        remaining.length
          ? `What ${remaining.map((field) => field.replaceAll("_", " ")).join(", ")} should I use?`
          : "I have the details. Please review them below before I run this workflow.",
      );
    } catch (error) {
      setRetryMessage(message);
      setManual(true);
      say((error as Error).message + " You can enter the details manually below; nothing has been run.");
    } finally {
      setBusy(false);
    }
  }
  async function choose(item: CatalogItem) {
    setSelected(item);
    setNoMatch(false);
    setShowWorkflows(false);
    setManual(false);
    setValues({});
    setApproved(false);
    say(
      `I'll use ${item.capability.name}. Let me pick up the details from your request.`,
    );
    await readValues(item, initialRequest, {}, false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const input = text.trim();
    if (!input || busy || !history.ready) return;
    setText("");
    setMessages((old) => [...old, { role: "you", text: input }]);
    if (input.toLowerCase() === "cancel") {
      setSelected(null);
      setRetryMessage(null);
      setManual(false);
      setShowWorkflows(false);
      setValues({});
      say(
        "Cleared the draft request. This does not stop a running execution; use its Cancel run control. What would you like to do next?",
      );
      return;
    }
    if (selected) {
      await readValues(selected, input, values);
      return;
    }
    await findWorkflow(input);
  }
  async function prepareDiscovery(input: string, context?: string) {
    const prepared = await request<{supported: boolean; spec?: DiscoverySpec; values?: Record<string,string>}>(
      "/agent/discovery", {method:"POST", body:JSON.stringify({message:input, context})}, csrf);
    if (!prepared.supported || !prepared.spec) return false;
    const item = discoveryItem(prepared.spec);
    const extracted = prepared.values || {};
    setDiscoveryDraft(item); setSelectedId(discoveryId); setValues(extracted);
    setManual(false); setApproved(false); setNoMatch(false); setShowWorkflows(false);
    const missingFields = Object.keys(item.capability.inputs).filter(key => !extracted[key]);
    say(missingFields.length
      ? `I can learn this address change. I still need ${missingFields.map(key=>key.replaceAll("_", " ")).join(", ")}. Reply here with those details.`
      : "I’ll learn this from scratch in the browser. I have the address details—review them below and confirm when you’re ready.");
    return true;
  }
  async function findWorkflow(input: string) {
    setInitialRequest(input);
    setNoMatch(false);
    setRetryMessage(null);
    setShowWorkflows(false);
    setBusy(true);
    try {
      const reply = await request<MatchReply>(
        "/agent/match",
        { method: "POST", body: JSON.stringify({ message: input }) },
        csrf,
      );
      if (!reply.matches.length || reply.intent === "discover") {
        if (await prepareDiscovery(input)) return;
        if (reply.intent === "discover") {
          setNoMatch(false);
          say("I can currently learn address changes. I can’t discover this task yet. You can record its steps instead; nothing has been run.");
          return;
        }
      }
      setNoMatch(reply.matches.length === 0);
      say(
        reply.matches.length
          ? "This saved workflow can help. Choose it to review the details from your message."
          : "I don't have a matching published workflow yet. I can help you set up an agent discovery, or you can show me the steps by recording a demonstration.",
        reply.matches,
      );
    } catch (error) {
      setRetryMessage(input);
      setShowWorkflows(true);
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
            mode: selected.id === discoveryId ? "discovery" : "replay",
            goal: selected.id === discoveryId ? "Update the customer identified by customer_id with the supplied street, city and postal inputs. Verify the saved customer ID and all saved address fields. Return every declared output." : "",
            capability_id: selected.id,
            inputs: values,
            approve_writes: approved,
          }),
        },
        csrf,
      );
      say(
        selected.id === discoveryId ? "I’m learning how to do that now. You can watch the browser as I work." : "I’m on it. I’ll let you know what I find when the task finishes.",
      );
      setSelected(null);
      setValues({});
      setApproved(false);
      setChatRun(result.id);
      onRun(result.id);
    } catch (error) {
      say((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className={`panel agent-panel conversational ${messages.length ? "has-messages" : "is-empty"}`}>
      <div className="conversation-storage">
        <select aria-label="Saved conversations" value={history.items.some(item=>item.id===history.id) ? history.id : ""} disabled={busy || !history.ready} onChange={e=>void history.load(e.target.value)}>
          <option value="">New conversation</option>{history.items.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}
        </select><ModelStatus csrf={csrf}/>
      </div>
      {history.error && <p role="alert">{history.error}</p>}
      <div ref={conversation} className="chat-thread">
      <div className="conversation-heading">
        <div><p className="eyebrow">WORKFLOW ASSISTANT</p>
          <h2>{messages.length ? "Let’s get this done." : "What would you like to do?"}</h2></div>
        {messages.length > 0 && <button className="button secondary" disabled={busy || !history.ready} onClick={newRequest} title="Start a separate saved conversation. Does not stop an active run.">New request</button>}
      </div>
      {!messages.length && <p className="chat-intro">{catalog.length ? "Tell me the activity and any customer, account, or card details you know. I’ll help you review everything before it runs." : "No saved workflows yet. Describe an address change and I’ll help you teach the agent. You can also record a workflow yourself."}</p>}
      <div className="agent-conversation" role="log" aria-label="Conversation" aria-live="polite">
        {messages.map((message, index) => (
          <article
            key={index}
            className={
              message.role === "you" ? "agent-question" : "agent-answer"
            }
          >
            <small>{message.role === "you" ? "You" : "Assistant"}</small>
            <p>{message.text}</p>
            {message.matches?.map((id) => {
              const item = catalog.find((candidate) => candidate.id === id);
              return item ? (
                <div className="agent-match workflow-choice" key={id}>
                  {index === messages.length - 1 && !selected && <p className="next-step-label">NEXT STEP · SELECT A WORKFLOW</p>}
                  <h3>{item.capability.name}</h3>
                  <details className="workflow-description"><summary>What this workflow does</summary><p>{item.capability.description}</p></details>
                  <p className="workflow-scope">Details this workflow accepts: {Object.keys(item.capability.inputs).map((key) => key.replaceAll("_", " ")).join(", ")}.</p>
                  <div className="workflow-choice-footer"><small>
                    {item.capability.steps.length} recorded actions · Version{" "}
                    {item.capability.version}
                  </small>
                  <button
                    className="button primary"
                    disabled={viewer || !!selected || busy || index !== messages.length - 1}
                    onClick={() => void choose(item)}
                  >
                    Use this workflow
                  </button></div>
                  <p className="workflow-choice-hint">Select this to review the details. Nothing runs yet.</p>
                </div>
              ) : null;
            })}
          </article>
        ))}
      </div>
      {noMatch && !selected && <div className="chat-next-step"><button className="button primary" disabled={busy || viewer} onClick={() => discover(initialRequest)}>Learn with the agent</button><button className="button secondary" disabled={busy || viewer} onClick={record}>Show the steps</button><p>You’ll review the setup before discovery or recording begins.</p></div>}
      {execution?.status === "running" && <p role="status" className="chat-execution">{execution.live?.owner === "human" ? "I need your help in the browser. Review the message there to continue." : "Working in the browser. You can watch each step alongside this conversation."}</p>}
      {busy && <p role="status">{selected ? "Reading the details in your message…" : "Understanding your request…"} The model may take a moment.</p>}
      {retryMessage !== null && !busy && (
        <button className="button secondary" onClick={() => selected ? void readValues(selected, retryMessage, values) : void findWorkflow(retryMessage)}>Retry last message</button>
      )}
      {showWorkflows && !selected && <div className="agent-match">
        <p>Select a workflow yourself. These are your saved workflows, not model recommendations.</p>
        {catalog.map((item) => <button key={item.id} className="button secondary" disabled={busy || viewer} onClick={() => void choose(item)}>{item.capability.name}</button>)}
      </div>}
      {selected && <div className="agent-manual chat-review">
        <button className="text-button" disabled={busy} onClick={() => setManual(!manual)}>{manual ? "Hide input fields" : "Enter or edit details manually"}</button>
        {manual && <fieldset disabled={busy || viewer}><legend>Details for {selected.capability.name}</legend>
          <p>Check or correct these details. This workflow changes only the fields listed here.</p>
          {fields.map((field) => <label key={field}>{field.replaceAll("_", " ")}
            <input aria-label={`Workflow input ${field}`} value={values[field] || ""} onChange={(e) => { setValues({ ...values, [field]: e.target.value }); setApproved(false); }} />
          </label>)}
          <p>Review these values before running. Missing details are never guessed.</p>
        </fieldset>}
      </div>}
      {selected && !missing && (
        <div className="agent-match">
          <p className="workflow-mode">{selected.id === discoveryId ? "New workflow · AI will learn the steps" : "Saved workflow · Replay recorded steps"}</p>
          <h3>{selected.id === discoveryId ? "Ready to learn this address change" : "Ready when you are"}</h3>
          {!manual && <dl>
            {fields.map((field) => (
              <div key={field}>
                <dt>{field.replaceAll("_", " ")}</dt>
                <dd>{values[field]}</dd>
              </div>
            ))}
          </dl>}
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
            {selected.id === discoveryId ? "Confirm and start discovery" : "Run workflow"}
          </button>
        </div>
      )}
      <div className="agent-examples" hidden={messages.length > 0}>
        {[
          "Check the balance of account AC-10002",
          "Update the mailing address for customer C-1001",
          "Freeze debit card DC-205",
        ].map((example) => (
          <button
            className="button secondary"
            key={example}
            disabled={!!selected || busy}
            onClick={() => { setText(example); composer.current?.focus(); }}
          >
            {example}
          </button>
        ))}
      </div>
      </div>
      {awaitingChoice && <p className="selection-prompt" role="status">Choose <strong>Use this workflow</strong> above to continue, or send a different request.</p>}
      <form onSubmit={submit} className="agent-composer">
        <label htmlFor="agent-request">Message your assistant</label>
        <textarea
          id="agent-request"
          ref={composer}
          disabled={!history.ready}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!busy && csrf && text.trim()) event.currentTarget.form?.requestSubmit();
            }
          }}
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={2000}
          required
          placeholder={
            missing
              ? `Enter ${missing}`
              : awaitingChoice ? "Or describe a different activity…" : messages.length ? "Add details or ask for a correction…" : "For example: Check the balance of account AC-10002"
          }
        />
        <div className="composer-footer"><span>Enter to send · Shift + Enter for a new line</span><button
          className="button primary"
          disabled={busy || !csrf || !history.ready || !text.trim()}
        >
          {busy ? "Working…" : "Send message"}
        </button></div>
      </form>
      <div className="chat-alternatives"><p className="chat-action-label">Other ways to start <span>Choose a saved workflow, let the agent learn, or demonstrate the steps.</span></p><div className="chat-secondary-actions" role="group" aria-label="Workflow actions">
      {!selected && catalog.length > 0 && !busy && (
        <button className="button secondary" aria-expanded={showWorkflows} onClick={() => setShowWorkflows(!showWorkflows)}>Choose a saved workflow</button>
      )}
      <button className="button secondary" disabled={viewer || busy} onClick={() => discover(text.trim() || initialRequest)}>Discover a workflow</button>
      <button
        className="button secondary"
        disabled={viewer || busy}
        onClick={record}
      >
        Record a workflow
      </button>
      </div>
      </div>
      <p className="chat-footnote">Nothing runs until you confirm. Conversations are saved locally for this demo profile.</p>
    </section>
  );
}
