from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation import fastapi as otel_fastapi
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, DEFAULT_ON, Sampler
from starlette.routing import Match

from app.config import Settings


class ScanAlwaysOnSampler(Sampler):
    """Always export scan traces while preserving normal sampling elsewhere."""

    def should_sample(
        self,
        parent_context,
        trace_id,
        name,
        kind=None,
        attributes=None,
        links=None,
        trace_state=None,
    ):
        route = (attributes or {}).get("http.route")
        if name == "POST /scan/file" or route == "/scan/file":
            return ALWAYS_ON.should_sample(
                parent_context,
                trace_id,
                name,
                kind,
                attributes,
                links,
                trace_state,
            )
        return DEFAULT_ON.should_sample(
            parent_context,
            trace_id,
            name,
            kind,
            attributes,
            links,
            trace_state,
        )

    def get_description(self) -> str:
        return "ScanAlwaysOnSampler"


def _decoded_url(raw_url) -> str:
    if isinstance(raw_url, bytes):
        return raw_url.decode("utf-8", errors="replace")
    return str(raw_url)


def _sanitize_http_request_span(span, request) -> None:
    """Keep outbound HTTP visibility without exporting query parameters."""
    if not span.is_recording():
        return
    parsed = urlsplit(_decoded_url(request.url))
    sanitized_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    span.set_attribute("url.full", sanitized_url)
    # The installed HTTP semantic conventions currently emit the legacy key.
    span.set_attribute("http.url", sanitized_url)


async def _sanitize_async_http_request_span(span, request) -> None:
    _sanitize_http_request_span(span, request)


def _provider_request_id(headers) -> str | None:
    items = headers.items() if hasattr(headers, "items") else headers
    for raw_key, raw_value in items:
        key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        if key.lower() not in {"x-request-id", "request-id", "openai-request-id"}:
            continue
        return (
            raw_value.decode(errors="replace")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
    return None


def _set_http_response_metadata(span, request, response) -> None:
    if not span.is_recording():
        return
    hostname = urlsplit(_decoded_url(request.url)).hostname
    if hostname not in {"api.openai.com", "api.anthropic.com"}:
        return
    request_id = _provider_request_id(response.headers)
    if request_id:
        span.set_attribute("gen_ai.response.id", request_id)


async def _set_async_http_response_metadata(span, request, response) -> None:
    _set_http_response_metadata(span, request, response)


def _patch_fastapi_route_details() -> None:
    """
    opentelemetry-instrumentation-fastapi==0.63b1's _get_route_details() guards
    AttributeError only on the Match.FULL branch, not Match.PARTIAL. FastAPI
    >=0.137 wraps include_router()'d routers in _IncludedRouter, which lacks
    a .path attribute and matches as PARTIAL for most requests, crashing every
    request with AttributeError. Fixed upstream in 0.64b0, but that version
    requires opentelemetry-sdk>=1.43 which conflicts with logfire (pulled in
    via pydantic-ai) capping it at <1.43. Patch locally until that's resolved.
    """

    def _get_route_details(scope):
        app = scope["app"]
        route = None

        for starlette_route in app.routes:
            match, _ = starlette_route.matches(scope)
            if match == Match.FULL:
                route = getattr(starlette_route, "path", scope.get("path"))
                break
            if match == Match.PARTIAL:
                route = getattr(starlette_route, "path", route)
        return route

    otel_fastapi._get_route_details = _get_route_details


def setup_tracing(endpoint: Optional[str] = None):
    # Manually create a fresh, uncached Settings instance
    settings = Settings()

    if endpoint is None:
        endpoint = settings.otel_exporter_otlp_endpoint

    # Resource can be required for some backends, e.g. Jaeger
    # If resource wouldn't be set - traces wouldn't appears in Jaeger
    resource = Resource(attributes={"service.name": settings.otel_service_name})

    # An unsampled upstream parent must not suppress scan latency diagnostics.
    tracer_provider = TracerProvider(resource=resource, sampler=ScanAlwaysOnSampler())
    trace.set_tracer_provider(tracer_provider)

    otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)

    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    RequestsInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        request_hook=_sanitize_http_request_span,
        response_hook=_set_http_response_metadata,
        async_request_hook=_sanitize_async_http_request_span,
        async_response_hook=_set_async_http_response_metadata,
    )

    return tracer_provider
