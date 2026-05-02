import pytest

from app.models.domain_service import DomainService


def _build_domain_service_data(faker, overrides: dict | None = None) -> dict:
    base_data = {
        "name": faker.company(),
        "domains": [f"{faker.domain_word()}.{faker.domain_word()}"],
        "base_url": faker.url(),
        "indexes_path_prefix": None,
        "excluded_entities": None,
        "enabled": True,
    }

    if overrides:
        base_data.update(overrides)

    return base_data


@pytest.fixture(scope="function")
def domain_service_payload(faker):
    return _build_domain_service_data(faker)


@pytest.fixture(scope="function")
def setup_domain_service(db, faker):
    service_data = _build_domain_service_data(faker)
    service = DomainService(**service_data)
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@pytest.fixture(scope="function")
def setup_domain_service_factory(db, faker):
    def _create_domain_service(**overrides):
        service_data = _build_domain_service_data(faker, overrides)
        service = DomainService(**service_data)
        db.add(service)
        db.commit()
        db.refresh(service)
        return service

    return _create_domain_service


@pytest.fixture(scope="function")
def dummy_domain_service_publisher():
    class DummyPublisher:
        def __init__(self):
            self.published = []

        def publish_sync(self, event, event_type):
            self.published.append((event, event_type))

    return DummyPublisher()


@pytest.fixture(scope="function")
def mock_domain_service_nats(monkeypatch):
    class DummyPublisher:
        def publish_sync(self, *args, **kwargs):
            return None

    from app.commands.domain_services import create_domain_service_command
    from app.commands.domain_services import update_domain_service_command
    from app.commands.domain_services import delete_domain_service_command

    monkeypatch.setattr(
        create_domain_service_command, "NatsEventPublisher", DummyPublisher
    )
    monkeypatch.setattr(
        update_domain_service_command, "NatsEventPublisher", DummyPublisher
    )
    monkeypatch.setattr(
        delete_domain_service_command, "NatsEventPublisher", DummyPublisher
    )
