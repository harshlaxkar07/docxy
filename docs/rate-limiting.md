# Rate Limiting & Usage Tracking

## Persistent Multi-Window Rate Limiter

All calls to external LLM / Vision APIs pass through `GroqRateLimiter`.

Counters are tracked in SQLite in the `rate_limit_state` table:
- **Second Window**: Enforces `GROQ_REQUESTS_PER_SECOND`
- **Minute Window**: Enforces `GROQ_REQUESTS_PER_MINUTE`
- **Day Window**: Enforces `GROQ_REQUESTS_PER_DAY`
- **Pacing Gap**: Enforces `GROQ_MIN_REQUEST_GAP_SECONDS` between consecutive requests

If a window cap is reached:
- When running in worker context: sleeps until the window resets or transitions job to `RETRYING` with `retry_after`.
- When rate limit errors (429) occur from provider: invokes exponential backoff with jitter up to `GROQ_MAX_RETRIES`.

All requests are audited in `api_usage` with latency and token metrics, with zero raw API key leakage.
