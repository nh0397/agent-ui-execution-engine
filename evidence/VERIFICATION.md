# Verification on 2026-09-20

- Local full suite: 36 passed, two dependency deprecation warnings. Then the browser suite was rerun after adding model-transport denial and session restoration: 11 passed (37 total collected tests across the final test files).
- Production React/TypeScript build succeeded inside Docker, using npm ci and npm run build.
- New browser checks cover dead-end escalation without capability publication, unexpected dialog rejection, textarea/annotated-node privacy canaries, and session restoration with unchanged session identity.
- All operator actions in these automated checks are scripted. A person-operated demonstration is not claimed.
- Existing genuine Ollama runs remain in e2e/. Fresh Docker discovery and paired replay are in docker-e2e/, including the newly generated capability. Discovery used 14 model decisions; replay used zero with different inputs. docker-replay/ additionally verifies the original checked-in capability.
- Docker PostgreSQL replay completed 14 actions with zero model decisions. A separate bank session confirmed the saved address. Dashboard, worker, bank, and database health checks passed; the worker can reach local Ollama.
- The published bank/dashboard services join an access network because internal-only networking prevented localhost port access. The database stays on the internal network with no published port. The browser uses cedar.test internally to avoid Chromium HTTPS upgrading the bare app hostname.

Limits: no desktop adapter, production authentication, tenant isolation, or visual-only discovery. Structured observations rely on labels and configured sensitive nodes. Arbitrary human recovery during discovery does not publish incomplete capabilities.

## Human recording extension

Final regression: 42 tests passed, with two dependency deprecation warnings. TypeScript validation and the production Vite build passed. A full-stack browser test recorded a parameterized workflow, downloaded 26 masked screenshots plus documentation, reviewed/published the draft, and replayed different inputs with zero model decisions. API tests verify automation rejects click/type commands, accepts a control request, and requires an operator to publish drafts. The scripted recorder example is in human-recorder-scripted-test/; no real-person demonstration is claimed.

## Three services, larger dataset, and catalog matching

- Full suite: 53 tests passed on 2026-09-20 after adding balance/card recording and replay, card CSRF/idempotency/concurrency checks, seed preservation/pagination, and agent UI routing checks. After adding the opposite-effect guard, its targeted suite passed all 5 tests (including one additional test).
- SQLite counts verified: 1,003 customers, 1,004 accounts, 1,003 cards, 4,004 transactions.
- Frontend TypeScript check and production build passed. Live browser checks verified the three-service bank homepage and empty-catalog agent response.
- Genuine local-model catalog checks and the two failures encountered during development are preserved in catalog-matching/. These are distinct from LLM browser discovery evidence.
- Current local dashboard: port 5176; bank: port 8003. Docker socket access was denied, so PostgreSQL execution of these additions was not verified in this turn.

## Integrated conversation and visible demonstration history

- Full suite: 54 passed after integrating the chatbot with the main workspace and adding explicit automated-recording provenance.
- Real browser authoring generated three verified capabilities and three successful new-input replays in the active local workspace. The recordings contain 5, 13, and 6 supported gestures, respectively, with 48 masked before/after screenshots in total.
- Run history and its downloadable documents were verified through the live dashboard. See automated-demonstrations/summary.json for actual run IDs and statuses. These runs are automated demonstrations, not genuine human participation or LLM discovery.
- GitHub push remains blocked by local Git credential-helper access and GitHub integration write permission (403). Local commits must not be described as published.

## Existing-bank request intake (2026-09-21)

- Full regression: 64 tests passed; request tests passed again after stabilizing status-history ordering.
- Real Playwright UI check created statement request REQ-00B86C3A64FF for C-1002 / AC-10002, submitted the review, changed status to In review with a staff note, and located it through customer request history. No browser errors. This was a scripted UI verification, not human or LLM discovery evidence.
- New tests cover all three request types, linked-resource ownership, invalid CSRF, denied writes, duplicate submission, stale status updates, and persistence across restart. Verified locally with SQLite; this change was not exercised on PostgreSQL.

## Demonstration-first recording (2026-09-21)

