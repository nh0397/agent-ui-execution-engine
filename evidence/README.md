# Evidence index

Start with **[groq-e2e/manifest.json](groq-e2e/manifest.json)** for the final Groq verification:

| Evidence | What it establishes |
| --- | --- |
| [Groq discovery](groq-e2e/discovery/events.jsonl) and [capability](groq-e2e/discovery/capability.json) | Genuine runtime model choices through Cedar Bank: 15 actions and independently verified success. |
| [New-input replay](groq-e2e/replay/result.json) | Same capability, different inputs, checked outputs, zero model decisions; model HTTP transport was blocked. |
| [Not found](groq-e2e/not-found/result.json) | Expected business outcome, with sanitized structural evidence. |
| [Transient recovery](groq-e2e/transient/events.jsonl) | One bounded recovery action, then verified success. |
| [Uncertain save](groq-e2e/uncertain-save/events.jsonl) | Reconciled visible result without blindly resubmitting. |
| [Permission denial](groq-e2e/permission-denied/result.json) | Safe stop with failure snapshot. |
| [Slow loading](groq-e2e/slow/result.json) | Bounded browser waits completed successfully. |
| [Docker/PostgreSQL replay](groq-e2e/docker-replay/result.json) | The exact CLI replay command completed 15 actions against the container bank. |
| [Dashboard API replay](groq-e2e/dashboard-replay/result.json) | Newly learned capability completed for C-306, with zero additional model calls; visible in local Past runs. |
| [Expired handoff](groq-e2e/handoff-expired/result.json) | A real paused session expired safely without person input. This is not a successful human demonstration. |
| [Catalog chat](groq-e2e/catalog-chat.json) | Genuine Groq matching and exact input extraction through FastAPI; no bank action. |
| [LangSmith verification](langsmith/manifest.json) and [trace records](langsmith/traces.json) | A fresh genuine Groq discovery used 14 model calls. New-input replay and permission denial used zero with model transport blocked. All three traces were uploaded and read back, with input values and keys absent. |
| [Readable run explanations](readable-traces/README.md) and [trace records](readable-traces/traces.json) | A further genuine Groq discovery used 14 calls. Success, access denial, and temporary-error recovery replays used zero. Read-back checks verified named controls, selected model actions, and the specific failure explanation without customer values or keys. |
| [Failed discovery attempts](groq-e2e/failed-attempts/) | Six genuine failures encountered during the audit: targeting, model dead ends, provider rate limiting and timeouts. Changes were made between attempts; this is not a measured reliability sample. |

The manifest links actual run IDs and the capability hash. Groq runs used the local SQLite bank. Existing **e2e/** and **docker-e2e/** contain genuine earlier Ollama discovery and paired replays; docker-e2e used PostgreSQL. Other scripted recorder/operator evidence is explicitly labeled. It is never a substitute for model discovery or actual human participation.

A person-operated final takeover/resume demonstration remains pending until recorded and verified. The same-session mechanism is exercised by automated tests. See [verification notes](VERIFICATION.md).

Published run evidence redacts configured sensitive values. Only synthetic example inputs are checked into config/. Private API keys, conversation databases, browser session state and raw live images are excluded.
