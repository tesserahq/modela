# Investigation: `POST /scan/file` latency

Investigate and optimize the latency of `POST /scan/file` in modela-api.

## Context

A downstream service (vaulta) uploads a small file (~200KB) to S3, then calls modela-api's `POST /scan/file?project_id=...` to have it analyzed/extracted. A distributed trace of one such request showed the *entire* request-response cycle took 11.22 seconds, and `POST /scan/file` alone accounted for 9.98s of that (89% of total end-to-end latency). That is unacceptably slow for a 200KB file and is the primary lever for fixing upload latency as experienced by callers.

Within modela-api's own server span for that request, the instrumented child spans (DB connect/queries for `users`, `model_configs`, `system_prompts`, `system_prompt_versions`, plus an outbound `POST https://custos-api.mylinden.family/authorization/authorize` call) only account for ~350ms combined. The remaining **~9.6 seconds has no child spans at all** — it's a black-box gap between the last traced DB query (fetching `system_prompt_versions`) and the response being sent. This gap is almost certainly where the actual document scan / LLM inference call happens, but it is currently completely unobserved — no span, no visibility into what's slow inside it.

## What to do

1. Trace the request handling path for `POST /scan/file` starting at `app/routers/scan_router.py`, through `app/commands/scan/create_scan_command.py`, and find where the ~9.6s untraced gap actually happens. Identify the specific call(s) responsible — this is likely a call out to an LLM provider (check `app/schemas/model_config.py` / whatever client wraps model calls) but confirm rather than assume.
2. For whatever is found in that gap, determine:
   - Is it a single LLM call, multiple sequential LLM calls, or something else (e.g., OCR/document parsing before or in addition to an LLM call)?
   - Is there any opportunity to parallelize independent sub-calls (e.g., multiple page/chunk analysis calls done concurrently instead of sequentially)?
   - Is there retry logic that could be silently multiplying the latency (e.g., a transient failure triggering a retry with backoff, invisible without spans)?
   - Is the correct/fastest suitable model being used, or is a larger/slower model configured by default where a faster one would meet quality bar?
   - Is there streaming, or does the caller wait for a complete non-streamed response even though only the final result matters?
   - Is there caching opportunity for repeated/identical scans?
3. Add OpenTelemetry instrumentation (spans) around whatever call(s) are found in the gap, so this black box becomes observable in future traces — this alone is valuable even before any optimization.
4. Also check the ~350ms of already-traced overhead per request: the `custos-api` `/authorization/authorize` call (~112ms) and the several sequential DB round-trips for `model_configs`/`system_prompts`/`system_prompt_versions` — these are on the same critical path for every scan and are candidates for caching (e.g., cache resolved model config + system prompt content, since these are unlikely to change per-request) or a single joined query instead of N sequential ones.
5. Report back: root cause of the 9.6s gap with evidence (not speculation), and a concrete, prioritized list of changes with expected latency impact for each. Do not implement changes yet unless explicitly asked — investigate and propose first.

## Constraints

- Don't guess — trace actual code paths and, if possible, reproduce with a real request/local trace to confirm where time is spent before proposing fixes.
- Flag anything that looks like it silently swallows errors or retries, since that can hide latency problems as well as correctness ones.
- Tracing implementation is explicitly in scope for this investigation. Do not implement latency optimizations until the new traces have produced evidence and the proposed optimizations have been reviewed.

## Tracing contract

- Emit a scan-specific orchestration span, a shared agent-run span, one span for every model request, and one span for every outbound provider HTTP attempt. This must distinguish structured-output retries from provider SDK/network retries.
- Permanently export 100% of `/scan/file` traces from modela-api. Preserve the normal sampling policy for other routes. Collector and observability-backend sampling or retention are outside this investigation's scope.
- Record metadata only: provider, model, model-config slug, MIME type, attempt number, streaming flag, token counts, duration, status, error type, and provider request ID when available.
- Never add file URLs, URL query parameters, prompts, output schemas, headers, document content, extracted output, exception messages, or stack traces to the new spans.
- Put reusable agent, model-request, and provider HTTP instrumentation in the shared inference layer; keep scan-specific context in the scan command.
- Deploy the instrumentation and analyze representative production traces before completing the investigation. Report call counts, retries, phase timings, and the measured latency owner.
- If one successful provider request owns the latency, isolating that provider boundary is sufficient. Separating provider-internal file retrieval, parsing, and inference can be a follow-up experiment.
- Any later model-quality comparison may be verified manually; an automated labeled corpus is not required for this tracing phase.