- Added inline text entry with inferred input names, explicit Stop recording & review / Continue recording, and post-capture input renaming. Legacy explicit bindings remain an advanced option.
- Full-stack test covers correcting an entered value, stopping capture, renaming the inferred input, preserving its output equality check, publishing, and replaying another account. Persisted run JSON excludes the entered account value. This is scripted test evidence, not a person-operated handoff claim.
- Reduced recording overhead by capturing masked viewport images and logging scrolling without image capture. Each published state uses a current browser frame; the live screencast continues between steps. No latency guarantee is claimed.
- Validation: 57 non-dashboard tests passed in the full regression run; after fixing image-refresh coordinate mapping, all 8 dashboard tests passed. TypeScript checks and the production build passed. The inline test also exercises zero intrinsic image dimensions during frame replacement.

## Chat model recovery (2026-09-21)

- Reproduced Ollama HTTP 500 (model worker connection reset), previously misreported as a connection failure or timeout. Reduced chat context from 8192/4096 to 2048 tokens and limited idle model residency to one minute. This alleviated the observed failure; local memory pressure can still affect availability.
- Nineteen catalog/API/dashboard tests passed, including failure classification, private-error redaction, and manual recovery without execution. Type checking and the production frontend build passed after releasing an idle model from memory.
- Genuine local Mistral calls through the running API and Playwright-driven chat matched the saved Customer address change workflow for the user's synthetic C-1001 request. The UI extraction returned customer_id=C-1001 and street_address=Central Avenue. No banking workflow was executed. This verifies catalog chat, not a new LLM discovery run.
- The saved workflow has only customer ID and street address inputs. Its unchanged city/postal fields are not represented as newly parameterized values. Chat now exposes the accepted fields and allows corrections before run confirmation.

## Assistant-first landing page

- Overview opens directly into the conversation, with activity examples and input guidance. The idle browser placeholder is removed. The same assistant stays mounted and becomes a popup during live execution. Secondary workflow/history/service tools remain accessible.
- TypeScript and production build passed; all nine dashboard tests passed. Visually inspected 1440px desktop and 390px mobile renders, with no horizontal overflow on mobile.

## Conversational chat refinement

- TypeScript and production build passed; ten dashboard tests passed, including Enter versus Shift+Enter, draft reset/focus, and no implicit execution. Inspected desktop and mobile renders; no horizontal mobile overflow. This change affects presentation and chat interaction, not model discovery behavior.

## Full-page conversation and task story

- Replaced primary dashboard navigation and idle cards with full-page chat, anchored composer, and secondary Tools. The live browser and chat share the execution view; terminal outcomes are appended to the originating conversation. No-match replies offer discovery setup with the original goal or human recording.
- Production build and type checking passed. Ten dashboard tests passed; the additional no-match → discovery setup → return to chat → recording assertions also passed. Chat-driven replay verifies that the completion message appears in the conversation. Desktop and mobile layouts were visually inspected; mobile has no horizontal overflow.

## Workflow selection clarity

- Highlighted Tools, added explicit next-step selection guidance and supported fields, separated action buttons from metadata, and disabled stale suggestions. Type checking/build passed; ten dashboard tests passed. Desktop/mobile selection rendering inspected with an explicit mocked match response (not model evidence); mobile action verified clear of the composer.
- Submission readiness remains conditional on a person-operated takeover/resume demonstration and final clean-setup, documentation, and public-evidence review. Existing genuine discovery/replay evidence remains intact.

## Hosted provider, persistent conversations, and clean setup

- Installed the declared Python/test dependencies into a new virtual environment. Ran the complete suite there: **78 passed**, with two dependency deprecation warnings. Browser tests reused the installed Playwright Chromium binaries. TypeScript checking, the production Vite build, and PowerShell startup-script parsing passed.
- Added provider transport tests for server-only keys, usage accounting, rate-limit cooldown, application budget, and sanitized timeout errors. These Groq responses are **test doubles**, not hosted-model execution evidence. No Groq key or live Groq run was available.
- Conversation tests verify persistence across restart, profile ownership, revision conflicts, key scrubbing, and no implicit execution. The browser reload test restores reviewed fields but clears write approval.
- The live dashboard on port 5176 rendered the new history/status controls without JavaScript errors; a 390px mobile viewport had no horizontal overflow. Production backend restarted after confirming there were no active runs. No bank writes were performed by that presentation check.
- Repository review found no tracked private environment/database files or matching Groq/OpenAI secret-key patterns. This pattern check is a limited check, not a guarantee of universal secret detection. Private conversations and model accounting remain ignored.
- Existing genuine Ollama discovery/replay evidence remains unchanged. Person-operated takeover/resume remains an explicit pending demonstration. Current provider changes were verified locally, not by rebuilding the Docker deployment.

