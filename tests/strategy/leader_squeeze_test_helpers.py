"""Shared fixtures for the configurable leader-squeeze strategy tests.

Tuning values come from the public runtime configuration. The entry-price guard
is explicitly disabled in these legacy policy fixtures, which do not construct
closed OHLC history and frozen candidate signals. Its dedicated regression tests
exercise hard enforcement, including the enabled-by-default production behavior.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, TypeVar


_REPO_ROOT = Path(__file__).parents[2]
_STRATEGY_DIR = _REPO_ROOT / "user_data" / "strategies"
if str(_STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGY_DIR))

with (_REPO_ROOT / "user_data" / "config.json").open(encoding="utf-8") as _config_file:
    PUBLIC_CONFIG: dict[str, Any] = json.load(_config_file)


T = TypeVar("T")


def configured_settings() -> dict[str, Any]:
    """Isolate existing policies; entry-price tests supply their own signal history."""

    settings = copy.deepcopy(PUBLIC_CONFIG["leader_squeeze"])
    settings["entry_price_guard_enabled"] = False
    return settings


def configured_strategy(cls: type[T]) -> T:
    """Create an uninitialised strategy and apply the production config path.

    ``__new__`` is used because most unit tests intentionally avoid starting
    background workers. The configuration module is imported lazily so this
    helper can be imported before an ``importlib``-loaded strategy module.
    The price guard is disabled only in the fixture's copied configuration.
    """

    instance = cls.__new__(cls)
    config = copy.deepcopy(PUBLIC_CONFIG)
    config["leader_squeeze"]["entry_price_guard_enabled"] = False
    from leader_squeeze_config import configure_strategy

    configure_strategy(instance, config)
    return instance
