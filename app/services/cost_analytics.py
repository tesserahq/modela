from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository
from app.schemas.completion_request import CostSummaryItem
from app.schemas.user import UserCompact


def attach_group_details(
    group_by: str,
    items: list[CostSummaryItem],
    db: Session,
) -> list[CostSummaryItem]:
    if group_by != "user":
        return items

    user_ids: list[UUID] = [
        group_value for item in items if (group_value := item.group_value) is not None
    ]
    if not user_ids:
        return items

    users = UserRepository(db).get_users_by_ids(user_ids)
    users_by_id = {user.id: UserCompact.model_validate(user) for user in users}

    return [
        (
            item.model_copy(update={"group_details": users_by_id.get(item.group_value)})
            if item.group_value is not None
            else item
        )
        for item in items
    ]
