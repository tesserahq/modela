"""Architecture guards for transaction ownership, provided by
tessera_sdk.testing.transaction_guards (see docs/managed-transactions.md in
tessera-sdk-py).

Every rule is fully enforced, so any violation fails, including
``async_database_access`` (synchronous database access inside ``async def``,
linden-api SDD 0012). The only exceptions are the reasoned early commits in
``early_commit_allowlist``. Async routes that await LLM or MCP calls take
``ShortSessions`` and do their database work in the threadpool.
"""

from pathlib import Path

import pytest
from tessera_sdk.testing.transaction_guards import (
    DEFAULT_TRANSACTION_DIRS,
    EVENT_LOOP_RULE_NAMES,
    RULE_NAMES,
    TransactionGuardConfig,
    assert_matches_baseline,
)

CONFIG = TransactionGuardConfig(
    app_root=Path(__file__).parents[2] / "app",
    baseline_path=Path(__file__).with_name("transaction_baseline.json"),
    transaction_dirs=(*DEFAULT_TRANSACTION_DIRS, "middleware", "core", "messaging"),
    session_modules=("db.py", "services/sdk_user_service.py"),
    repository_base_modules=(),
    # Allowlisted top-level workflows that commit early around external I/O:
    # (path relative to app/, function name) -> reason.
    early_commit_allowlist={},
)


@pytest.mark.parametrize("rule", RULE_NAMES)
def test_transaction_rule_matches_baseline(rule):
    assert_matches_baseline(CONFIG, rule)


@pytest.mark.parametrize("rule", EVENT_LOOP_RULE_NAMES)
def test_event_loop_rule_matches_baseline(rule):
    """Synchronous database access in ``async def`` blocks the event loop
    (linden-api SDD 0012)."""
    assert_matches_baseline(CONFIG, rule)
