# Run evidence

These are genuine application runs against the standalone SQLite demo, copied from the engine's run directories after checking redaction. They are not PostgreSQL-container verification or scripted test fixtures.

- `discovery/`: successful Mistral/Ollama discovery, 14 model-selected actions, saved capability, and verified result.
- `replay/`: the saved capability replayed for a different customer and address, with 14 actions and no model-decision events.
- `replay-not-found/`: the same capability returned a structured business outcome for a nonexistent customer; includes a sanitized structural DOM snapshot.
- `manifest.json`: actual run IDs, statuses, and event counts derived from the logs.

The checked-in reusable capability is also at `capabilities/update-address.v1.json` in the repository root. Earlier failed discovery attempts remain in ignored local development runs. No test fixture is presented as model discovery.

Actual human takeover/resume evidence is pending. The first headed handoff was aborted because its browser was not visible on the user's desktop. A loopback operator view has been added, but that run has not yet been demonstrated with a human.

Model observations and persisted outputs omit sensitive address values. Source configuration contains explicitly synthetic example inputs so the commands are reproducible. No credentials or session state are included here.
# Connected Cedar Bank verification

`e2e/manifest.json` indexes the latest genuine runs. A React dashboard action launched local Ollama discovery through FastAPI against the Cedar Bank UI: 14 model decisions, 14 actions, verified success, and a saved capability. The dashboard then replayed that artifact for another customer/address with 14 actions and zero model decisions. A fresh banking browser session confirmed persistence.

The same API/capability also completed transient recovery and uncertain-save reconciliation, returned a missing-customer business outcome, and stopped on permission denial. Their sanitized logs and failure DOM evidence are in `e2e/`. These runs used standalone SQLite; they do not establish Docker/PostgreSQL verification.

The full-stack tests exercise the real live-session control queue and verify ownership transfer, a scripted operator save, same-session resume, and final success. Scripted operator input is **not** claimed as a genuine human demonstration. The live dashboard supports a person doing the same steps; a person-operated evidence recording remains outstanding.
