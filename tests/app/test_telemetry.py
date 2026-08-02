from unittest.mock import MagicMock, patch

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace.sampling import Decision
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from app.telemetry import (
    ScanAlwaysOnSampler,
    _sanitize_async_http_request_span,
    _sanitize_http_request_span,
    _set_async_http_response_metadata,
    _set_http_response_metadata,
    setup_tracing,
)


def _unsampled_parent_context():
    span_context = SpanContext(
        trace_id=1,
        span_id=1,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.DEFAULT),
    )
    return trace.set_span_in_context(NonRecordingSpan(span_context))


def test_scan_sampler_overrides_unsampled_upstream_parent():
    sampler = ScanAlwaysOnSampler()

    scan_result = sampler.should_sample(
        _unsampled_parent_context(), 2, "POST /scan/file"
    )
    other_result = sampler.should_sample(_unsampled_parent_context(), 2, "GET /health")

    assert scan_result.decision is Decision.RECORD_AND_SAMPLE
    assert other_result.decision is Decision.DROP


def test_http_request_hook_removes_query_parameters():
    span = MagicMock()
    span.is_recording.return_value = True
    request = MagicMock()
    request.url = b"https://api.openai.com/v1/responses?token=secret"

    _sanitize_http_request_span(span, request)

    span.set_attribute.assert_any_call(
        "url.full", "https://api.openai.com/v1/responses"
    )
    span.set_attribute.assert_any_call(
        "http.url", "https://api.openai.com/v1/responses"
    )


def test_http_response_hook_records_provider_request_id():
    span = MagicMock()
    span.is_recording.return_value = True
    response = MagicMock()
    response.headers = httpx.Headers({"x-request-id": "provider-request-123"})
    request = MagicMock()
    request.url = b"https://api.openai.com/v1/responses"

    _set_http_response_metadata(span, request, response)

    span.set_attribute.assert_called_once_with(
        "gen_ai.response.id", "provider-request-123"
    )


def test_setup_tracing_exports_all_spans_and_instruments_httpx():
    with (
        patch("app.telemetry.OTLPSpanExporter"),
        patch("app.telemetry.BatchSpanProcessor"),
        patch("app.telemetry.trace.set_tracer_provider"),
        patch("app.telemetry.RequestsInstrumentor") as requests_instrumentor,
        patch("app.telemetry.HTTPXClientInstrumentor") as httpx_instrumentor,
    ):
        provider = setup_tracing(endpoint="http://collector:4317")

    assert isinstance(provider.sampler, ScanAlwaysOnSampler)
    requests_instrumentor.return_value.instrument.assert_called_once()
    httpx_instrumentor.return_value.instrument.assert_called_once()
    kwargs = httpx_instrumentor.return_value.instrument.call_args.kwargs
    assert kwargs["tracer_provider"] is provider
    assert kwargs["request_hook"] is _sanitize_http_request_span
    assert kwargs["async_request_hook"] is _sanitize_async_http_request_span
    assert kwargs["response_hook"] is _set_http_response_metadata
    assert kwargs["async_response_hook"] is _set_async_http_response_metadata
