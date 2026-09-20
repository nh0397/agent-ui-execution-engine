# Architecture

Agent UI Execution Engine separates goal-driven discovery from repeatable execution. A Python CLI accepts a goal, application entry point, typed workflow contract, input values, and an application policy profile. Playwright operates a local customer-service UI; the engine never reads its database or calls task endpoints directly to complete a workflow. The demo uses server-rendered forms so the work remains visible and easy to inspect. Docker Compose provides PostgreSQL and the app, with idempotent synthetic seeding; SQLite remains available for isolated tests and standalone use.

Discovery calls a local Ollama model on each step. The adapter observes current controls, and the engine enumerates legal operations on those controls. The model selects an action by its full description. Native form patterns filter invalid input bindings; output patterns and equality constraints filter impossible output bindings using values inspected locally, never sent to the model. These checks constrain actions without supplying a workflow sequence. Filling a field twice in the same document is disallowed during discovery to prevent repeated overwrites; this is a deliberate initial constraint. New documents expose new affordances. Verified completion is determined by code rather than the model's claim.

Once the success checkpoint appears, discovery permits only output extraction, preventing further navigation or writes after the requested change. The replay module does not import the discovery module or its model client. Both runners share action execution, policy checks, outcome detection, and evidence. Ordinary modules and versioned files are sufficient for this initial system; queues and distributed services would add complexity without improving the demonstrated flow.

The React dashboard calls a FastAPI execution API. A single-flight worker keeps each browser on its owning thread; HTTP handlers only enqueue operator commands. Polling exposes sanitized events and in-memory browser frames. Jobs, capabilities, and redacted results persist locally; unfinished jobs fail on restart. Three demo identities illustrate backend-enforced operator/viewer roles but are not production authentication. Archived evidence is separate from newly launched runs.

# Artifact schema

Pydantic rejects unknown fields and validates actions, targets, parameter declarations, results, and capabilities. Each capability has a schema version, capability version, application/version identity, typed string parameters, ordered actions, extraction bindings, a success target, and its originating discovery run ID. Field types are deliberately limited to strings in the initial contract; richer types would require a new supported schema extension.

Fill actions reference input keys instead of storing example values. Read actions reference declared output keys. Outputs may have patterns and equality constraints against inputs. The address workflow verifies customer ID and every saved address field, then returns a confirmation reference. This catches a successful-looking screen for an incorrect update. Semantic labels and role/name targets replace transient browser handles. Files are written exclusively, preventing accidental overwrites.

Runtime business conditions and recovery actions live in a separate reviewed application profile. They are authored rules, not knowledge inferred from a single successful recording. A production evolution should bind compatible profile versions or hashes to capability versions and require review of changes.

# Determinism & error handling

Replay validates inputs, resolves exact targets, requires a unique visible match, executes ordered actions, checks application compatibility and terminal success, and validates extracted outputs. Fixed waits and bounded recovery determine behavior; the model does not choose branches. Determinism does not imply that changing application state always produces identical results.

Results distinguish success, expected business outcomes, and hard failure. Recovery is logged as an intermediate condition. Missing records and validation rejection are legitimate outcomes. A known transient load failure has a fixed retry action. An uncertain save follows a visible reconciliation link instead of blindly repeating the write. The demo additionally uses idempotency tokens and optimistic concurrency; the engine must still reconcile because third-party applications may not supply those guarantees. Permission denial stops execution. Session expiry requests intervention.

Tests include server-level persistence checks and real-browser replay using explicitly labeled scripted fixtures. Such fixtures verify the executor, not LLM discovery. Failed live model attempts are preserved as failures. Genuine successful discovery and replay must be evidenced separately before the project is considered complete.

# Heterogeneity & multi-tenant

Observation and UI action execution are concentrated in the browser adapter. The initial implementation depends on usable labels, roles, and visible text. It does not claim to operate arbitrary legacy interfaces. Frames, nested table context, visual targeting, and OS accessibility require richer target variants and corresponding adapter implementations. The current browser metadata compatibility check would become an adapter-specific application fingerprint on a legacy surface.

Tenant origin and policy remain external to recorded actions. A future base capability would identify the vendor application and supported versions, with narrowly scoped tenant overrides for targets and routes. Compatibility checks and preconditions would reject unknown variants before writes. Overrides should be reviewed and versioned rather than silently learned during replay. No tenant management infrastructure or desktop implementation is included.

# Escalation & handoff

The session controller records an intervention request containing the current goal/capability context, step, reason, expected checkpoint, and sanitized observation. It stops dispatching automation actions and changes ownership to human while preserving the same browser context and session ID. The operator can use a visible browser and terminal signals, or a loopback operator page showing live frames from that same browser. HTTP handlers enqueue operator commands; the original Playwright thread executes them. Playwright continues pumping events so supported human clicks, field changes, and navigation are recorded. Sensitive values are omitted.

Resume validates the requested checkpoint and policy before returning ownership. A risky save without prior invocation approval is performed by the operator, followed by confirmation verification. The dashboard shows the same browser image and forwards clicks, typing, keys, and scrolling through the backend queue; commands are rejected while automation owns the session. The terminal/loopback page remain CLI options. Runs without any handoff channel fail clearly. Full-stack scripted operator tests verify the mechanism but do not establish genuine human participation. Native-browser/OS interactions are not fully recorded.

# Safety

Policy restricts origins, route patterns, action types, and state-changing requests. Risky POST routes have an additional authorization check independent of the model's target description. Discovery cannot grant itself permission. UI content is untrusted data. Unexpected browser dialogs are dismissed and execution stops rather than choosing a potentially destructive confirmation.

Known sensitive inputs are redacted recursively before persistence or model transmission. The browser observation excludes input values and hidden fields and masks explicitly sensitive nodes. Declared sensitive outputs are withheld from persisted results. Failure evidence includes a sanitized structural DOM snapshot. These controls depend on correct application annotations/configuration; they are not a universal PII detector. Full browser traces, credentials, and session state are not published. Demo session restoration is simulated access recovery, not production authentication.

# Cuts

The implementation focuses on one workflow and one browser surface. It includes a local capability catalog and execution API but omits public hosting, visual/desktop adapters, arbitrary JavaScript actions, sophisticated recovery planning, multi-tenant execution, and production authentication. Replay never uses an LLM fallback. Models can choose poor bindings despite valid JSON. Lexical field matching, native constraints, required-form completion, and independent output verification constrain this risk without prescribing action order. Labels without lexical overlap still require model interpretation.

Next priorities are stronger capability/profile compatibility, scope-aware targeting for frames and repeated controls, schema support for additional data types, improved malformed-model-response recovery, and broader privacy testing. Evidence and README status must accurately distinguish completed checks from pending live demonstrations.
