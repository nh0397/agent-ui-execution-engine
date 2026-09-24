# LangSmith verification

I ran a new address discovery against an isolated SQLite bank, then replayed the learned capability with different inputs. A second replay exercised permission denial. These are actual browser runs, not model test doubles.

| Run | Result | Model calls | Exported spans |
| --- | --- | --- | --- |
| Discovery | Success | 14 | 30 |
| Replay with new inputs | Success | 0 | 16 |
| Replay with permission denied | Failure as expected | 0 | 5 |

The [manifest](manifest.json) contains the run and trace IDs, model token counts, and privacy-check results. The [trace records](traces.json) were retrieved from LangSmith after export. They omit account and project metadata. The three folders contain the local events and results; `discovery/capability.json` is the learned workflow.

Model HTTP transport was blocked during both replays. The trace contents were checked for both synthetic input sets and the configured API keys. None appeared. Local evidence uses the engine's existing redaction rules.

The first read immediately after discovery did not confirm the uploaded trace. A later read found it. The exporter now allows bounded background waits for that delay and reports an unconfirmed state if it still cannot read the trace. No extra discovery was needed.

These traces do not establish actual human participation. Takeover tracing is covered by separately labeled scripted browser tests. A successful person-operated takeover is still missing from the public evidence.