## Groq connection and pacing verification

- One genuine Groq JSON request succeeded using openai/gpt-oss-20b: 147 reported input tokens and 69 output tokens. This verifies connectivity/transport, not browser discovery. No bank action was performed.
- Seven provider/history tests passed, including a new rolling-minute guard test. TypeScript and production frontend build passed. App guards are 100 attempts per UTC day and 10 per rolling minute; monitoring reads local accounting without making model calls. Provider quotas remain shared and cannot be guaranteed by this application.

## Final PDF audit and Groq vertical slice

- Rechecked all ten original PDF pages. New evidence/groq-e2e contains a genuine successful 15-decision Groq discovery, six real new-capability replays with model transport blocked, and six failed discovery attempts encountered while fixing integration issues.
- Replays verified all requested output values locally. Published sensitive outputs remain redacted. Not-found is a business outcome; permission denial is a failure with structural snapshot; transient and uncertain-save cases each have one explicit recovery action; slow loading succeeds.
- Genuine live catalog chat selected groq-address-v1 and extracted all four supplied fields exactly in two model requests, without executing a bank task.
- Fixed normalized rendered link names, explicit current-document input-binding state, pre-request capacity waiting, and Windows UTF-8 artifact decoding. A submitted provider rejection still stops; pacing cannot retry a UI action. Browser action timeout is bounded at ten seconds.
- Full regression: 83 passed with two dependency deprecation warnings. After the encoding fix, 16 API/provider/CLI tests passed, including a new cp1252-host simulation (84 tests in the final collection). Earlier TypeScript/production build passed; final audit made no frontend changes.
- Docker Compose build/start completed with app, database, worker and dashboard healthy. The final worker rebuild includes the encoding fix. Public GitHub visibility checked. Local workspace is 5176/8003; Docker workspace is 5173/8000, with separate data stores.
- A person-operated takeover was prepared on the loopback operator page. Until actual save/resume events and verified success exist, it remains pending. Scripted handoff tests are not relabeled as human evidence.

Final live checks: CLI replay against Docker/PostgreSQL succeeded (15 actions). Dashboard API replay succeeded for C-306 with zero additional model requests. The prepared operator session expired with no person commands; the genuine person-operated acceptance check remains pending.

## Bordered chat and action visibility
- TypeScript checking and the production frontend build passed. All 11 dashboard regression tests passed.
- Live Playwright presentation checks at 1440px desktop and 390px mobile verified the bordered chat, visible workflow buttons, no horizontal overflow, and no page errors. The Discover a workflow button opened the existing goal configuration. These checks made no model calls or banking writes.

## README walkthrough verification
- Rewrote the README against startup scripts, configuration, contracts, and API routes. Captured and visually checked five actual app screenshots with synthetic data.
- Executed the README PowerShell session, catalog, model-status, replay-start, and polling blocks against isolated bank/API services on ports 8017/5187. The bundled address workflow completed successfully with 14 actions and zero model decisions. No provider requests were made. The temporary services were stopped afterward; the existing development workspace was untouched.
- Checked local Markdown links and screenshot paths. Docker startup instructions were checked against source, not rerun for this documentation change.

## Conversational discovery inputs
- Chat prepares supported address discovery after no saved match, extracts supplied values, collects missing fields in the conversation, and requires explicit confirmation. Manual setup remains available. No saved capability is invented during preparation.
- Twelve catalog/API tests passed. Thirteen dashboard tests passed, including full/partial requests, no execution before confirmation, draft restoration without write approval, and discovery dispatch with the reviewed values. Model and run dispatch doubles in these tests are not genuine discovery evidence.
- TypeScript and production build passed. A live Groq preparation check used two model requests, correctly extracted all four values from an address-change message, and started no browser run. No banking writes were performed by that check.

## Full-width chat
- Removed the desktop chat width cap and laid out reviewed input values as readable cards. Confirmation identifies new discovery separately from saved-workflow replay. An empty catalog is stated on the landing screen.
- TypeScript and production build passed. Live presentation checks measured 1872px chat width on a 1920px viewport and no horizontal overflow at 390px. Twelve dashboard tests passed on the first run; one browser crashed during fixture setup and passed when rerun alone. No model calls or banking changes were needed for these checks.
