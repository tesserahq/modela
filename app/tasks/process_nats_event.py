from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.celery_app import celery_app
from app.core.logging_config import get_logger
from app.db import SessionLocal
from app.schemas.event import EventCreate
from app.schemas.user import UserOnboard
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from tessera_sdk.clients.identies import IdentiesClient
from tessera_sdk.infra.m2m_token import M2MTokenClient

logger = get_logger("process_nats_event_task")


@celery_app.task
def process_nats_event_task(msg: dict) -> None:
    """Handle incoming NATS events and store them in the database."""
    logger.info(f"Processing NATS event: {msg}")

    db = SessionLocal()
    try:
        # Parse time if it's a string
        time_value = msg.get("time")
        if isinstance(time_value, str):
            time_value = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
        elif time_value is None:
            time_value = datetime.now(timezone.utc)

        # Extract specific fields from the event for model columns
        event_create = EventCreate(
            source=msg.get("source", ""),
            spec_version=msg.get("spec_version", "1.0"),
            event_type=msg.get("event_type", ""),
            event_data=msg.get("event_data"),  # Store entire event here
            data_content_type=msg.get("data_content_type", "application/json"),
            subject=msg.get("subject", ""),
            time=time_value,
            tags=msg.get("tags"),
            labels=msg.get("labels"),
            privy=msg.get("privy", False),  # Default to False if not provided
            user_id=msg.get("user_id"),
            project_id=msg.get("project_id"),
        )

        # Create event using EventRepository
        event_repository = EventRepository(db)
        created_event = event_repository.create_event(event_create)

        # Ensure user is onboarded if user_id is provided
        user_id = msg.get("user_id")
        if user_id:
            _ensure_user_onboarded(db, user_id)

        logger.info(f"Event created successfully: {created_event.id}")

        # Queue indexing task asynchronously
        from app.tasks.index_entity_task import index_entity_task

        index_entity_task.delay(str(created_event.id))

    except Exception as e:
        logger.error(f"Error creating event: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_user_onboarded(db: Session, user_id: str) -> None:
    """
    Ensure a user is onboarded by checking if they exist locally,
    and if not, fetching from Identies and onboarding them.
    """
    try:
        user_repository = UserRepository(db)
        user_uuid = UUID(user_id)

        # Check if user is already onboarded
        existing_user = user_repository.get_user(user_uuid)
        if existing_user:
            logger.debug(f"User already onboarded: {user_id}")
            return

        # User doesn't exist, fetch from Identies and onboard
        m2m_token = _get_m2m_token()
        identies_client = IdentiesClient(
            base_url=get_settings().identies_base_url,
            # TODO: This is a temporary solution, we need to move this into jobs
            timeout=320,  # Shorter timeout for middleware
            max_retries=1,  # Fewer retries for middleware
            api_token=m2m_token,
        )

        identies_user = identies_client.get_user(user_id)
        user = UserOnboard(
            id=UUID(identies_user.id),
            email=identies_user.email,
            first_name=identies_user.first_name,
            last_name=identies_user.last_name,
            avatar_url=identies_user.avatar_url,
            provider=identies_user.provider,
            verified=identies_user.verified,
            verified_at=identies_user.verified_at,
            confirmed_at=identies_user.confirmed_at,
            external_id=identies_user.external_id,
        )
        user_repository.onboard_user(user)
        logger.info(f"User onboarded successfully: {user.id}")
    except Exception as e:
        # Log error but don't fail the event processing
        logger.error(f"Error fetching/onboarding user: {e}", exc_info=True)


def _get_m2m_token() -> str:
    """
    Get an M2M token for Quore.
    """
    return M2MTokenClient().get_token_sync().access_token
