"""Required configuration loading and validation; parameter values live in config.json."""

from __future__ import annotations

import math

from leader_squeeze_support import LeaderMixinContext


class LeaderConfigMixin(LeaderMixinContext):
    def _validate_score_settings(self) -> None:
        if not math.isclose(sum(self.settings["weights"].values()), 1.0, abs_tol=1e-9):
            raise ValueError("leader_squeeze weights must add up to 1.0")
        if any(not math.isfinite(v) or v < 0 for v in self.settings["weights"].values()):
            raise ValueError("leader_squeeze weights must be finite and non-negative")
        for key in (
            "momentum_full_score",
            "liquidation_min_notional",
            "replacement_score_gap",
        ):
            if not math.isfinite(float(self.settings[key])) or float(self.settings[key]) <= 0:
                raise ValueError(f"leader_squeeze {key} must be positive and finite")
        if not (
            0
            <= float(self.settings["base_entry_score"])
            <= float(self.settings["additional_entry_score"])
            <= 100
            and 0 <= float(self.settings["min_short_share"]) < 1
            and 0 <= float(self.settings["min_trend_continuity"]) <= 1
        ):
            raise ValueError("leader_squeeze entry score/short share/trend thresholds are invalid")
        for key in ("market_min_coverage_ratio", "market_down_ratio"):
            if not 0 < float(self.settings[key]) <= 1:
                raise ValueError(f"leader_squeeze {key} must be within (0, 1]")
        if (
            not math.isfinite(float(self.settings["status_log_seconds"]))
            or float(self.settings["status_log_seconds"]) <= 0
        ):
            raise ValueError("leader_squeeze status_log_seconds must be positive and finite")
        max_positions = self.settings["max_positions"]
        if type(max_positions) is not int or max_positions < 1:
            raise ValueError("leader_squeeze max_positions must be a positive integer")
        stake_ratio = self.settings["stake_ratio"]
        if (
            type(stake_ratio) not in (int, float)
            or not math.isfinite(stake_ratio)
            or not 0 < stake_ratio <= 1 / (max_positions + 1)
        ):
            raise ValueError("stake_ratio must be positive and leave one buy-first rotation slot")
        framework_limit = self.config.get("max_open_trades", 0)
        if type(framework_limit) not in (int, float) or not (
            framework_limit in (-1, math.inf)
            or (
                math.isfinite(framework_limit)
                and framework_limit % 1 == 0
                and framework_limit >= max_positions + 1
            )
        ):
            raise ValueError(
                f"max_open_trades must be >= {max_positions + 1} (or unlimited): "
                f"max_positions={max_positions} requires one extra buy-first rotation slot"
            )

    def _validate_reversal_settings(self) -> None:
        if self.timeframe != self.config["timeframe"]:
            raise ValueError("strategy timeframe must match config timeframe")
        for key, minimum in (
            ("reversal_lookback_candles", 5),
            ("reversal_confirm_candles", 2),
            ("reversal_slow_candles", 3),
        ):
            if type(self.settings[key]) is not int or not minimum <= self.settings[key] <= 40:
                raise ValueError(f"leader_squeeze {key} must be an integer within [{minimum}, 40]")
        if (
            max(self.settings["reversal_lookback_candles"], self.settings["atr_period"] + 1)
            + self.settings["reversal_confirm_candles"]
            > self.startup_candle_count
        ):
            raise ValueError("reversal lookback/confirmation exceeds startup_candle_count")
        if (
            not math.isfinite(float(self.settings["reversal_atr_buffer"]))
            or float(self.settings["reversal_atr_buffer"]) < 0
        ):
            raise ValueError("leader_squeeze reversal_atr_buffer must be non-negative and finite")
        fast_buffer = float(self.settings["reversal_fast_atr_buffer"])
        if not math.isfinite(fast_buffer) or fast_buffer <= float(
            self.settings["reversal_atr_buffer"]
        ):
            raise ValueError(
                "reversal_fast_atr_buffer must be finite and exceed reversal_atr_buffer"
            )
        slow_drop = float(self.settings["reversal_slow_atr_drop"])
        if not math.isfinite(slow_drop) or slow_drop <= 0:
            raise ValueError("reversal_slow_atr_drop must be positive and finite")
        if (
            self.settings["trend_ema_candles"] + self.settings["reversal_slow_candles"]
            > self.startup_candle_count
        ):
            raise ValueError("reversal slow confirmation exceeds startup_candle_count")

    def _validate_entry_heat_settings(self) -> None:
        penalty = self.settings["entry_heat_max_penalty"]
        scale = self.settings["entry_heat_return_scale"]
        start = self.settings["entry_heat_extension_start_atr"]
        full = self.settings["entry_heat_extension_full_atr"]
        if any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (penalty, scale, start, full)
        ):
            raise ValueError("entry heat settings must be finite numbers")
        if not (0 <= penalty <= 0.5 and scale > 0 and 0 <= start < full):
            raise ValueError(
                "entry heat requires penalty within [0, .5], scale > 0, 0 <= start < full"
            )
        if penalty and self.startup_candle_count < self.ENTRY_HEAT_HISTORY_CANDLES:
            raise ValueError(
                f"entry heat requires {self.ENTRY_HEAT_HISTORY_CANDLES} closed candles"
            )

    def _validate_tuning_settings(self) -> None:
        """Reject impossible scales and invalid rotation settings before trading."""
        for key in (
            "short_score_start_share",
            "short_score_full_share",
            "momentum_return_weight",
            "volume_activity_weight",
            "liquidation_warmup_score",
            "entry_heat_cooled_breakout_factor",
            "entry_heat_base_fraction",
            "replacement_fast_close_location",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"leader_squeeze {key} must be within [0, 1]")
        if self.settings["short_score_start_share"] >= self.settings["short_score_full_share"]:
            raise ValueError("short_score_full_share must exceed short_score_start_share")
        for key in (
            "volume_score_full_ratio",
            "volume_activity_full_ratio",
            "taker_score_full_ratio",
            "liquidation_score_full_ratio",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 1:
                raise ValueError(f"leader_squeeze {key} must exceed 1")
        for key in (
            "oi_score_full_drop",
            "entry_heat_box_max_width_atr",
            "entry_heat_prebreak_extension_max_atr",
            "entry_heat_breakout_overshoot_atr",
            "replacement_fast_score_gap",
            "replacement_fast_volume_ratio",
            "replacement_fast_taker_ratio",
            "replacement_fast_max_breakout_atr",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"leader_squeeze {key} must be positive and finite")
        self._validate_rotation_settings()

    def _validate_rotation_settings(self) -> None:
        for key, low, high in (
            ("entry_heat_ema_candles", 2, 1440),
            ("entry_heat_box_candles", 2, 1440),
            ("replacement_no_new_high_candles", 2, 100),
            ("replacement_fast_breakout_candles", 2, 100),
            ("replacement_fast_volume_baseline_candles", 2, 100),
            ("replacement_confirmations", 1, 10),
            ("replacement_fast_confirmations", 1, 10),
        ):
            value = self.settings[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"leader_squeeze {key} must be an integer within [{low}, {high}]")
        for key in (
            "replacement_entry_score",
            "replacement_weak_score",
            "replacement_fast_entry_score",
            "replacement_fast_core_score",
            "replacement_candidate_hysteresis",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"leader_squeeze {key} must be within [0, 100]")
        for key in (
            "replacement_min_age_minutes",
            "replacement_cooldown_minutes",
            "replacement_fast_min_age_minutes",
            "replacement_fast_cooldown_minutes",
            "replacement_reentry_cooldown_minutes",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError(f"leader_squeeze {key} must be non-negative and finite")
        if type(self.settings["replacement_fast_enabled"]) is not bool:
            raise ValueError("replacement_fast_enabled must be boolean")
        if self.settings["replacement_fast_entry_score"] < self.settings["replacement_entry_score"]:
            raise ValueError("fast entry score must be >= normal entry score")
        if self.settings["replacement_fast_score_gap"] < self.settings["replacement_score_gap"]:
            raise ValueError("fast score gap must be >= normal score gap")
        core_max = 100 * sum(
            self.settings["weights"][k] for k in ("momentum", "volume", "taker_buy")
        )
        if (
            self.settings["replacement_fast_enabled"]
            and self.settings["replacement_fast_core_score"] > core_max
        ):
            raise ValueError("replacement_fast_core_score exceeds available weighted core points")


REQUIRED_SETTINGS = frozenset(
    (
        "leverage",
        "stake_ratio",
        "min_positions",
        "max_positions",
        "base_entry_score",
        "additional_entry_score",
        "min_short_share",
        "short_share_filter_enabled",
        "min_absolute_momentum",
        "min_trend_continuity",
        "momentum_full_score",
        "short_score_start_share",
        "short_score_full_share",
        "momentum_return_weight",
        "volume_score_full_ratio",
        "volume_activity_weight",
        "volume_activity_full_ratio",
        "volume_activity_baseline_candles",
        "taker_score_full_ratio",
        "oi_score_full_drop",
        "liquidation_score_full_ratio",
        "liquidation_warmup_score",
        "entry_heat_max_penalty",
        "entry_heat_return_scale",
        "entry_heat_extension_start_atr",
        "entry_heat_extension_full_atr",
        "entry_heat_ema_candles",
        "entry_heat_box_candles",
        "entry_heat_box_max_width_atr",
        "entry_heat_prebreak_extension_max_atr",
        "entry_heat_breakout_overshoot_atr",
        "entry_heat_cooled_breakout_factor",
        "entry_heat_base_fraction",
        "liquidation_min_notional",
        "market_min_coverage_ratio",
        "market_down_ratio",
        "market_emergency_enabled",
        "market_emergency_ratio",
        "market_emergency_drop",
        "taker_window_candles",
        "rotation_recovery_enabled",
        "rotation_recovery_grace_seconds",
        "rotation_recovery_interval_seconds",
        "rotation_recovery_max_age_seconds",
        "rotation_recovery_confirmations",
        "rotation_recovery_history_limit",
        "score_refresh_seconds",
        "score_retry_seconds",
        "status_log_seconds",
        "data_grace_seconds",
        "remote_metric_max_age_seconds",
        "liquidation_stream_max_age_seconds",
        "external_stop_check_seconds",
        "max_spread_ratio",
        "max_slippage_ratio",
        "reversal_lookback_candles",
        "reversal_confirm_candles",
        "reversal_atr_buffer",
        "reversal_fast_atr_buffer",
        "reversal_slow_candles",
        "reversal_slow_atr_drop",
        "holding_timeframe",
        "background_timeframe",
        "trend_slope_candles",
        "reversal_intrabar_atr_buffer",
        "reversal_emergency_memory_candles",
        "replacement_weak_atr_drop",
        "replacement_entry_score",
        "replacement_weak_score",
        "replacement_score_gap",
        "replacement_confirmations",
        "replacement_min_age_minutes",
        "replacement_cooldown_minutes",
        "replacement_no_new_high_candles",
        "replacement_candidate_hysteresis",
        "replacement_reentry_cooldown_minutes",
        "replacement_fast_enabled",
        "replacement_fast_entry_score",
        "replacement_fast_score_gap",
        "replacement_fast_confirmations",
        "replacement_fast_min_age_minutes",
        "replacement_fast_cooldown_minutes",
        "replacement_fast_core_score",
        "replacement_fast_breakout_candles",
        "replacement_fast_volume_baseline_candles",
        "replacement_fast_volume_ratio",
        "replacement_fast_taker_ratio",
        "replacement_fast_close_location",
        "replacement_fast_max_breakout_atr",
        "manage_external_positions",
        "weights",
        "external_exit_retry_seconds",
        "eth_pair",
        "order_book_max_age_seconds",
        "order_book_depth",
        "entry_heat_history_days",
        "atr_period",
        "trend_ema_candles",
        "eth_confirm_candles",
        "reversal_pivot_side_candles",
        "momentum_lookback_candles",
        "trend_continuity_candles",
        "volume_window_candles",
        "volume_baseline_windows",
        "candle_min_history",
        "oi_sample_count",
        "liquidation_window_seconds",
        "liquidation_recent_seconds",
        "position_sync_seconds",
        "position_stale_seconds",
        "metric_request_timeout_seconds",
        "funding_request_timeout_seconds",
        "funding_max_age_seconds",
        "metric_workers",
        "liquidation_open_timeout_seconds",
        "liquidation_close_timeout_seconds",
        "liquidation_receive_timeout_seconds",
        "liquidation_reconnect_seconds",
        "rest_base_url",
        "liquidation_stream_url",
        "state_file_live",
        "state_file_dry_run",
        "rotation_audit_enabled",
        "rotation_audit_statement_timeout_ms",
        "rotation_audit_retry_seconds",
        "rotation_audit_spool_live",
        "rotation_audit_spool_dry_run",
    )
)
FRAMEWORK_SETTINGS = (
    "timeframe",
    "startup_candle_count",
    "minimal_roi",
    "stoploss",
    "use_exit_signal",
    "exit_profit_only",
    "position_adjustment_enable",
    "process_only_new_candles",
    "order_types",
    "order_time_in_force",
)


def configure_strategy(strategy, config: dict, *, framework: bool = True) -> None:
    from copy import deepcopy

    supplied = config.get("leader_squeeze", {})
    if not isinstance(supplied, dict):
        raise ValueError("leader_squeeze must be a configuration object")
    missing = sorted(REQUIRED_SETTINGS - supplied.keys())
    missing += [key for key in FRAMEWORK_SETTINGS if key not in config]
    if missing:
        raise ValueError("Missing required strategy configuration: " + ", ".join(missing))
    expected_weights = {
        "short_crowding",
        "momentum",
        "volume",
        "taker_buy",
        "liquidation",
        "oi_squeeze",
        "funding",
    }
    if set(supplied["weights"]) != expected_weights:
        raise ValueError("leader_squeeze.weights must specify all seven score components")
    strategy.config = config
    strategy.settings = deepcopy(supplied)
    if framework:
        for key in FRAMEWORK_SETTINGS:
            setattr(strategy, key, deepcopy(config[key]))


def validate_runtime_settings(strategy) -> None:
    settings = strategy.settings
    integer_keys = (
        "atr_period",
        "trend_ema_candles",
        "eth_confirm_candles",
        "reversal_pivot_side_candles",
        "momentum_lookback_candles",
        "trend_continuity_candles",
        "volume_window_candles",
        "volume_baseline_windows",
        "volume_activity_baseline_candles",
        "candle_min_history",
        "oi_sample_count",
        "metric_workers",
        "taker_window_candles",
        "rotation_recovery_confirmations",
        "rotation_recovery_history_limit",
        "entry_heat_history_days",
        "order_book_depth",
        "rotation_audit_statement_timeout_ms",
        "trend_slope_candles",
        "reversal_emergency_memory_candles",
    )
    for key in integer_keys:
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError(f"leader_squeeze.{key} must be a positive integer")
    for key, value in settings.items():
        if key.endswith("_seconds") and (
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
        ):
            raise ValueError(f"leader_squeeze.{key} must be positive and finite")
    for key in (
        "manage_external_positions",
        "replacement_fast_enabled",
        "rotation_audit_enabled",
        "short_share_filter_enabled",
        "market_emergency_enabled",
        "rotation_recovery_enabled",
    ):
        if type(settings[key]) is not bool:
            raise ValueError(f"leader_squeeze.{key} must be boolean")
    if settings["liquidation_recent_seconds"] >= settings["liquidation_window_seconds"]:
        raise ValueError(
            "liquidation_recent_seconds must be smaller than liquidation_window_seconds"
        )
    if settings["oi_sample_count"] < 2:
        raise ValueError("oi_sample_count must include at least two observations")
    _validate_volume_history(strategy)
    _validate_execution_safety_settings(settings)
    if settings["reversal_lookback_candles"] < 2 * settings["reversal_pivot_side_candles"] + 1:
        raise ValueError("reversal lookback cannot hold the configured pivot window")
    _validate_multi_timeframe_settings(strategy)
    required_history = max(
        settings[key] + 1 for key in integer_keys if key.endswith("_candles") or key == "atr_period"
    )
    if (
        type(strategy.startup_candle_count) is not int
        or strategy.startup_candle_count < required_history
    ):
        raise ValueError("startup_candle_count does not cover the configured indicator windows")


def _validate_execution_safety_settings(settings: dict) -> None:
    for key in ("market_emergency_ratio", "market_emergency_drop"):
        value = settings[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"{key} must be within (0, 1]")
    if not (
        1 <= settings["taker_window_candles"] <= 500
        and 2 <= settings["rotation_recovery_confirmations"] <= 10
        and 1 <= settings["rotation_recovery_history_limit"] <= 1000
        and settings["rotation_recovery_interval_seconds"]
        <= settings["rotation_recovery_grace_seconds"]
        < settings["rotation_recovery_max_age_seconds"]
        <= 2 * 86400
    ):
        raise ValueError("invalid taker window or rotation recovery limits")


def _validate_volume_history(strategy) -> None:
    settings = strategy.settings
    if settings["volume_activity_baseline_candles"] <= settings["volume_baseline_windows"]:
        raise ValueError("volume activity baseline must exceed the short baseline")
    if type(strategy.startup_candle_count) is not int or (
        strategy.startup_candle_count
        < settings["volume_window_candles"]
        + max(settings["volume_baseline_windows"], settings["volume_activity_baseline_candles"])
    ):
        raise ValueError("startup_candle_count must cover both volume baselines and signal window")


def _validate_multi_timeframe_settings(strategy) -> None:
    from freqtrade.exchange import timeframe_to_seconds

    settings = strategy.settings
    try:
        base = timeframe_to_seconds(strategy.timeframe)
        holding = timeframe_to_seconds(settings["holding_timeframe"])
        background = timeframe_to_seconds(settings["background_timeframe"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("invalid holding_timeframe/background_timeframe") from exc
    if not (base < holding < background and holding % base == background % base == 0):
        raise ValueError("higher timeframes must increase and be exact multiples of timeframe")
    for key in ("reversal_intrabar_atr_buffer", "replacement_weak_atr_drop"):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"leader_squeeze.{key} must be positive and finite")
    if settings["reversal_intrabar_atr_buffer"] < settings["reversal_atr_buffer"]:
        raise ValueError("intrabar ATR buffer must be >= ordinary reversal ATR buffer")
    holding_count = max(
        max(settings["reversal_lookback_candles"], settings["atr_period"] + 1)
        + settings["reversal_confirm_candles"],
        settings["trend_ema_candles"] + settings["reversal_slow_candles"],
        settings["trend_ema_candles"] + settings["trend_slope_candles"],
        settings["replacement_no_new_high_candles"],
    )
    background_count = max(
        settings["trend_ema_candles"] + settings["trend_slope_candles"],
        settings["atr_period"] + 2,
    )
    aggregation_history = max(
        (holding_count + 1) * (holding // base),
        (background_count + 1) * (background // base),
        settings["reversal_emergency_memory_candles"]
        + (max(settings["reversal_lookback_candles"], settings["atr_period"] + 1) + 1)
        * (holding // base),
    )
    if strategy.startup_candle_count < aggregation_history:
        raise ValueError("startup_candle_count does not cover complete higher timeframe windows")
