from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.domain_service import DomainService
from app.models.event import Event
from app.models.reindex_job import ReindexJob
from app.repositories.domain_service_repository import DomainServiceRepository
from app.repositories.event_repository import EventRepository
from app.repositories.reindex_repository import ReindexRepository
from app.exceptions.handlers import ResourceNotFoundError


def get_domain_service_by_id(
    service_id: UUID,
    db: Session = Depends(get_db),
) -> DomainService:
    """FastAPI dependency to get a domain service by ID.

    Args:
        service_id: The UUID of the domain service to retrieve
        db: Database session dependency

    Returns:
        DomainService: The retrieved domain service

    Raises:
        HTTPException: If the domain service is not found
    """
    domain_service = DomainServiceRepository(db).get_service(service_id)
    if domain_service is None:
        raise HTTPException(status_code=404, detail="Domain service not found")
    return domain_service


def get_event_by_id(
    event_id: UUID,
    db: Session = Depends(get_db),
) -> Event:
    """FastAPI dependency to get an event by ID.

    Args:
        event_id: The UUID of the event to retrieve
        db: Database session dependency

    Returns:
        Event: The retrieved event

    Raises:
        ResourceNotFoundError: If the event is not found
    """
    event = EventRepository(db).get_event(event_id)
    if event is None:
        raise ResourceNotFoundError(f"Event with id {event_id} not found")
    return event


def get_reindex_job_by_id(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> ReindexJob:
    """FastAPI dependency to get a reindex job by ID.

    Args:
        job_id: The UUID of the reindex job to retrieve
        db: Database session dependency

    Returns:
        ReindexJob: The retrieved reindex job

    Raises:
        ResourceNotFoundError: If the reindex job is not found
    """
    job = ReindexRepository(db).get_reindex_job(job_id)
    if job is None:
        raise ResourceNotFoundError(f"Reindex job with id {job_id} not found")
    return job
