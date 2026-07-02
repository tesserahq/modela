# Celery worker telemetry: Grafana dashboard

`celery-worker-dashboard.json` visualizes Celery worker health — throughput,
success/failure rate, runtime percentiles, queue backlog, and per-worker
liveness — for **any worker in this infra**, sourced from **celery-exporter**
(`danihodovic/celery-exporter`), which listens to the Celery event bus on the
shared Redis broker. This is the same metrics pattern already used by every
Celery worker here (modela, conversa, indexa, eventa, orcha, quore) — no OTel
Collector pipeline required for these panels. A `Queue` dropdown variable
picks which worker's queue to inspect.

It also includes two Tempo trace drill-down panels, sourced independently
from OTel spans (`CeleryInstrumentor`) — useful for inspecting individual
slow/errored task executions, not just aggregate rates. As of writing, only
modela's worker has OTel tracing wired up (`app/infra/celery_app.py`'s
`worker_process_init` signal, active when `OTEL_ENABLED=true`), so these two
panels will be empty when `Queue` is set to any other app until that app
adds the same instrumentation.

## Prerequisite: Prometheus must actually scrape celery-exporter

This bit the first rollout: `celery-exporter` can have correct data
(verifiable directly via `curl http://<exporter-host>:9808/metrics`) while
every panel in Grafana still shows "No data", because Prometheus was never
told to scrape it. Check the infra repo's Prometheus scrape config (e.g.
`docker/prometheus/config.yml`) for a job like:

```yaml
  - job_name: 'celery-exporter'
    static_configs:
      - targets: ['celery-exporter:9808']
```

If it's missing, add it and reload Prometheus (`docker compose restart
prometheus`, or `curl -X POST http://localhost:9090/-/reload` if
`--web.enable-lifecycle` is set). Confirm via Prometheus's own UI
(`/targets`) that the job shows `UP` before troubleshooting Grafana further.

## Prerequisite: task events must be enabled per worker

celery-exporter only sees a worker's tasks if that worker publishes task
events onto the broker. This is **off by default** — Celery's own startup
banner says so explicitly (`task events: OFF (enable -E to monitor tasks in
this worker)`). For modela, `app/infra/celery_app.py` sets
`worker_send_task_events=True` and `task_send_sent_event=True` in
`celery_app.conf` so this applies regardless of how the worker process is
invoked (`run_worker.py` or a raw `celery -A ... worker` command, as used in
this infra's docker-compose). If you point this dashboard's `Queue` variable
at a different app and see no task-level data despite Prometheus scraping
fine, check whether that app's worker has task events enabled the same way.

## Identifying a worker's own tasks

Task-level metrics carry a `name` label (the dotted task path, e.g.
`app.tasks.process_import_items.process_import_items`) and a `queue_name`
label. **Don't filter on `name` alone** — multiple apps in this infra use an
`app.tasks.*` import convention, so task names alone don't disambiguate.
Every panel here filters on `queue_name="$queue_name"` instead, which is
reliable because each app routes its tasks to a dedicated, app-named queue
(modela's `celery_app.py` sets `task_default_queue="modela"` and routes
`app.tasks.*` there explicitly; other apps follow the same convention with
their own queue name).

One exception: `celery_worker_up` and `celery_worker_tasks_active` are only
labeled by `hostname`, not `queue_name`. The `$worker_hostname` template
variable works around this by deriving the selected queue's worker hostnames
from `celery_task_received_total{queue_name="$queue_name"}` (a queue-scoped
metric), then using that hostname set to filter the two per-worker panels.

## Prerequisite: Tempo service name (trace panels only)

`otel_service_name` defaults to `"modela"` for every modela process (API,
Celery worker, NATS worker) — see `app/config.py`. The `$tempo_service_name`
dashboard variable (a text box, default `modela-worker.*`) assumes
`OTEL_SERVICE_NAME=modela-worker` is set distinctly for modela's worker
process; adjust the variable if you use a different value, or if you switch
`Queue` to another app that has its own OTel service naming. This only
affects the two trace drill-down panels — the Prometheus panels above don't
depend on it.

## Importing

Grafana → Dashboards → New → Import → upload `celery-worker-dashboard.json`.
You'll be prompted to map the `DS_PROMETHEUS` and `DS_TEMPO` inputs to your
actual datasources. If you're re-importing over a dashboard you previously
saved via the Grafana UI and hit a storage/precondition error, delete the
existing dashboard first (or bump the `uid` in the JSON) rather than trying
to overwrite in place — Grafana's newer unified dashboard storage can get
stuck on stale resource versions.

## Panels

| Panel | Source | Notes |
|---|---|---|
| Task throughput | Prometheus (celery-exporter) | `sum(rate(celery_task_received_total{queue_name="$queue_name"}...))` |
| Success rate / Failure rate | Prometheus (celery-exporter) | `celery_task_succeeded_total` / `celery_task_failed_total` over `celery_task_received_total` |
| P95 task runtime | Prometheus (celery-exporter) | `histogram_quantile` over `celery_task_runtime_bucket` (seconds) |
| Queue backlog | Prometheus (celery-exporter) | `celery_queue_length{queue_name="$queue_name"}` — current unconsumed messages |
| Active worker processes | Prometheus (celery-exporter) | `celery_active_process_count{queue_name="$queue_name"}` — concurrency, not in-flight count |
| Task throughput / P95 runtime by task name | Prometheus (celery-exporter) | broken out by `name` |
| Failures by task name | Prometheus (celery-exporter) | table, `increase()` over the selected range, includes `exception` label |
| Retries by task name | Prometheus (celery-exporter) | table, `increase()` over the selected range |
| Worker up/down | Prometheus (celery-exporter) | `celery_worker_up{hostname=~"$worker_hostname"}` |
| Active in-flight tasks per worker | Prometheus (celery-exporter) | `celery_worker_tasks_active{hostname=~"$worker_hostname"}` |
| Recent errored task traces | Tempo (TraceQL) | `{resource.service.name=~"$tempo_service_name" && status=error}` |
| Slow task traces (> 2s) | Tempo (TraceQL) | adjust the `2s` threshold in the panel query as needed |
