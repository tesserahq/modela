# FastAPI service telemetry: Grafana dashboard

`fastapi-dashboard.json` visualizes HTTP-level health — request rate, error
rate (RED), latency percentiles, per-handler breakdowns — for **any FastAPI
app in this infra instrumented with prometheus-fastapi-instrumentator**
(`http_*` metrics), selected via an `Application` dropdown (the Prometheus
`job` label). It also includes Tempo trace drill-down panels (OTel
`FastAPIInstrumentor` spans) and Loki log panels (promtail container logs),
following the same structure as `celery-worker-dashboard.json`.

## Instrumentation status across the fleet

As of writing, **only modela** emits the `http_*` metrics this dashboard
queries (via `Instrumentator(...).instrument(app).expose(app)` in
`app/main.py`, active when `OTEL_ENABLED=true`). The other APIs in this infra
(sendly, orcha, custos, looply, indexa, conversa, vaulta) use a hand-rolled
`PrometheusMiddleware` (`app/utils/metrics.py` in each repo) emitting
blueswen-style `fastapi_*` metrics — that's what the pre-existing "FastAPI
Observability" dashboard in Grafana reads. The plan is to migrate those apps
to the instrumentator pattern; each app appears in this dashboard's
`Application` dropdown automatically once it (a) emits `http_requests_total`
and (b) is scraped by Prometheus. Migration per app: drop
`app/utils/metrics.py` + the `add_middleware(PrometheusMiddleware, ...)` /
`add_route("/metrics", metrics)` lines, add `prometheus-fastapi-instrumentator`
as a dependency, and mirror modela's `app/main.py` block (including
`excluded_handlers` for health-check routes).

Note the blueswen dashboard's "No data" panels (Total Exceptions, Requests In
Process, Slow Requests) are a separate issue — those need `fastapi_exceptions_total`
/ `fastapi_requests_in_progress`, which even the custom middleware apps only
partially populate. This dashboard only uses metrics instrumentator actually
emits, so every Prometheus panel works once an app is on the standard pattern.

## Prerequisite: Prometheus must scrape the app

Same trap as the Celery dashboard: metrics can be correct at the app
(`curl http://<app-host>:8000/metrics`) while Grafana shows "No data" because
Prometheus never scrapes it. **modela is currently missing from the infra's
scrape config** (`infra/production/docker/prometheus/config.yml` — it lists
the eight `*-api` jobs but not modela). Add a job before expecting data:

```yaml
  - job_name: 'modela-api'
    static_configs:
      - targets: ['modela-api:8000']
```

The job name you choose here is what appears in the `Application` dropdown.
Confirm the target shows `UP` at Prometheus `/targets` before troubleshooting
Grafana.

## Prerequisite: OTEL_ENABLED gates metrics too (modela)

In modela, the `/metrics` endpoint and Prometheus middleware are only mounted
when `OTEL_ENABLED=true` — the same flag that turns on tracing
(`app/main.py`). If the scrape target returns 404 on `/metrics`, check this
flag before anything else.

## Metric-shape gotchas baked into the panels

- **Status codes are grouped into classes** (`2xx`/`4xx`/`5xx`) by
  instrumentator's default config — the status panels show classes, not raw
  codes. If you need raw codes, that's an instrumentator option
  (`should_group_status_codes=False`), but changing it breaks these queries.
- **Two latency histograms with different tradeoffs**:
  `http_request_duration_highr_seconds` (21 buckets, no per-handler label) is
  used for the accurate service-wide p50/p95/p99 and the "Slow requests
  (> 1s)" stat; `http_request_duration_seconds` (per-handler, but only
  buckets 0.1/0.5/1/+Inf) backs the per-handler p95 panel — treat that one as
  coarse SLI banding, not precise percentiles. Per-handler *averages* (from
  `_sum`/`_count`) are exact.
- **No exceptions or in-progress metrics** exist in instrumentator's default
  set, so there are deliberately no such panels. Unhandled exceptions surface
  as 5xx in the error panels and as `status=error` traces in the Tempo panel.

## Prerequisite: Tempo service name (trace panels only)

The `$tempo_service_name` variable (textbox, default `modela`) must match the
app's `OTEL_SERVICE_NAME`. modela defaults every process to `modela`
(`app/config.py`); if the API runs with a distinct value (recommended once
worker vs API naming matters, e.g. `modela-api`), update the variable. Only
the two trace panels depend on it.

## Loki panels: service_name is the *container* name

promtail (`infra/production/docker/promtail-config.yaml`) labels every
container's logs with `service_name` = docker container name, which is **not
necessarily the Prometheus job name** (compose generates
`<project>-<service>-<n>` names unless `container_name` is pinned). The
`$loki_service_name` variable is therefore a separate dropdown populated from
Loki's actual `service_name` values — pick the container matching the
selected app. promtail also extracts `level`/`logger`/`module` labels from
JSON-formatted log lines (the log-volume panel stacks by `level`); plain-text
lines land in an empty-level series.

## Importing

Grafana → Dashboards → New → Import → upload `fastapi-dashboard.json`. You'll
be prompted to map `DS_PROMETHEUS`, `DS_TEMPO`, and `DS_LOKI` to your
datasources. If re-importing over a previously saved copy hits a
storage/precondition error, delete the existing dashboard first (or bump the
`uid`) — same Grafana unified-storage quirk noted in the Celery dashboard
README.

## Panels

| Panel | Source | Notes |
|---|---|---|
| Request rate / Total requests | Prometheus | `http_requests_total{job="$app"}` |
| 2xx rate / 5xx rate | Prometheus | share of total, grouped status classes |
| P95 latency / Slow requests (>1s) | Prometheus | `http_request_duration_highr_seconds` (service-wide, accurate) |
| Requests per second by handler / by status class | Prometheus | `sum by (handler)` / `sum by (status)` |
| Requests by handler (range) | Prometheus | table, `increase()` over selected range |
| Error rate (4xx vs 5xx) | Prometheus | grouped classes |
| Service latency p50/p95/p99 | Prometheus | high-res histogram |
| P95 latency by handler | Prometheus | coarse buckets (0.1/0.5/1) — SLI banding only |
| Average duration / response size by handler | Prometheus | exact, from `_sum`/`_count` |
| Recent errored / slow (>1s) request traces | Tempo (TraceQL) | needs `OTEL_ENABLED=true` + `$tempo_service_name` |
| Log volume by level / Application logs | Loki | `{service_name=~"$loki_service_name"}`, `$log_query` line filter |
