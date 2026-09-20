# Local-model catalog matching

These checks called the installed local Ollama `mistral:latest` model against an address capability fixture and balance/freeze capabilities produced by scripted browser-recording tests. They are genuine catalog-model calls, not evidence of LLM UI discovery or a person recording workflows.

`initial-failed-check.json` preserves the first failure: the model suggested related tasks for an unsupported mortgage request. The revised contract requires one capability accomplishing the entire task, or an explicit `NO_MATCH`.

`opposite-effect-failed-check.json` preserves a second failure: the model selected freeze for unfreeze. A deterministic guard now rejects known opposite effects based on the request and capability's success heading. It never selects a capability or executes steps. This is a narrow guard, not proof of universal semantic correctness.

`local-model-results.json` contains the final checks, including that guard. User selection, input review, and explicit run authorization remain necessary. The active user catalog is not populated with these test fixtures.
