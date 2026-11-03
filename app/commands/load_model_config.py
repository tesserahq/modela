"""Load what an LLM run needs from the database before the run starts.

LLM calls take seconds, so a command that awaits one must not hold a pooled
connection meanwhile (linden-api SDD 0012). It loads the ModelConfig and its
system prompt here, in one short session in the threadpool, then runs the
model holding nothing.
"""

from collections.abc import Callable

from app.db import SessionFactory
from app.models.model_config import ModelConfig
from app.repositories.model_config_repository import ModelConfigRepository
from app.repositories.system_prompt_repository import SystemPromptRepository


def load_model_config(
    sessions: SessionFactory,
    resolve: Callable[[ModelConfigRepository], ModelConfig],
) -> tuple[ModelConfig, str | None]:
    """Return the config ``resolve`` picks and its current system prompt.

    The config is detached before the session commits, so its columns stay
    loaded after the session closes. It has no relationships loaded: callers
    read columns only.
    """
    with sessions() as db:
        config = resolve(ModelConfigRepository(db))
        system_prompt = None
        if config.system_prompt_id is not None:
            system_prompt = SystemPromptRepository(db).get_current_content_by_id(
                config.system_prompt_id
            )
        db.expunge(config)
    return config, system_prompt
