# Worker telemetry: Grafana dashboard

`celery-worker-dashboard.json` visualizes the traces emitted by the Celery
worker (`app/infra/celery_app.py`) and the NATS worker (`run_nats_worker.py`)
once `OTEL_ENABLED=true`. See [Key env vars](../../README.md) / `app/config.py`
for `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`.

## What this dashboard assumes

`CeleryInstrumentor` (wired in `app/infra/celery_app.py`'s `worker_process_init`
signal) emits **spans**, not Prometheus metrics. To get rate/error/duration
panels out of that, an OTel Collector between the app and Tempo needs the
[`spanmetrics` connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/spanmetricsconnector)
enabled, which aggregates spans into the `traces_spanmetrics_calls_total` /
`traces_spanmetrics_latency_bucket` Prometheus series this dashboard queries.
The dashboard's trace drill-down panels query Tempo directly via TraceQL and
don't need the connector.

If your collector doesn't run spanmetrics yet, only the two "Trace drill-down"
panels at the bottom (raw span search) will work — the throughput/latency/error
panels will show "No data" until it's added.

Minimal collector config sketch:

```yaml
connectors:
  spanmetrics:
    namespace: traces.spanmetrics # produces the traces_spanmetrics_* metric names below
    dimensions:
      - name: celery.action
      - name: messaging.destination

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp/tempo, spanmetrics]
    metrics:
      receivers: [spanmetrics]
      exporters: [prometheusremotewrite]
```

## Prerequisite: distinguish worker from API in `service_name`

`otel_service_name` defaults to `"modela"` for every process (API, Celery
worker, NATS worker) — see `app/config.py`. Without overriding it per process,
spans/metrics from all three collapse into one `service_name` and this
dashboard's `$service_name` filter (which defaults to a `worker` regex) won't
find anything. Set distinct values before deploying:

```bash
# API
OTEL_SERVICE_NAME=modela-api

# Celery worker
OTEL_SERVICE_NAME=modela-worker

# NATS worker
OTEL_SERVICE_NAME=modela-nats-worker
```

## Importing

Grafana → Dashboards → New → Import → upload `celery-worker-dashboard.json`.
You'll be prompted to map the `DS_PROMETHEUS` and `DS_TEMPO` inputs to your
actual datasources.

## Panels

| Panel | Source | Notes |
|---|---|---|
| Task throughput | Prometheus (spanmetrics) | `sum(rate(traces_spanmetrics_calls_total...))` |
| Error rate | Prometheus (spanmetrics) | spans with `status_code="STATUS_CODE_ERROR"` |
| P95 / P99 task duration | Prometheus (spanmetrics) | `histogram_quantile` over the latency histogram |
| Task throughput / P95 duration by task name | Prometheus (spanmetrics) | broken out by `span_name`, which is the Celery task name |
| Errors by task name | Prometheus (spanmetrics) | table, `increase()` over the selected time range |
| Recent errored task traces | Tempo (TraceQL) | `{resource.service.name=~"$service_name" && status=error}` |
| Slow task traces (> 2s) | Tempo (TraceQL) | adjust the `2s` threshold in the panel query as needed |
