# Readable run explanations

I ran a fresh Groq discovery against an isolated Cedar Bank database, then replayed its saved capability with different inputs. These are real browser runs and actual LangSmith records. Discovery used `openai/gpt-oss-20b` through Groq.

| Run | Result | Model calls | Trace steps |
| --- | --- | --- | --- |
| Discovery | Verified success, 14 UI actions | 14 | 45 |
| New-input replay | Verified success | 0 | 31 |
| Permission-denied replay | Stopped after opening the edit page | 0 | 10 |
| Temporary-error replay | Retried the search once, then verified success | 0 | 32 |

Model HTTP transport was blocked during every replay. The discovered capability, run events, results, and readable explanations are saved in the corresponding folders. [manifest.json](manifest.json) links the run IDs and trace IDs. [traces.json](traces.json) contains the records read back from LangSmith, with project and account fields excluded.

The trace checks verified the readable workflow name, the model's selected action, the specific access-denied error, and the successful recovery step. Both synthetic input sets and configured API keys were absent from the exported trace content. The discovery responses reported 18,441 input tokens and 2,863 output tokens. These are reported usage totals, not a billing calculation.

The first read-back request timed out after discovery succeeded. I retried reading the existing trace with a longer timeout. I did not repeat discovery or replace its evidence.

For the failure example, start with [permission-denied/explanation.json](permission-denied/explanation.json). Four browser actions completed. The next page check detected denied access. No protected write was attempted. The trace recommends checking the operator's permissions rather than retrying unchanged access.

The [README screenshot](../../docs/images/run-explanation.png) comes from an additional real replay through the execution API and React UI, using the bundled reference capability and a separate synthetic database. It is an app screenshot, not a LangSmith screenshot. Its job ID is `c95a7cd2-5570-4a80-a586-43e1bf70e030` and trace ID is `1c63df19-493d-41a6-97d8-63ff47d5e49b`.

The full test suite passed 132 tests. It includes readable failure summaries, recovery, privacy, older evidence, interrupted runs, failed model attempts, and scripted same-session human takeover. Scripted operator tests do not establish actual human participation. A successful person-operated takeover demonstration remains pending.

Descriptions come from reviewed application labels and fixed engine messages. Unknown labels, customer values, raw prompts, responses, and exception text are withheld. Step durations can overlap. Historical cloud traces remain unchanged. This evidence does not establish reliability across arbitrary applications or model choices.
