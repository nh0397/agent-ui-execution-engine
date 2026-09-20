# Verification on 2026-09-20

- Local full suite: 36 passed, two dependency deprecation warnings. Then the browser suite was rerun after adding model-transport denial and session restoration: 11 passed (37 total collected tests across the final test files).
- Production React/TypeScript build succeeded inside Docker, using npm ci and npm run build.
- New browser checks cover dead-end escalation without capability publication, unexpected dialog rejection, textarea/annotated-node privacy canaries, and session restoration with unchanged session identity.
- All operator actions in these automated checks are scripted. A person-operated demonstration is not claimed.
- Existing genuine Ollama runs remain in e2e/. Fresh Docker discovery and paired replay are in docker-e2e/, including the newly generated capability. Discovery used 14 model decisions; replay used zero with different inputs. docker-replay/ additionally verifies the original checked-in capability.
- Docker PostgreSQL replay completed 14 actions with zero model decisions. A separate bank session confirmed the saved address. Dashboard, worker, bank, and database health checks passed; the worker can reach local Ollama.
- The published bank/dashboard services join an access network because internal-only networking prevented localhost port access. The database stays on the internal network with no published port. The browser uses cedar.test internally to avoid Chromium HTTPS upgrading the bare app hostname.

Limits: no desktop adapter, production authentication, tenant isolation, or visual-only discovery. Structured observations rely on labels and configured sensitive nodes. Arbitrary human recovery during discovery does not publish incomplete capabilities.
