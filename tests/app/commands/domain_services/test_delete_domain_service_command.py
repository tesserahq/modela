from uuid import uuid4

import pytest
from app.commands.domain_services.delete_domain_service_command import (
    DeleteDomainServiceCommand,
)
from app.events.domain_service_events import DOMAIN_SERVICE_DELETED
from app.exceptions.handlers import ResourceNotFoundError
from app.repositories.domain_service_repository import DomainServiceRepository
from tessera_sdk.infra.events.event import event_type


def test_delete_domain_service_command_deletes_and_publishes(
    db, setup_domain_service, test_user, dummy_domain_service_publisher
):
    command = DeleteDomainServiceCommand(
        db, nats_publisher=dummy_domain_service_publisher
    )

    command.execute(setup_domain_service.id, deleted_by=test_user)

    service = DomainServiceRepository(db).get_service(setup_domain_service.id)
    assert service is None

    assert len(dummy_domain_service_publisher.published) == 1
    event, published_event_type = dummy_domain_service_publisher.published[0]
    assert published_event_type == event.event_type
    assert event.event_type == event_type(DOMAIN_SERVICE_DELETED)


def test_delete_domain_service_command_missing_service_raises(
    db, test_user, dummy_domain_service_publisher
):
    command = DeleteDomainServiceCommand(
        db, nats_publisher=dummy_domain_service_publisher
    )

    with pytest.raises(ResourceNotFoundError):
        command.execute(uuid4(), deleted_by=test_user)

    assert dummy_domain_service_publisher.published == []
