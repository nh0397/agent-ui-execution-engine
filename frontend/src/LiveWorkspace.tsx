import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  CircleCheck,
  Code2,
  ExternalLink,
  LayoutDashboard,
  ListChecks,
  Monitor,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  StopCircle,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { request, type Run, type CatalogItem } from "./api";
import { RecordingTools, RecordingDocument } from "./Recording";
import { Agent } from "./Agent";
import archive from "./generated/evidence.json";
import "./live.css";
const people = [
  { id: "mira", name: "Mira Chen", initials: "MC", role: "Operator" },
  { id: "sam", name: "Sam Rivera", initials: "SR", role: "Operator" },
  { id: "taylor", name: "Taylor Morgan", initials: "TM", role: "Viewer" },
];
const pages = [
  "Overview",
  "New workflow",
  "Capabilities",
  "Run history",
  "Live session",
  "Banking app",
] as const;
type Page = (typeof pages)[number];
const icons = [LayoutDashboard, Workflow, Box, Activity, Monitor, ExternalLink];
function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Dialog({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} aria-label={title} onCancel={close}>
      <div className="dialog-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={close}
        >
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function status(run: Run) {
  return run.status === "running" && run.live?.owner === "human"
    ? "Needs your review"
    : run.status === "running"
      ? "Running"
      : run.status === "success"
        ? "Completed"
        : run.status === "business_outcome"
          ? "Business outcome"
          : "Failed";
}
function RunTable({
  visibleRuns,
  runs,
  viewer,
  onLive,
  onDetail,
  onNew,
}: {
  visibleRuns: Run[];
  runs: Run[];
  viewer: boolean;
  onLive: (id: string) => void;
  onDetail: (run: Run) => void;
  onNew: () => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Mode</th>
            <th>Result</th>
            <th>Actions</th>
            <th>Model decisions</th>
            <th>Inspect</th>
          </tr>
        </thead>
        <tbody>
          {visibleRuns.map((run) => (
            <tr key={run.id}>
              <td>
                <button
                  className="table-title"
                  onClick={() => {
                    onLive(run.id);
                  }}
                >
                  {(run.name || "Customer address update").replaceAll("_", " ")}
                </button>
                <small className="mono">
                  {run.id.slice(0, 8)} ·{" "}
                  {new Date(run.created * 1000).toLocaleTimeString()}
                </small>
              </td>
              <td>{run.mode}</td>
              <td>
                <Badge
                  tone={
                    run.status === "success"
                      ? "green"
                      : run.status === "failure"
                        ? "red"
                        : "amber"
                  }
                >
                  {status(run)}
                </Badge>
              </td>
              <td>{run.actions}</td>
              <td>{run.model_decisions}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label={`Inspect run ${run.id}`}
                  onClick={() => onDetail(run)}
                >
                  <ArrowUpRight size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!visibleRuns.length && (
        <div className="empty">
          <Activity />
          <h3>
            {runs.length
              ? "No matching runs"
              : "Your first live run starts here."}
          </h3>
          <p>
            {runs.length
              ? "Try another search."
              : "Start discovery against Cedar Bank, then replay the resulting capability."}
          </p>
          <button
            className="button primary"
            onClick={() => onNew()}
            disabled={viewer}
          >
            Create a workflow <ArrowRight size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
export default function LiveWorkspace() {
  const [page, setPage] = useState<Page>("Overview");
  const [person, setPerson] = useState(people[0]);
  const [profileDialog, setProfileDialog] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [health, setHealth] = useState<{
    bank: boolean;
    bank_url?: string;
    model: boolean;
    models?: string[];
  } | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const [detail, setDetail] = useState<Run | null>(null);
  const [inspect, setInspect] = useState<CatalogItem | null>(null);
  const [showArchive, setShowArchive] = useState(false);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"replay" | "discovery" | "recording">(
    "discovery",
  );
  const [capId, setCapId] = useState("example");
  const [goal, setGoal] = useState(
    "Update the customer identified by customer_id with the supplied street, city and postal inputs. Verify the saved customer ID and all saved address fields. Return every declared output.",
  );
  const [workflowName, setWorkflowName] = useState("Customer address change");
  const [template, setTemplate] = useState<CatalogItem["capability"] | null>(
    null,
  );
  const [inputs, setInputs] = useState<Record<string, string>>({
    customer_id: "C-104",
    street: "41 Cedar Avenue",
    city: "Sampletown",
    postal: "12345",
  });
  const [scenario, setScenario] = useState("normal");
  const [approved, setApproved] = useState(false);
  const [model, setModel] = useState("mistral:latest");
  const [typing, setTyping] = useState("");
  const [frameTick, setFrameTick] = useState(0);
  const [imageError, setImageError] = useState(false);
  const current =
    runs.find((r) => r.id === selected) ||
    runs.find((r) => r.status === "running") ||
    runs[0];
  const inputSchema =
    (mode === "replay"
      ? catalog.find((c) => c.id === capId)?.capability
      : template
    )?.inputs || {};
  const active = runs.find((r) => r.status === "running");
  const viewer = person.role === "Viewer";
  const canControl =
    current?.status === "running" && current.live?.owner === "human" && !viewer;
  const visibleRuns = runs.filter((r) =>
    `${r.id} ${r.mode} ${r.status} ${r.code}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  async function refresh() {
    const [list, caps] = await Promise.all([
      request<Run[]>("/runs"),
      request<CatalogItem[]>("/capabilities"),
    ]);
    setRuns(list);
    setCatalog(caps);
    setOnline(true);
  }
  async function choose(p: (typeof people)[number]) {
    try {
      const s = await request<{ csrf: string }>("/session", {
        method: "POST",
        body: JSON.stringify({ profile_id: p.id }),
      });
      setCsrf(s.csrf);
      setPerson(p);
      setProfileDialog(false);
      await refresh();
      setTemplate(await request<CatalogItem["capability"]>("/workflow-spec"));
      setError("");
    } catch (e) {
      setOnline(false);
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    let stopped = false;
    void choose(people[0]);
    const poll = setInterval(() => {
      if (!stopped) void refresh().catch(() => setOnline(false));
    }, 1200);
    const check = () =>
      request<typeof health>("/health")
        .then((h) => {
          if (!stopped) setHealth(h);
        })
        .catch(() => {
          if (!stopped) setHealth(null);
        });
    void check();
    const healthPoll = setInterval(check, 8000);
    return () => {
      stopped = true;
      clearInterval(poll);
      clearInterval(healthPoll);
    };
  }, []);
  useEffect(() => {
    if (!current?.live?.has_frame) return;
    const timer = setInterval(() => setFrameTick((t) => t + 1), 800);
    return () => clearInterval(timer);
  }, [current?.id, current?.live?.has_frame]);
  useEffect(() => {
    setImageError(false);
  }, [current?.id]);
  function navigate(p: Page) {
    setPage(p);
    setError("");
  }
  async function start(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const run = await request<{ id: string }>(
        "/runs",
        {
          method: "POST",
          body: JSON.stringify({
            mode,
            goal: mode === "recording" ? workflowName : goal,
            inputs:
              mode === "recording"
                ? {}
                : Object.fromEntries(
                    Object.keys(inputSchema).map((k) => [k, inputs[k] || ""]),
                  ),
            name: workflowName,
            capability_id: capId,
            scenario,
            approve_writes: approved,
            model,
          }),
        },
        csrf,
      );
      setSelected(run.id);
      await refresh();
      setPage("Live session");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function command(value: Record<string, unknown>) {
    if (!current) return;
    try {
      await request(
        `/runs/${current.id}/control`,
        { method: "POST", body: JSON.stringify(value) },
        csrf,
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function prepareReplay(id: string) {
    setCapId(id);
    setMode("replay");
    const sample: Record<string, string> = {
      customer_id: "C-205",
      street: "62 Test Street",
      city: "Demoville",
      postal: "54321",
      account_id: "AC-4205",
      card_id: "DC-205",
    };
    const schema = catalog.find((c) => c.id === id)?.capability.inputs || {};
    setInputs(
      Object.fromEntries(
        Object.keys(schema).map((key) => [key, sample[key] || ""]),
      ),
    );
    setPage("New workflow");
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            navigate("Overview");
          }}
        >
          <span className="brand-mark">
            <Workflow size={23} />
          </span>
          <span>
            agent<span className="brand-light">ui</span>
            <small>EXECUTION WORKSPACE</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-icon">C</span>
          <span>
            Cedar Bank sandbox<small>Local execution environment</small>
          </span>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map((name, i) => {
            const Icon = icons[i];
            return (
              <button
                key={name}
                className={`nav-item ${page === name ? "active" : ""}`}
                onClick={() => navigate(name)}
                aria-current={page === name ? "page" : undefined}
              >
                <Icon size={18} />
                {name}
                {name === "Live session" && active && (
                  <span className="nav-count">1</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="guard-card">
            <ShieldCheck />
            <strong>Real UI. Real execution.</strong>
            <p>
              The model discovers.
              <br />
              Saved capabilities replay.
            </p>
            <span>
              {online
                ? "Execution API connected"
                : "Connecting to execution API…"}
            </span>
          </div>
          <button
            className="profile-button"
            onClick={() => setProfileDialog(true)}
          >
            <span className="avatar">{person.initials}</span>
            <span>
              {person.name}
              <small>{person.role} · demo session</small>
            </span>
            <ChevronDown size={15} />
          </button>
        </div>
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace</span>
            <span className="slash">/</span>
            <strong>{page}</strong>
          </div>
          <div className="top-actions">
            <span className="evidence-indicator">
              <span className={online ? "" : "offline"} />
              {online ? "Live API connected" : "API unavailable"}
            </span>
            <button
              className="icon-button"
              aria-label="Choose demo profile"
              onClick={() => setProfileDialog(true)}
            >
              <Users size={18} />
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="eyebrow">FROM INTENT TO EXECUTION</p>
              <h1>
                {page === "Overview"
                  ? "Your banking workflow assistant."
                  : page === "New workflow"
                    ? "Give your workflow a goal."
                    : page === "Capabilities"
                      ? "Learn once. Run again."
                      : page === "Run history"
                        ? "Every action, accounted for."
                        : page === "Live session"
                          ? "Your workflow, live."
                          : "Meet Cedar Bank."}
              </h1>
              <p className="subtitle">
                {page === "New workflow"
                  ? "Start the real Python engine against the banking application."
                  : page === "Live session"
                    ? "Watch the same browser the engine operates. Intervene when control passes to you."
                    : "A complete local workspace for discovering and replaying UI workflows."}
              </p>
            </div>
            {page !== "New workflow" && (
              <button
                className="button primary"
                onClick={() => navigate("New workflow")}
                disabled={viewer || !online}
              >
                <Plus size={16} />
                New workflow
              </button>
            )}
          </div>
          {error && (
            <div className="error-banner" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          {!online && (
            <div className="callout">
              The execution API is unavailable. Start the project with{" "}
              <code>start.ps1</code>. This dashboard requires the Python
              backend; it does not simulate runs.
            </div>
          )}
          <div
            hidden={
              !["Overview", "New workflow", "Live session"].includes(page)
            }
          >
            <Agent
              key={person.id}
              catalog={catalog}
              csrf={csrf}
              viewer={viewer}
              onRun={(id) => {
                setSelected(id);
                void refresh();
                setPage("Live session");
              }}
              record={() => {
                setMode("recording");
                setPage("New workflow");
              }}
            />
          </div>
          {page === "Overview" && (
            <details className="workspace-summary">
              <summary>Execution overview and service status</summary>
              <section className="hero">
                <div>
                  <Badge tone="hero-badge">
                    CONNECTED AUTOMATION WORKSPACE
                  </Badge>
                  <h2>
                    Give the engine a goal.
                    <br />
                    Watch it work through the UI.
                  </h2>
                  <p>
                    Search a customer, update their address, and verify the
                    result.
                    <br />
                    Capture a reusable capability and run it again with new
                    inputs.
                  </p>
                  <button
                    className="button light"
                    disabled={viewer || !online}
                    onClick={() => {
                      setMode("discovery");
                      navigate("New workflow");
                    }}
                  >
                    <Sparkles size={16} /> Start discovery
                  </button>
                </div>
                <div className="service-health">
                  <h3>Environment</h3>
                  <div>
                    <span>Execution API</span>
                    <Badge tone={online ? "green" : "red"}>
                      {online ? "Connected" : "Unavailable"}
                    </Badge>
                  </div>
                  <div>
                    <span>Cedar Bank + database</span>
                    <Badge tone={health?.bank ? "green" : "red"}>
                      {health?.bank ? "Ready" : "Unavailable"}
                    </Badge>
                  </div>
                  <div>
                    <span>Local model service</span>
                    <Badge tone={health?.model ? "green" : "amber"}>
                      {health?.model ? "Ready" : "Unavailable"}
                    </Badge>
                  </div>
                  <small>
                    Replay works without a model. Discovery requires an
                    installed local model.
                  </small>
                </div>
              </section>
              <section className="stats">
                {[
                  {
                    name: "Live runs",
                    value: runs.length,
                    note: "Started through this workspace",
                  },
                  {
                    name: "Completed",
                    value: runs.filter((r) => r.status === "success").length,
                    note: "Verified terminal outcomes",
                  },
                  {
                    name: "Capabilities",
                    value: catalog.length,
                    note: "Includes the original example",
                  },
                  {
                    name: "Active session",
                    value: active
                      ? active.live?.owner === "human"
                        ? "Your turn"
                        : "Running"
                      : "Idle",
                    note: active
                      ? "One session at a time"
                      : "Ready for a new workflow",
                  },
                ].map((m) => (
                  <article className="stat" key={m.name}>
                    <span className="stat-title">{m.name}</span>
                    <strong>{m.value}</strong>
                    <small>{m.note}</small>
                  </article>
                ))}
              </section>
              <div className="section-heading">
                <div>
                  <h2>Live run history</h2>
                  <p>Results from the connected execution backend.</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => navigate("Run history")}
                >
                  View runs <ArrowRight size={15} />
                </button>
              </div>
              <section className="panel">
                <RunTable
                  visibleRuns={visibleRuns}
                  runs={runs}
                  viewer={viewer}
                  onLive={(id) => {
                    setSelected(id);
                    setPage("Live session");
                  }}
                  onDetail={setDetail}
                  onNew={() => navigate("New workflow")}
                />
              </section>
              <div className="bottom-grid">
                <section className="panel next-step">
                  <p className="eyebrow">THE APPLICATION UNDER AUTOMATION</p>
                  <h3>Cedar Bank customer workspace</h3>
                  <p>
                    Three synthetic customers, checking and savings accounts,
                    transaction history, and an address-change flow with review
                    and confirmation.
                  </p>
                  <a
                    className="button secondary"
                    href={health?.bank_url || "http://127.0.0.1:8000"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open banking application <ExternalLink size={15} />
                  </a>
                </section>
                <section className="panel featured-cap">
                  <h3>Prior verified evidence</h3>
                  <p>
                    The original discovery and replay records remain available
                    for comparison. They are separate from the live runs above.
                  </p>
                  <button
                    className="text-button"
                    onClick={() => setShowArchive(true)}
                  >
                    Inspect archived evidence <ArrowUpRight size={15} />
                  </button>
                </section>
              </div>
            </details>
          )}
          {page === "New workflow" && (
            <div className="form-layout">
              <form className="panel workflow-form" onSubmit={start}>
                <div className="section-heading">
                  <h2>Run configuration</h2>
                  <Badge tone={health?.bank ? "green" : "amber"}>
                    Cedar Bank {health?.bank ? "ready" : "offline"}
                  </Badge>
                </div>
                <fieldset disabled={viewer || busy}>
                  <legend>Execution mode</legend>
                  <div className="mode-picker">
                    <button
                      type="button"
                      className={mode === "discovery" ? "selected" : ""}
                      onClick={() => setMode("discovery")}
                    >
                      <Sparkles />
                      <strong>Discover workflow</strong>
                      <small>Real model-selected UI actions</small>
                    </button>
                    <button
                      type="button"
                      className={mode === "replay" ? "selected" : ""}
                      onClick={() => setMode("replay")}
                    >
                      <Play />
                      <strong>Replay capability</strong>
                      <small>No model decisions</small>
                    </button>
                    <button
                      type="button"
                      className={mode === "recording" ? "selected" : ""}
                      onClick={() => setMode("recording")}
                    >
                      <Monitor />
                      <strong>Record workflow</strong>
                      <small>Demonstrate it yourself</small>
                    </button>
                  </div>
                  {mode === "recording" ? (
                    <>
                      <label>
                        Workflow name
                        <input
                          aria-label="Workflow name"
                          required
                          value={workflowName}
                          onChange={(e) => setWorkflowName(e.target.value)}
                        />
                      </label>
                      <p className="callout">
                        You will control the managed browser. Supported clicks
                        and field entries are documented with redacted
                        screenshots. Example values stay out of the saved
                        capability. Review it before publishing.
                      </p>
                    </>
                  ) : mode === "discovery" ? (
                    <>
                      <label>
                        Goal
                        <textarea
                          aria-label="Goal"
                          required
                          maxLength={2000}
                          rows={4}
                          value={goal}
                          onChange={(e) => setGoal(e.target.value)}
                        />
                      </label>
                      <label>
                        Local model
                        <select
                          value={model}
                          onChange={(e) => setModel(e.target.value)}
                        >
                          <option>mistral:latest</option>
                          <option>llama3.1:latest</option>
                        </select>
                      </label>
                    </>
                  ) : (
                    <label>
                      Saved capability
                      <select
                        value={capId}
                        onChange={(e) => setCapId(e.target.value)}
                      >
                        {catalog.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.id === "example"
                              ? "Original example"
                              : `${c.capability.recording_actor === "automated_demo" ? "Automated demonstration" : c.capability.source === "human" ? "Human recording" : "Discovered"} ${c.id.slice(0, 8)}`}{" "}
                            · {c.capability.name} v{c.capability.version}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="divider" />
                  {mode !== "recording" && (
                    <>
                      <h3>Workflow inputs</h3>
                      {Object.entries(inputSchema).map(([key, parameter]) => (
                        <label key={key}>
                          {key.replaceAll("_", " ")}
                          <input
                            aria-label={`Input ${key}`}
                            required
                            maxLength={300}
                            pattern={parameter.pattern || undefined}
                            value={inputs[key] || ""}
                            onChange={(e) =>
                              setInputs({ ...inputs, [key]: e.target.value })
                            }
                          />
                          {parameter.sensitive && (
                            <small>Redacted in saved evidence</small>
                          )}
                        </label>
                      ))}
                    </>
                  )}
                  <label>
                    Runtime scenario
                    <select
                      value={scenario}
                      onChange={(e) => setScenario(e.target.value)}
                    >
                      <option value="normal">Normal operation</option>
                      <option value="transient">
                        Transient search failure · recover
                      </option>
                      <option value="uncertain-save">
                        Interrupted save response · reconcile
                      </option>
                      <option value="session-expired">
                        Expired session · human handoff
                      </option>
                      <option value="permission-denied">
                        Permission denied · stop
                      </option>
                      <option value="slow">Slow response · wait</option>
                    </select>
                  </label>
                  {mode !== "recording" && (
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={approved}
                        onChange={(e) => setApproved(e.target.checked)}
                      />
                      <span>
                        <strong>
                          Authorize changes for this synthetic run
                        </strong>
                        <small>
                          Leave unchecked to approve changes yourself in the
                          live session.
                        </small>
                      </span>
                    </label>
                  )}
                  <button
                    className="button primary"
                    type="submit"
                    disabled={
                      !online ||
                      !!active ||
                      !health?.bank ||
                      (mode === "replay" &&
                        !catalog.some((c) => c.id === capId)) ||
                      (mode === "discovery" && !health?.models?.includes(model))
                    }
                  >
                    <Play size={16} />
                    {busy
                      ? "Starting…"
                      : mode === "discovery"
                        ? "Start discovery"
                        : mode === "recording"
                          ? "Start recording"
                          : "Start replay"}
                  </button>
                  {active && (
                    <p className="callout">
                      A run is already active. Complete or cancel it in Live
                      session.
                    </p>
                  )}
                </fieldset>
              </form>
              <aside className="form-aside">
                <section className="panel">
                  <span className="square-icon">
                    <ShieldCheck />
                  </span>
                  <h3>Execution boundaries</h3>
                  <ul className="check-list">
                    <li>
                      <Check />
                      Real browser interaction
                    </li>
                    <li>
                      <Check />
                      Configured domain and route allowlist
                    </li>
                    <li>
                      <Check />
                      One active browser session
                    </li>
                    <li>
                      <Check />
                      Sensitive values redacted in logs
                    </li>
                    <li>
                      <Check />
                      Success checked against your inputs
                    </li>
                  </ul>
                </section>
                <div className="info-note">
                  <h4>What happens next?</h4>
                  <p>
                    Starting a run opens its browser view. Discovery calls your
                    local model for each decision. Replay executes the selected
                    capability directly.
                  </p>
                  <p>
                    If approval or session recovery is needed, the engine pauses
                    and transfers control to you.
                  </p>
                </div>
              </aside>
            </div>
          )}
          {page === "Capabilities" && (
            <div className="cap-library">
              {catalog.length === 0 && (
                <section className="panel capability-detail">
                  <h2>No saved workflows yet</h2>
                  <p>
                    Open New workflow to record a demonstration or start LLM
                    discovery. Verified workflows appear here after they are
                    published.
                  </p>
                </section>
              )}
              {catalog.map((item) => (
                <section className="panel capability-detail" key={item.id}>
                  <div className="cap-title">
                    <span className="square-icon">
                      <Box />
                    </span>
                    <div>
                      <h2>{item.capability.name.replaceAll("_", " ")}</h2>
                      <p className="mono">
                        {item.id === "example"
                          ? "Original example"
                          : `${item.capability.recording_actor === "automated_demo" ? "Automated demonstration" : item.capability.source === "human" ? "Human recording" : "LLM discovery"} ${item.id.slice(0, 8)}`}
                      </p>
                    </div>
                    <Badge tone="green">v{item.capability.version}</Badge>
                  </div>
                  <p>{item.capability.description}</p>
                  <div className="cap-facts">
                    <div>
                      <small>ACTIONS</small>
                      <strong>{item.capability.steps.length}</strong>
                    </div>
                    <div>
                      <small>TYPED INPUTS</small>
                      <strong>
                        {Object.keys(item.capability.inputs).length}
                      </strong>
                    </div>
                    <div>
                      <small>APPLICATION</small>
                      <strong>{item.capability.app}</strong>
                    </div>
                  </div>
                  <div className="cap-actions">
                    <button
                      className="button primary"
                      disabled={viewer}
                      onClick={() => prepareReplay(item.id)}
                    >
                      <Play size={15} />
                      Replay with new inputs
                    </button>
                    <button
                      className="button secondary"
                      onClick={() => setInspect(item)}
                    >
                      <Code2 size={15} />
                      Inspect
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        download(`${item.id}.json`, item.capability)
                      }
                    >
                      <ArrowDownToLine size={15} />
                      Download
                    </button>
                  </div>
                </section>
              ))}
            </div>
          )}
          {page === "Run history" && (
            <>
              <div className="filters">
                <Badge>{runs.length} live runs</Badge>
                <label className="search-box">
                  <Search size={16} />
                  <input
                    aria-label="Search live runs"
                    placeholder="Search ID, mode, or outcome…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <button
                  className="text-button"
                  onClick={() => setShowArchive(true)}
                >
                  Archived evidence
                </button>
              </div>
              <section className="panel">
                <RunTable
                  visibleRuns={visibleRuns}
                  runs={runs}
                  viewer={viewer}
                  onLive={(id) => {
                    setSelected(id);
                    setPage("Live session");
                  }}
                  onDetail={setDetail}
                  onNew={() => navigate("New workflow")}
                />
              </section>
            </>
          )}
          {page === "Live session" && (
            <>
              {current ? (
                <>
                  <div className="live-toolbar">
                    <select
                      aria-label="Select run"
                      value={current.id}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      {runs.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.id.slice(0, 8)} · {r.mode} · {status(r)}
                        </option>
                      ))}
                    </select>
                    <Badge
                      tone={
                        canControl
                          ? "amber"
                          : current.status === "success"
                            ? "green"
                            : "neutral"
                      }
                    >
                      {status(current)}
                    </Badge>
                    <span>Control: {current.live?.owner || "none"}</span>
                    {current.status === "running" &&
                      current.live?.owner === "automation" &&
                      !viewer && (
                        <button
                          className="button secondary"
                          disabled={current.live?.takeover_requested}
                          onClick={() => command({ kind: "request_control" })}
                        >
                          {current.live?.takeover_requested
                            ? "Control requested…"
                            : "Request control"}
                        </button>
                      )}
                    {current.status === "running" && !viewer && (
                      <button
                        className="button secondary"
                        onClick={() => command({ kind: "abort" })}
                      >
                        <StopCircle size={15} />
                        Cancel run
                      </button>
                    )}
                  </div>
                  <div className="live-layout">
                    <section className="panel browser-panel">
                      <div className="browser-chrome">
                        <span />
                        <span />
                        <span />
                        <div>
                          <Monitor size={13} />
                          Cedar Bank · same browser session
                        </div>
                      </div>
                      {current.live?.has_frame && !imageError ? (
                        <img
                          className={`live-screen ${canControl ? "controllable" : ""}`}
                          src={`/api/runs/${current.id}/frame?t=${frameTick}`}
                          alt="Current automation browser"
                          onError={() => setImageError(true)}
                          onClick={(e) => {
                            if (!canControl) return;
                            const r = e.currentTarget.getBoundingClientRect();
                            void command({
                              kind: "click",
                              x:
                                ((e.clientX - r.left) *
                                  e.currentTarget.naturalWidth) /
                                r.width,
                              y:
                                ((e.clientY - r.top) *
                                  e.currentTarget.naturalHeight) /
                                r.height,
                            });
                          }}
                        />
                      ) : (
                        <div className="empty-session">
                          <Monitor size={40} />
                          <h2>
                            {current.status === "running"
                              ? "Opening browser…"
                              : "Browser session closed"}
                          </h2>
                          <p>{current.code}</p>
                        </div>
                      )}
                      {current.status !== "running" && (
                        <div className="last-frame">
                          Last frame from the completed session. This browser is
                          no longer controllable.
                        </div>
                      )}
                    </section>
                    <aside>
                      <section className="panel session-info">
                        <h3>
                          {canControl
                            ? current.mode === "recording"
                              ? "You are recording"
                              : "Your review is needed"
                            : "Execution details"}
                        </h3>
                        {current.live?.intervention ? (
                          <>
                            <p className="callout">
                              {current.live.intervention.reason}
                            </p>
                            <p>
                              Click inside the browser image to operate the same
                              session. Complete the requested step, then resume.
                            </p>
                            <p className="muted">
                              Expected checkpoint:{" "}
                              {JSON.stringify(
                                current.live.intervention.expected,
                              )}
                            </p>
                          </>
                        ) : (
                          <p>
                            {current.status === "running"
                              ? current.mode === "recording"
                                ? "Demonstrate the workflow using the image and parameter controls below."
                                : "The engine owns this browser. Request control to pause at the next safe action boundary."
                              : "The run has finished. Inspect its outputs and evidence below."}
                          </p>
                        )}
                        <dl>
                          <dt>Mode</dt>
                          <dd>{current.mode}</dd>
                          <dt>Actions / model decisions</dt>
                          <dd>
                            {current.actions} / {current.model_decisions}
                          </dd>
                          <dt>Session ID</dt>
                          <dd className="mono">
                            {current.live?.session_id ||
                              current.run_id ||
                              "Starting"}
                          </dd>
                        </dl>
                        {canControl && current.mode === "recording" && (
                          <RecordingTools
                            key={current.id}
                            run={current}
                            command={command}
                          />
                        )}
                        {canControl && current.mode !== "recording" && (
                          <div className="operator-tools">
                            <label>
                              Text for focused field
                              <input
                                aria-label="Text for focused field"
                                type="password"
                                value={typing}
                                onChange={(e) => setTyping(e.target.value)}
                              />
                            </label>
                            <button
                              className="button secondary"
                              onClick={() => {
                                void command({ kind: "type", text: typing });
                                setTyping("");
                              }}
                            >
                              Type text
                            </button>
                            <div className="key-buttons">
                              {["Tab", "Enter", "Escape", "Backspace"].map(
                                (key) => (
                                  <button
                                    className="button secondary"
                                    key={key}
                                    onClick={() =>
                                      command({ kind: "key", key })
                                    }
                                  >
                                    {key}
                                  </button>
                                ),
                              )}
                              <button
                                className="button secondary"
                                onClick={() =>
                                  command({ kind: "scroll", delta: 500 })
                                }
                              >
                                Scroll down
                              </button>
                              <button
                                className="button secondary"
                                onClick={() =>
                                  command({ kind: "scroll", delta: -500 })
                                }
                              >
                                Scroll up
                              </button>
                            </div>
                            <button
                              className="button primary"
                              onClick={() => command({ kind: "resume" })}
                            >
                              <Play size={15} />
                              Resume automation
                            </button>
                          </div>
                        )}
                      </section>
                    </aside>
                  </div>
                  <RecordingDocument
                    run={current}
                    viewer={viewer}
                    publish={async () => {
                      try {
                        await request(
                          `/runs/${current.id}/publish`,
                          { method: "POST" },
                          csrf,
                        );
                        await refresh();
                      } catch (e) {
                        setError((e as Error).message);
                      }
                    }}
                  />
                  <section className="panel event-panel">
                    <div className="section-heading">
                      <h2>Live event log</h2>
                      <button
                        className="text-button"
                        onClick={() => setDetail(current)}
                      >
                        Inspect result <ArrowUpRight size={15} />
                      </button>
                    </div>
                    {current.result && (
                      <div className={`result-banner ${current.status}`}>
                        <strong>
                          {status(current)} · {current.code}
                        </strong>
                        <pre>
                          {JSON.stringify(current.result.outputs, null, 2)}
                        </pre>
                        {current.status === "success" &&
                          (current.mode === "discovery" ||
                            (current.mode === "recording" &&
                              current.capability_id === current.id)) && (
                            <button
                              className="button primary"
                              onClick={() =>
                                prepareReplay(current.capability_id)
                              }
                            >
                              Replay this new capability{" "}
                              <ArrowRight size={15} />
                            </button>
                          )}
                      </div>
                    )}
                    <ol className="live-events">
                      {current.events
                        .slice(-25)
                        .reverse()
                        .map((event, index) => (
                          <li key={`${event.time}-${index}`}>
                            <time>
                              {new Date(event.time).toLocaleTimeString()}
                            </time>
                            <Badge>{event.event}</Badge>
                            <code>{JSON.stringify(event).slice(0, 500)}</code>
                          </li>
                        ))}
                    </ol>
                  </section>
                </>
              ) : (
                <section className="panel empty-session">
                  <Monitor size={42} />
                  <h2>No run started yet</h2>
                  <p>
                    Start discovery or replay to open a real browser session.
                  </p>
                  <button
                    className="button primary"
                    onClick={() => navigate("New workflow")}
                  >
                    Create workflow
                  </button>
                </section>
              )}
            </>
          )}
          {page === "Banking app" && (
            <section className="panel bank-launch">
              <div className="bank-logo">C</div>
              <p className="eyebrow">SYNTHETIC BANKING SANDBOX</p>
              <h2>Cedar Bank customer workspace</h2>
              <p>
                A real database-backed application with customers, checking and
                savings accounts, balance inquiries, debit-card controls,
                transaction history, and address servicing. The automation
                engine operates its visible UI, not its database.
              </p>
              <a
                className="button primary"
                href={health?.bank_url || "http://127.0.0.1:8000"}
                target="_blank"
                rel="noreferrer"
              >
                Open Cedar Bank <ExternalLink size={16} />
              </a>
              <div className="callout">
                <h3>Browse the live customer directory</h3>
                <p>
                  Open Cedar Bank to see the current customer count and database
                  records. The directory shows 20 customers per page. Use Next
                  page to browse, or search by Customer ID to find a record
                  directly.
                </p>
                <p>
                  Synthetic member IDs include C-1000 through C-1999. For
                  example, search for C-1500 to try a member from the expanded
                  dataset.
                </p>
                <a
                  className="button secondary"
                  href={health?.bank_url || "http://127.0.0.1:8000"}
                  target="_blank"
                  rel="noreferrer"
                >
                  Browse customer directory <ExternalLink size={16} />
                </a>
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>
              <ShieldCheck size={14} />
              Synthetic local data · Real execution
            </span>
            <span>Agent UI Execution Engine · v0.2</span>
          </footer>
        </main>
      </div>
      {profileDialog && (
        <Dialog
          title="Choose a demo session"
          close={() => setProfileDialog(false)}
        >
          <p className="muted">
            These local demo identities illustrate operator/viewer access. This
            is not production authentication. The API enforces the selected
            role.
          </p>
          <div className="profile-list">
            {people.map((p) => (
              <button key={p.id} onClick={() => choose(p)}>
                <span className="avatar">{p.initials}</span>
                <strong>{p.name}</strong>
                <Badge>{p.role}</Badge>
              </button>
            ))}
          </div>
        </Dialog>
      )}
      {detail && (
        <Dialog title="Run result and evidence" close={() => setDetail(null)}>
          <Badge>{status(detail)}</Badge>
          <p className="mono muted">{detail.id}</p>
          <p>{detail.code}</p>
          <pre>
            {JSON.stringify(
              detail.result || { status: detail.status },
              null,
              2,
            )}
          </pre>
          <button
            className="button secondary"
            onClick={() => download(`run-${detail.id}.json`, detail)}
          >
            <ArrowDownToLine size={16} />
            Download evidence
          </button>
          <details>
            <summary>All recorded events</summary>
            <pre className="event-log">
              {JSON.stringify(detail.events, null, 2)}
            </pre>
          </details>
        </Dialog>
      )}
      {inspect && (
        <Dialog title="Capability contract" close={() => setInspect(null)}>
          <p>{inspect.capability.description}</p>
          <ol className="action-list">
            {inspect.capability.steps.map((step, i) => (
              <li key={i}>
                <span>{i + 1}</span>
                <strong>
                  {step.kind} · {step.target.name}
                </strong>
                <small>{step.input_key || step.output_key}</small>
              </li>
            ))}
          </ol>
          <details>
            <summary>Full typed contract</summary>
            <pre>{JSON.stringify(inspect.capability, null, 2)}</pre>
          </details>
        </Dialog>
      )}
      {showArchive && (
        <Dialog
          title="Archived verification evidence"
          close={() => setShowArchive(false)}
        >
          <p className="muted">
            Original runs against the earlier standalone demo. These are
            historical records, not current activity.
          </p>
          {archive.runs.map((r) => (
            <section className="archive-run" key={r.run_id}>
              <h3>{r.name}</h3>
              <p>
                {r.status} · {r.actions} actions · {r.model_decisions} model
                decisions
              </p>
              <button
                className="text-button"
                onClick={() => download(`${r.name}.json`, r)}
              >
                Download original evidence
              </button>
            </section>
          ))}
        </Dialog>
      )}
    </div>
  );
}
