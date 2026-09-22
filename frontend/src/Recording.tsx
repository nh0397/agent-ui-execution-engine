import { useEffect, useState } from "react";
import { request, type Run } from "./api";

export function RecordingTools({
  run,
  command,
}: {
  run: Run;
  command: (v: Record<string, unknown>) => Promise<void>;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [key, setKey] = useState("customer_id");
  const [value, setValue] = useState("");
  const [heading, setHeading] = useState("");
  const [inputNames, setInputNames] = useState<Record<string, string>>({});
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  const data = run.recording;
  useEffect(() => {
    if (!data?.reviewing) return;
    setInputNames(
      Object.fromEntries(
        Object.keys(data.parameters || {}).map((key) => [key, key]),
      ),
    );
    setHeading(data.headings?.[0] || "");
    const bindings: Record<string, string> = {};
    for (const label of data.outputs || []) {
      const normalized = label
        .toLowerCase()
        .replace(/^(verified|saved|request) /, "")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_|_$/g, "");
      const key = /^[a-z]/.test(normalized)
        ? normalized
        : `output_${normalized}`;
      if (!Object.values(bindings).includes(key))
        bindings[label] = key.slice(0, 50);
    }
    setOutputs(bindings);
  }, [data?.reviewing]);
  return (
    <div className="operator-tools">
      <p>
        Use the bank directly. Editable fields open an inline text box when
        clicked. Values become reusable inputs automatically.
      </p>
      {data?.reviewing && (
        <div className="callout">
          <h4>Reusable inputs captured</h4>
          {Object.keys(data.parameters || {}).map((key) => (
            <label key={key}>
              Reusable name for {key}
              <input
                aria-label={`Reusable input name for ${key}`}
                value={inputNames[key] || ""}
                onChange={(e) =>
                  setInputNames({ ...inputNames, [key]: e.target.value })
                }
              />
            </label>
          ))}
          <p>
            {Object.keys(data.parameters || {}).join(", ") ||
              "No text inputs captured."}
          </p>
          <p>
            Review the success heading and returned fields below, then save the
            draft.
          </p>
        </div>
      )}
      <details onToggle={(e) => setAdvanced(e.currentTarget.open)}>
        <summary>Advanced field entry</summary>
        <p>
          Click a field in the live image, give it a parameter name, then enter
          an example value. Click the application's buttons to continue.
        </p>
        <label>
          Parameter name
          <input
            aria-label="Parameter name"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="customer_id"
          />
        </label>
        <label>
          Example value
          <input
            aria-label="Example value"
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <button
          className="button secondary"
          disabled={!value || !/^[a-z][a-z0-9_]{0,49}$/.test(key)}
          onClick={() => {
            void command({ kind: "type", parameter_key: key, text: value });
            setValue("");
          }}
        >
          Fill parameter
        </button>
        <div className="key-buttons">
          <button
            className="button secondary"
            onClick={() => command({ kind: "key", key: "Tab" })}
          >
            Tab
          </button>
          <button
            className="button secondary"
            onClick={() => command({ kind: "scroll", delta: 500 })}
          >
            Scroll down
          </button>
          <button
            className="button secondary"
            onClick={() => command({ kind: "scroll", delta: -500 })}
          >
            Scroll up
          </button>
        </div>
      </details>
      {data?.error && (
        <p role="alert" className="callout">
          {data.error}
        </p>
      )}
      <div hidden={!data?.reviewing && !advanced}>
        <h4>Finish at the verified result</h4>
        <label>
          Success heading
          <select
            aria-label="Success heading"
            value={heading}
            onChange={(e) => setHeading(e.target.value)}
          >
            <option value="">Choose the terminal heading</option>
            {data?.headings?.map((h) => (
              <option key={h}>{h}</option>
            ))}
          </select>
        </label>
        <p>
          Name the output fields to return. Reuse an input parameter name to
          verify that the saved value matches.
        </p>
        {data?.outputs?.map((label) => (
          <label key={label}>
            {label}
            <input
              aria-label={`Output key for ${label}`}
              placeholder="Output key (leave blank to skip)"
              value={outputs[label] || ""}
              onChange={(e) =>
                setOutputs({ ...outputs, [label]: e.target.value })
              }
            />
          </label>
        ))}
        <button
          className="button primary"
          disabled={!heading || !Object.values(outputs).some(Boolean)}
          onClick={() =>
            command({
              kind: "finish",
              success_name: heading,
              input_names: inputNames,
              output_bindings: Object.fromEntries(
                Object.entries(outputs).filter(([, v]) => v),
              ),
            })
          }
        >
          Finish and review recording
        </button>
      </div>
    </div>
  );
}

