from uuid import uuid4

import pytest
from app.commands.domain_services.update_domain_service_command import (
    UpdateDomainServiceCommand,
)
from app.events.domain_service_events import DOMAIN_SERVICE_UPDATED
from app.exceptions.handlers import ResourceNotFoundError
from app.schemas.domain_service import DomainServiceUpdate
from tessera_sdk.infra.events.event import event_type


def test_update_domain_service_command_updates_and_publishes(
    db, setup_domain_service, test_user, dummy_domain_service_publisher
):
    command = UpdateDomainServiceCommand(
        db, nats_publisher=dummy_domain_service_publisher
    )
    update_data = DomainServiceUpdate(name="Updated Service", enabled=False)

    updated_service = command.execute(
        setup_domain_service.id, update_data, updated_by=test_user
    )

    assert updated_service.id == setup_domain_service.id
    assert updated_service.name == "Updated Service"
    assert updated_service.enabled is False

    assert len(dummy_domain_service_publisher.published) == 1
    event, published_event_type = dummy_domain_service_publisher.published[0]
    assert published_event_type == event.event_type
    assert event.event_type == event_type(DOMAIN_SERVICE_UPDATED)


def test_update_domain_service_command_missing_service_raises(
    db, test_user, dummy_domain_service_publisher
):
    command = UpdateDomainServiceCommand(
        db, nats_publisher=dummy_domain_service_publisher
    )
    update_data = DomainServiceUpdate(name="Missing")

    with pytest.raises(ResourceNotFoundError):
        command.execute(uuid4(), update_data, updated_by=test_user)

    assert dummy_domain_service_publisher.published == []
