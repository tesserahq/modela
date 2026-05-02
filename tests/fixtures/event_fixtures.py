from datetime import timezone
import pytest
from app.models.event import Event


def _build_event_data(faker, overrides: dict | None = None) -> dict:
    """Generate default event data with optional overrides."""
    base_data = {
        "source": faker.uri(),
        "spec_version": "1.0",
        "event_type": faker.random_element(
            elements=("user.created", "user.updated", "system.alert")
        ),
        "event_data": {"payload": faker.pydict(value_types=[str])},
        "data_content_type": "application/json",
        "subject": faker.sentence(nb_words=3),
        "time": faker.date_time(tzinfo=timezone.utc),
        "tags": faker.words(nb=3),
        "labels": {"environment": faker.random_element(elements=("prod", "dev", "qa"))},
        "project_id": "704894b7-f2de-4e02-824a-2c4b6ecf08b6",
    }

    if overrides:
        base_data.update(overrides)

    return base_data


@pytest.fixture(scope="function")
def setup_event(db, faker):
    """Create a persisted event instance for testing."""
    event_data = _build_event_data(faker)
    event = Event(**event_data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture(scope="function")
def setup_event_factory(db, faker):
    """Factory fixture for creating persisted events with custom attributes."""

    def _create_event(**overrides):
        event_data = _build_event_data(faker, overrides)
        event = Event(**event_data)
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    return _create_event
