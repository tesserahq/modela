import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base
from app.models.mixins import TimestampMixin


class ProviderModelCatalogEntry(Base, TimestampMixin):
    """One detected change in a provider's model list, or one failed check.

    Entries are never deleted, so there is no soft-delete mixin (PRD 0023).
    """

    __tablename__ = "provider_model_catalog_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(String(50), nullable=False, index=True)
    # added | removed | check_failed
    kind = Column(String(20), nullable=False, index=True)
    # Set for added and removed entries; null for check_failed.
    model_id = Column(String(255), nullable=True)
    # Set for check_failed entries only (missing_key, network, http_error, unknown).
    error_category = Column(String(50), nullable=True)
    detected_at = Column(DateTime, nullable=False, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ProviderModelCatalogSnapshot(Base, TimestampMixin):
    """The live model ids last seen for one provider.

    Replaced only after a successful fetch, so a failed check can't
    change the baseline for the next run (PRD 0023).
    """

    __tablename__ = "provider_model_catalog_snapshots"

    provider_id = Column(String(50), primary_key=True)
    model_ids = Column(JSON, nullable=False)
    captured_at = Column(DateTime, nullable=False)
