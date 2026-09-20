# Genuine Docker end-to-end evidence

On 2026-09-20, discovery and paired replay were launched through the actual execution API behind the container dashboard. The worker used Playwright against Cedar Bank with PostgreSQL. Discovery called local Ollama mistral:latest and completed 14 model-selected actions. Its newly saved capability replayed with a different customer/address in 14 actions and zero model decisions.

capability.json links to the discovery run. Each API export includes job/run IDs, action reasons, events, and sanitized results. These are real runs, not test doubles. The save was explicitly approved for each invocation. No human participation is claimed for these runs.
