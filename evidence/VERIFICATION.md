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
