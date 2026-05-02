from app.commands.domain_services.create_domain_service_command import (
    CreateDomainServiceCommand,
)
from app.events.domain_service_events import DOMAIN_SERVICE_CREATED
from app.schemas.domain_service import DomainServiceCreate
from tessera_sdk.infra.events.event import event_type


def test_create_domain_service_command_creates_and_publishes(
    db, domain_service_payload, test_user, dummy_domain_service_publisher
):
    command = CreateDomainServiceCommand(
        db, nats_publisher=dummy_domain_service_publisher
    )
    service_data = DomainServiceCreate(**domain_service_payload)

    created_service = command.execute(service_data, created_by=test_user)

    assert created_service.id is not None
    assert created_service.name == domain_service_payload["name"]
    assert created_service.domains == domain_service_payload["domains"]
    assert created_service.base_url == domain_service_payload["base_url"]

    assert len(dummy_domain_service_publisher.published) == 1
    event, published_event_type = dummy_domain_service_publisher.published[0]
    assert published_event_type == event.event_type
    assert event.event_type == event_type(DOMAIN_SERVICE_CREATED)
