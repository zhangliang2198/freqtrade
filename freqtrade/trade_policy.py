"""Framework-owned trade permission checks shared by execution and strategy planning."""

from freqtrade.enums import ExitType
from freqtrade.persistence import LocalTrade


MANUAL_IMPORT_TAG = "manual_import"


def trade_exit_allowed(
    config: dict,
    trade: LocalTrade | None = None,
    exit_type: ExitType | None = None,
) -> bool:
    """Return whether the framework permits an active exit for this trade."""
    if exit_type in {ExitType.FORCE_EXIT, ExitType.EMERGENCY_EXIT, ExitType.LIQUIDATION}:
        return True
    if trade is None or getattr(trade, "enter_tag", None) != MANUAL_IMPORT_TAG:
        return True
    settings = config.get("manual_position_sync", {})
    return settings.get("auto_exit_positions", settings.get("auto_manage_positions", False)) is True