export function RecordingDocument({
  run,
  publish,
  viewer,
  csrf,
}: {
  csrf: string;
  run: Run;
  publish: () => Promise<void>;
  viewer: boolean;
}) {
  const [building, setBuilding] = useState(false);
  const [videoReady, setVideoReady] = useState(false);
  const [videoError, setVideoError] = useState("");
  async function buildVideo() {
    setBuilding(true);
    setVideoError("");
    try {
      await request(`/runs/${run.id}/video`, { method: "POST" }, csrf);
      setVideoReady(true);
    } catch (error) {
      setVideoError((error as Error).message);
    } finally {
      setBuilding(false);
    }
  }
  const steps = run.recording?.steps || [];
  if (!steps.length && !run.draft) return null;
  return (
    <section className="panel event-panel">
      <h2>Recorded steps and screenshots</h2>
      <h3>Watch this recording</h3>
      <p>
        A playable sequence of masked before/after frames. This is step
        playback, not continuous motion capture.
      </p>
      {run.has_video || videoReady ? (
        <video
          controls
          preload="metadata"
          style={{ width: "100%", maxHeight: 540 }}
          src={`/api/runs/${run.id}/video`}
          aria-label="Recorded workflow video"
        />
      ) : (
        <button
          className="button secondary"
          disabled={building || run.status === "running"}
          onClick={() => void buildVideo()}
        >
          {building ? "Preparing video…" : "Create playback video"}
        </button>
      )}
      {videoError && <p role="alert">{videoError}</p>}
      <p>
        Before and after each supported human gesture. Field values and marked
        sensitive regions are masked before saving.
      </p>
      <a className="button secondary" href={`/api/runs/${run.id}/document`}>
        Download workflow document and screenshots
      </a>
      {run.draft && (
        <div className="callout">
          <h3>Review before publishing</h3>
          <p>
            {run.draft.name} · {run.draft.steps.length} replay actions ·{" "}
            {run.draft.recording_actor === "automated_demo"
              ? "Automated demonstration"
              : "Human recording"}
          </p>
          <p>Inputs: {Object.keys(run.draft.inputs).join(", ")}</p>
          <p>Outputs: {Object.keys(run.draft.outputs).join(", ")}</p>
          <details>
            <summary>Review the complete capability</summary>
            <pre>{JSON.stringify(run.draft, null, 2)}</pre>
          </details>
          <button
            className="button primary"
            disabled={viewer || run.capability_id === run.id}
            onClick={publish}
          >
            {run.capability_id === run.id
              ? "Published to capabilities"
              : "Publish reviewed workflow"}
          </button>
        </div>
      )}
      <div className="recording-gallery">
        {steps.map((step) => (
          <details key={step.number}>
            <summary>
              Step {step.number}:{" "}
              {step.action
                ? `${step.action.kind} ${step.action.target.name}`
                : step.kind}
              {step.action?.input_key
                ? ` · parameter ${step.action.input_key}`
                : ""}
            </summary>
            <div className="capture-pair">
              {(["before", "after"] as const).map((phase) => (
                <figure key={phase}>
                  <img
                    loading="lazy"
                    src={`/api/runs/${run.id}/captures/${step[phase]}`}
                    alt={`Step ${step.number} ${phase}, redacted`}
                  />
                  <figcaption>{phase}</figcaption>
                </figure>
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}
