from datetime import timezone
from uuid import uuid4

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate
from app.repositories.event_repository import EventRepository


def _build_event_create(faker) -> EventCreate:
    """Helper to construct an EventCreate payload with realistic data."""
    return EventCreate(
        source=faker.uri(),
        spec_version="1.0",
        event_type="user.created",
        event_data={"user_id": str(uuid4()), "action": "signup"},
        data_content_type="application/json",
        subject=f"signup-{faker.uuid4()}",
        time=faker.date_time(tzinfo=timezone.utc),
        tags=faker.words(nb=2),
        labels={"env": faker.random_element(elements=("prod", "qa"))},
    )


def test_create_event(db, faker):
    repository = EventRepository(db)
    payload = _build_event_create(faker)

    created = repository.create_event(payload)

    assert created.id is not None
    assert created.source == payload.source
    assert created.event_data == payload.event_data


def test_get_event(db, setup_event):
    repository = EventRepository(db)

    fetched = repository.get_event(setup_event.id)

    assert fetched is not None
    assert fetched.id == setup_event.id


def test_update_event(db, faker, setup_event):
    repository = EventRepository(db)
    new_subject = faker.sentence(nb_words=4)
    update_payload = EventUpdate(
        subject=new_subject,
        tags=["updated"],
        labels={"priority": "high"},
    )

    updated = repository.update_event(setup_event.id, update_payload)

    assert updated is not None
    assert updated.subject == new_subject
    assert updated.tags == ["updated"]
    assert updated.labels == {"priority": "high"}


def test_delete_event(db, setup_event):
    repository = EventRepository(db)

    result = repository.delete_event(setup_event.id)

    assert result is True

    deleted_event = (
        db.query(Event)
        .execution_options(skip_soft_delete_filter=True)
        .filter(Event.id == setup_event.id)
        .first()
    )
    assert deleted_event is not None
    assert deleted_event.deleted_at is not None


def test_search_events(db, setup_event_factory):
    repository = EventRepository(db)
    target_event = setup_event_factory(event_type="user.created", subject="user signup")
    setup_event_factory(event_type="system.alert", subject="system down")

    results = repository.search({"event_type": "user.created"})

    assert len(results) == 1
    assert results[0].id == target_event.id


def test_get_events_by_tags_and_labels(db, setup_event_factory):
    repository = EventRepository(db)
    matching = setup_event_factory(tags=["alpha", "beta"], labels={"category": "news"})
    second = setup_event_factory(tags=["alpha"], labels={"category": "news"})
    third = setup_event_factory(tags=["alpha", "beta"], labels={"category": "ops"})

    events_by_tags = repository.get_events_by_tags_and_labels(tags=["alpha", "beta"])
    assert {event.id for event in events_by_tags} == {matching.id, third.id}

    events_with_labels = repository.get_events_by_tags_and_labels(
        tags=["alpha"], labels={"category": "news"}
    )
    assert {event.id for event in events_with_labels} == {matching.id, second.id}
