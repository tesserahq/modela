from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.inference.adapters.base import BaseProviderAdapter
from app.schemas.provider import LiveProviderModel, ProviderModelSchema
from app.tasks.check_provider_model_catalog import check_provider_model_catalog_task


class _FakeAdapter(BaseProviderAdapter):
    def __init__(self, provider_id, model_id_prefixes, curated, live, fetch_error=None):
        self.provider_id = provider_id
        self.provider_name = provider_id
        self.model_id_prefixes = model_id_prefixes
        self._curated = curated
        self._live = live
        self._fetch_error = fetch_error

    def create_model(self, model_name, api_key=None):
        raise NotImplementedError

    def list_models(self):
        return self._curated

    def fetch_live_model_ids(self):
        if self._fetch_error is not None:
            raise self._fetch_error
        return self._live


def _live(id: str) -> LiveProviderModel:
    return LiveProviderModel(id=id, created_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_publishes_added_event_when_new_model_found():
    adapter = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[ProviderModelSchema(id="claude-opus-5", name="Claude Opus 5")],
        live=[_live("claude-opus-5"), _live("claude-opus-6")],
    )
    publisher = MagicMock()

    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()

    assert publisher.publish_sync.call_count == 1
    event, event_type = publisher.publish_sync.call_args.args
    assert event.event_data["model_ids"] == ["claude-opus-6"]
    assert event_type.endswith("provider_model.added")


def test_publishes_removed_event_when_curated_model_gone():
    adapter = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[
            ProviderModelSchema(id="claude-opus-5", name="Claude Opus 5"),
            ProviderModelSchema(id="claude-opus-4", name="Claude Opus 4"),
        ],
        live=[_live("claude-opus-5")],
    )
    publisher = MagicMock()

    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()

    assert publisher.publish_sync.call_count == 1
    event, event_type = publisher.publish_sync.call_args.args
    assert event.event_data["model_ids"] == ["claude-opus-4"]
    assert event_type.endswith("provider_model.removed")


def test_no_event_published_when_no_drift():
    adapter = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[ProviderModelSchema(id="claude-opus-5", name="Claude Opus 5")],
        live=[_live("claude-opus-5")],
    )
    publisher = MagicMock()

    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()

    publisher.publish_sync.assert_not_called()


def test_one_provider_failure_does_not_block_the_other():
    failing_adapter = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[],
        live=[],
        fetch_error=RuntimeError("boom"),
    )
    healthy_adapter = _FakeAdapter(
        "openai",
        ("gpt", "o"),
        curated=[ProviderModelSchema(id="gpt-4o", name="GPT-4o")],
        live=[_live("gpt-4o"), _live("gpt-5")],
    )
    publisher = MagicMock()

    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": failing_adapter, "openai": healthy_adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()

    assert publisher.publish_sync.call_count == 1
    event, _ = publisher.publish_sync.call_args.args
    assert event.event_data["provider_id"] == "openai"


def test_publish_failure_is_swallowed():
    adapter = _FakeAdapter(
        "anthropic",
        ("claude",),
        curated=[],
        live=[_live("claude-opus-6")],
    )
    publisher = MagicMock()
    publisher.publish_sync.side_effect = RuntimeError("nats down")

    with (
        patch(
            "app.tasks.check_provider_model_catalog.PROVIDER_REGISTRY",
            {"anthropic": adapter},
        ),
        patch(
            "app.tasks.check_provider_model_catalog.NatsEventPublisher",
            return_value=publisher,
        ),
    ):
        check_provider_model_catalog_task()  # should not raise
