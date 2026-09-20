"""Shared fixtures for the configurable leader-squeeze strategy tests.

The strategy is intentionally configured from the merged runtime and strategy
configuration in these tests.  This exercises the same configuration path as
a freshly constructed strategy.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, TypeVar


_REPO_ROOT = Path(__file__).parents[2]
_STRATEGY_DIR = _REPO_ROOT / "user_data" / "strategies" / "leader_squeeze"
if str(_STRATEGY_DIR) not in sys.path:
    sys.path.insert(0, str(_STRATEGY_DIR))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


with (_REPO_ROOT / "user_data" / "config.json").open(encoding="utf-8") as _config_file:
    _runtime_config: dict[str, Any] = json.load(_config_file)
with (_STRATEGY_DIR / "config.json").open(encoding="utf-8") as _strategy_config_file:
    _strategy_config: dict[str, Any] = json.load(_strategy_config_file)

# Freqtrade gives the root config precedence over included config fragments.
PUBLIC_CONFIG: dict[str, Any] = _deep_merge(_strategy_config, _runtime_config)


T = TypeVar("T")


def configured_settings() -> dict[str, Any]:
    """Return an isolated copy of the strategy settings from public config."""

    return copy.deepcopy(PUBLIC_CONFIG["leader_squeeze"])


def configured_strategy(cls: type[T]) -> T:
    """Create an uninitialised strategy and apply the production config path.

    ``__new__`` is used because most unit tests intentionally avoid starting
    background workers.  The configuration module is imported lazily so this
    helper can be imported before an ``importlib``-loaded strategy module.
    """

    instance = cls.__new__(cls)
    config = copy.deepcopy(PUBLIC_CONFIG)
    from leader_squeeze_helpers import configure_strategy

    configure_strategy(instance, config)
    return instance
