"""Manual futures reconciliation uses real Trade persistence and mocked exchange I/O."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import ccxt
import pytest

from freqtrade.enums import TradingMode
from freqtrade.exceptions import OperationalException
from freqtrade.freqtradebot import FreqtradeBot
from freqtrade.manual_position_sync import ManualPositionSync
from freqtrade.persistence import Order, Trade


NOW = 1_800_000_000.0
PAIR = "BTC/USDT:USDT"


def order(oid="entry", side="buy", amount=1.0, price=100.0, stamp=NOW - 60):
    return {
        "id": oid,
        "symbol": PAIR,
        "side": side,
        "amount": amount,
        "filled": amount,
        "remaining": 0,
        "price": price,
        "average": price,
        "cost": price * amount,
        "status": "closed",
        "type": "market",
        "timestamp": int(stamp * 1000),
        "lastTradeTimestamp": int(stamp * 1000),
        "info": {},
    }


def stop(oid="stop", **changes):
    return {
        **order(oid, "sell"),
        "status": "open",
        "filled": 0,
        "type": "stop_market",
        "stopPrice": 80,
        "reduceOnly": True,
        **changes,
    }


@pytest.fixture
def env(init_persistence, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr("freqtrade.manual_position_sync.time.time", lambda: clock[0])
    settings = {
        "enabled": True,
        "import_positions": True,
        "cleanup_orphan_stops": True,
        "interval_seconds": 60,
        "orphan_stop_interval_seconds": 60,
        "confirmations": 2,
        "history_lookback_days": 7,
        "history_limit": 1000,
    }
    position = {
        "symbol": PAIR,
        "side": "long",
        "contracts": 1.0,
        "entryPrice": 100.0,
        "leverage": 5,
        "hedged": False,
    }
    exchange = SimpleNamespace(
        fetch_positions=Mock(return_value=[position]),
        fetch_orders=Mock(return_value=[order()]),
        _contracts_to_amount=lambda pair, contracts: contracts,
        _api=SimpleNamespace(
            options={},
            fetch_open_orders=Mock(return_value=[]),
            fetch_leverages=Mock(return_value={PAIR: {"longLeverage": 5.0, "shortLeverage": 5.0}}),
        ),
        get_fee=Mock(return_value=0.001),
        get_pair_base_currency=lambda pair: "BTC",
        get_precision_amount=lambda pair: 0.001,
        get_precision_price=lambda pair: 0.01,
        precisionMode=ccxt.TICK_SIZE,
        precision_mode_price=ccxt.TICK_SIZE,
        get_contract_size=lambda pair: 1.0,
        id="binance",
        fetch_stoploss_order=Mock(return_value=stop()),
        cancel_stoploss_order_with_result=Mock(return_value=stop(status="canceled")),
    )
    bot = SimpleNamespace(
        config={
            "manual_position_sync": settings,
            "dry_run": False,
            "stake_currency": "USDT",
            "timeframe": "15m",
        },
        exchange=exchange,
        trading_mode=TradingMode.FUTURES,
        strategy=SimpleNamespace(
            can_short=False,
            stoploss=-1.0,
            order_types={},
            get_strategy_name=lambda: "LeaderSqueezeStrategy",
        ),
        wallets=SimpleNamespace(update=Mock()),
        handle_onexchange_order=Mock(),
        update_trade_state=Mock(),
    )
    return bot, ManualPositionSync(bot), clock


def twice(env):
    _, sync, clock = env
    sync.run()
    clock[0] += 61
    sync.run()


def existing_trade(bot):
    entry = order()
    trade = Trade(
        pair=PAIR,
        base_currency="BTC",
        stake_currency="USDT",
        amount=1,
        stake_amount=20,
        fee_open=0.001,
        fee_close=0.001,
        open_rate=100,
        open_date=datetime.fromtimestamp(NOW - 60, UTC),
        is_open=True,
        exchange=bot.exchange.id,
        strategy=bot.strategy.get_strategy_name(),
        timeframe=15,
        leverage=5,
        trading_mode=TradingMode.FUTURES,
        amount_precision=bot.exchange.get_precision_amount(PAIR),
        price_precision=bot.exchange.get_precision_price(PAIR),
        precision_mode=bot.exchange.precisionMode,
        precision_mode_price=bot.exchange.precision_mode_price,
        contract_size=bot.exchange.get_contract_size(PAIR),
    )
    trade.orders.append(Order.parse_from_ccxt_object(entry, PAIR, "buy"))
    trade.recalc_trade_from_orders()
    Trade.session.add(trade)
    Trade.commit()
    return trade


def bind_real_order_recovery(bot, position_amount):
    """Use the production recovery loop with a small state-update adapter."""

    def update_trade_state(trade, order_id, action_order=None, **kwargs):
        assert action_order is not None
        trade.update_order(action_order)
        order_obj = trade.select_order_by_order_id(order_id)
        assert order_obj is not None
        trade.update_trade(order_obj, recalculating=not kwargs.get("send_msg", True))

    bot.update_trade_state = Mock(side_effect=update_trade_state)
    bot.handle_onexchange_order = FreqtradeBot.handle_onexchange_order.__get__(bot)
    bot.cancel_stoploss_on_exchange = Mock(side_effect=lambda trade: trade)
    bot.order_close_notify = Mock()
    bot._notify_exit = Mock()
    bot.handle_protections = Mock()
    bot.wallets.get_owned = Mock(return_value=position_amount)


def test_import_requires_two_snapshots_and_preserves_real_fill_id_time_and_amount(env):
    _, sync, clock = env
    sync.run()
    assert Trade.get_open_trades() == []
    clock[0] += 61
    sync.run()
    trades = Trade.get_open_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.enter_tag == "manual_import"
    assert trade.amount == 1
    assert trade.open_rate == 100
    assert trade.stake_amount == 20
    assert trade.open_date_utc == datetime.fromtimestamp(NOW - 60, UTC)
    assert [o.order_id for o in trade.orders] == ["entry"]
    assert trade.get_custom_data("manual_sync")["source"] == "exchange_orders"
    clock[0] += 61
    sync.run()
    assert len(Trade.get_open_trades()) == 1
    assert sync.blocked == set()


def test_reconciliation_interval_is_configurable_and_throttles_api_reads(env):
    bot, sync, clock = env

    sync.run()
    initial_calls = bot.exchange.fetch_positions.call_count
    assert initial_calls == 1

    clock[0] += 59
    sync.run()
    assert bot.exchange.fetch_positions.call_count == initial_calls

    clock[0] += 2
    sync.run()
    assert bot.exchange.fetch_positions.call_count > initial_calls


def test_wallet_refresh_failure_does_not_abort_reconciliation(env):
    bot, sync, _ = env
    bot.wallets.update.side_effect = RuntimeError("wallet unavailable")

    sync.run()

    assert bot.exchange.fetch_positions.call_count == 1
    assert bot.strategy._manual_sync_healthy is False


def test_import_fetches_leverage_when_position_does_not_include_it(env):
    bot, _, _ = env
    position = bot.exchange.fetch_positions.return_value[0]
    del position["leverage"]

    twice(env)

    trade = Trade.get_open_trades()[0]
    assert trade.leverage == 5
    bot.exchange._api.fetch_leverages.assert_called()


def test_import_preserves_exchange_liquidation_price(env):
    bot, _, _ = env
    bot.exchange.fetch_positions.return_value[0]["liquidationPrice"] = 75.0

    twice(env)

    trade = Trade.get_open_trades()[0]
    assert trade.liquidation_price == 75.0


def test_long_gap_requires_two_fresh_position_confirmations(env):
    bot, sync, clock = env

    sync.run()
    clock[0] += 121
    sync.run()
    assert Trade.get_open_trades() == []
    assert bot.exchange.fetch_orders.call_count == 0

    clock[0] += 61
    sync.run()
    assert len(Trade.get_open_trades()) == 1


def test_missing_open_orders_response_never_imports_or_cancels(env):
    bot, sync, clock = env
    bot.exchange._api.fetch_open_orders.return_value = None

    sync.run()
    clock[0] += 61
    sync.run()

    assert Trade.get_open_trades() == []
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


@pytest.mark.parametrize("change", ["add", "reduce", "close"])
def test_existing_trade_reconciles_manual_position_change(env, change):
    bot, sync, clock = env
    existing_trade(bot)
    if change == "add":
        current_amount = 2.0
        exchange_orders = [
            order(),
            order("add", "buy", amount=1.0, price=100.0, stamp=NOW - 30),
        ]
    elif change == "reduce":
        current_amount = 0.5
        exchange_orders = [
            order(),
            order("reduce", "sell", amount=0.5, price=110.0, stamp=NOW - 30),
        ]
    else:
        current_amount = 0.0
        exchange_orders = [
            order(),
            order("close", "sell", amount=1.0, price=110.0, stamp=NOW - 30),
        ]
    bot.exchange.fetch_orders.return_value = exchange_orders
    bot.exchange.fetch_positions.return_value = (
        []
        if current_amount == 0
        else [
            {
                "symbol": PAIR,
                "side": "long",
                "contracts": current_amount,
                "entryPrice": 100.0,
                "leverage": 5,
                "hedged": False,
            }
        ]
    )
    bind_real_order_recovery(bot, current_amount)

    sync.run()
    clock[0] += 61
    sync.run()

    saved = Trade.get_trades().first()
    assert saved is not None
    if change == "add":
        assert saved.is_open is True
        assert saved.amount == 2.0
        assert saved.nr_of_successful_entries == 2
    elif change == "reduce":
        assert saved.is_open is True
        assert saved.amount == 0.5
        assert saved.nr_of_successful_exits == 1
    else:
        assert saved.is_open is False
        assert saved.nr_of_successful_exits == 1


@pytest.mark.parametrize(
    "fault",
    [
        "partial_history",
        "truncated",
        "invalid_amount",
        "wrong_price",
        "pending",
        "short",
        "network",
    ],
)
def test_unverified_position_never_creates_a_trade(env, fault):
    bot, _, _ = env
    if fault == "partial_history":
        bot.exchange.fetch_orders.return_value = []
    elif fault == "truncated":
        bot.exchange.fetch_orders.return_value = [order()] * 1000
    elif fault == "invalid_amount":
        bot.exchange.fetch_orders.return_value = [order(amount=float("nan"))]
    elif fault == "wrong_price":
        bot.exchange.fetch_orders.return_value = [order(price=101)]
    elif fault == "pending":
        bot.exchange._api.fetch_open_orders.return_value = [stop()]
    elif fault == "short":
        bot.exchange.fetch_positions.return_value[0]["side"] = "short"
    else:
        bot.exchange.fetch_positions.side_effect = RuntimeError("offline")
    twice(env)
    assert Trade.get_open_trades() == []
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


def test_external_position_blocks_same_pair_entry_when_import_is_disabled(env):
    _, sync, _ = env
    sync.settings["import_positions"] = False

    sync.run()

    assert PAIR in sync.blocked
    assert not sync.entry_allowed(PAIR)
    assert Trade.get_open_trades() == []


def test_import_attaches_existing_stop_without_creating_another(env):
    bot, _, _ = env
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [stop()] if kw.get("params") else []
    )
    twice(env)
    trade = Trade.get_open_trades()[0]
    assert len(trade.open_sl_orders) == 1
    assert trade.open_sl_orders[0].order_id == "stop"


def test_orphan_stop_deleted_only_after_two_flat_checks(env):
    bot, sync, clock = env
    bot.exchange.fetch_positions.return_value = []
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [stop()] if kw.get("params") else []
    )
    sync.run()
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()
    clock[0] += 61
    sync.run()
    bot.exchange.cancel_stoploss_order_with_result.assert_called_once_with("stop", PAIR, 0)


@pytest.mark.parametrize(
    "fault", ["position", "pending", "take_profit", "entry_stop", "network", "reopened"]
)
def test_orphan_cleanup_preserves_ambiguous_or_still_needed_orders(env, fault):
    bot, sync, clock = env
    bot.exchange.fetch_positions.return_value = []
    candidate = stop()
    if fault == "take_profit":
        candidate["type"] = "take_profit_market"
    if fault == "entry_stop":
        candidate["reduceOnly"] = False
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [candidate] if kw.get("params") else []
    )
    sync.run()
    clock[0] += 61
    if fault == "position":
        bot.exchange.fetch_positions.return_value = [
            {"symbol": PAIR, "contracts": 1, "side": "long", "entryPrice": 100, "leverage": 5}
        ]
    if fault == "pending":
        bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
            [candidate] if kw.get("params") else [order()]
        )
    if fault == "network":
        bot.exchange.fetch_positions.side_effect = RuntimeError("offline")
    if fault == "reopened":
        bot.exchange.fetch_positions.side_effect = [
            [],
            [{"symbol": PAIR, "contracts": 1, "side": "long"}],
        ]
    sync.run()
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


def test_dry_run_never_reads_or_mutates_real_account(env):
    bot, sync, _ = env
    bot.config["dry_run"] = True
    sync.run()
    bot.exchange.fetch_positions.assert_not_called()
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


def test_restart_does_not_reuse_flat_confirmation(env):
    bot, sync, clock = env
    bot.exchange.fetch_positions.return_value = []
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [stop()] if kw.get("params") else []
    )
    sync.run()
    clock[0] += 61
    ManualPositionSync(bot).run()
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


def test_binance_account_stop_scan_uses_real_ccxt_without_network(env):
    bot, _, _ = env
    api = ccxt.binance({"options": {"defaultType": "swap"}})
    api.privateGetOpenOrders = Mock(return_value=[])
    api.markets = {}
    api.fapiPrivateGetOpenAlgoOrders = Mock(return_value=[])
    bot.exchange._api = api
    bot.exchange.fetch_positions.return_value = []
    sync = ManualPositionSync(bot)
    sync.run()
    api.fapiPrivateGetOpenAlgoOrders.assert_called_once_with({})


def test_import_accepts_weighted_entry_price_rounded_to_market_tick(env):
    bot, sync, clock = env
    bot.exchange.fetch_orders.return_value = [
        order("first", amount=0.5, price=100.00, stamp=NOW - 90),
        order("second", amount=0.5, price=100.01),
    ]
    bot.exchange.fetch_positions.return_value[0]["entryPrice"] = 100.005
    twice(env)
    assert len(Trade.get_open_trades()) == 1
    clock[0] += 61
    sync.run()
    assert PAIR not in sync.blocked


def test_entry_price_accepts_exchange_average_within_one_market_tick(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    trade.open_rate = 0.023335
    trade.price_precision = 0.000001
    position = {"entryPrice": 0.0233344801}

    assert sync._entry_price_matches(trade, position)

    position["entryPrice"] = 0.0233324
    assert not sync._entry_price_matches(trade, position)


def test_pending_conditional_entry_keeps_flat_position_protective_stop(env):
    bot, _, _ = env
    bot.exchange.fetch_positions.return_value = []
    pending_entry = stop("conditional-entry", side="buy", reduceOnly=False)
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [stop(), pending_entry] if kw.get("params") else []
    )
    twice(env)
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()


def test_existing_trade_does_not_accept_history_with_wrong_entry_price(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    bot.exchange.fetch_positions.return_value[0]["contracts"] = 2
    bot.exchange.fetch_orders.return_value = [order(), order("extra", price=110, stamp=NOW - 30)]
    bind_real_order_recovery(bot, 2)
    twice(env)
    Trade.session.refresh(trade)
    assert trade.amount == 1
    assert trade.open_rate == 100
    assert PAIR in sync.blocked


def test_manual_add_after_prior_partial_exit_keeps_trade_open(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    reduced = order("old-reduce", "sell", amount=0.5, price=110, stamp=NOW - 45)
    trade.orders.append(Order.parse_from_ccxt_object(reduced, PAIR, "sell"))
    trade.recalc_trade_from_orders()
    Trade.commit()
    bot.exchange.fetch_orders.return_value = [
        order(),
        reduced,
        order("new-add", amount=0.5, stamp=NOW - 30),
    ]
    bind_real_order_recovery(bot, 1)
    twice(env)
    Trade.session.refresh(trade)
    assert trade.is_open
    assert trade.amount == 1
    assert trade.nr_of_successful_exits == 1
    assert PAIR not in sync.blocked


def test_reconciliation_uses_configured_history_beyond_seven_days(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    opened = datetime.fromtimestamp(NOW - 30 * 86400, UTC)
    trade.open_date = opened
    trade.orders[0].order_date = opened
    trade.orders[0].order_filled_date = opened
    Trade.commit()
    sync.settings["history_lookback_days"] = 89
    bot.exchange.fetch_positions.return_value[0]["contracts"] = 2
    bot.exchange.fetch_orders.return_value = [
        order(stamp=NOW - 30 * 86400),
        order("new-add", amount=1, stamp=NOW - 30),
    ]
    bind_real_order_recovery(bot, 2)

    twice(env)

    requested_since = bot.exchange.fetch_orders.call_args.args[1]
    assert requested_since <= opened + timedelta(seconds=1)
    assert trade.amount == 2


def test_blocked_pair_cannot_enter_through_framework_entry(env):
    bot, sync, _ = env
    bot.manual_position_sync = sync
    sync.run()  # First unmatched snapshot: awaiting confirmation.
    assert FreqtradeBot.execute_entry(bot, PAIR, 10) is False


def test_stop_query_failure_still_allows_native_stop_recovery(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    trade.orders.append(Order.parse_from_ccxt_object(stop(), PAIR, "stoploss"))
    Trade.commit()
    bot.manual_position_sync = sync
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.exchange.fetch_stoploss_order.side_effect = RuntimeError("temporary outage")
    bot.handle_stoploss_on_exchange = Mock(return_value=True)
    sync.run()
    assert FreqtradeBot.exit_positions(bot, [trade]) == 1
    bot.handle_stoploss_on_exchange.assert_called_once_with(trade)


def test_reconciliation_block_never_skips_native_stop_handling(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    bot.manual_position_sync = sync
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.wallets.check_exit_amount = Mock(return_value=True)
    bot.handle_stoploss_on_exchange = Mock(return_value=True)
    sync.blocked = {PAIR}
    sync.stop_retry = set()

    assert FreqtradeBot.exit_positions(bot, [trade]) == 1
    bot.handle_stoploss_on_exchange.assert_called_once_with(trade)


def test_failed_unknown_order_recovery_does_not_persist_half_imported_order(env):
    bot, _, _ = env
    trade = existing_trade(bot)
    recovered = order("manual-fill", amount=0.5, stamp=NOW - 30)
    bot.update_trade_state = Mock(side_effect=RuntimeError("injected failure"))
    bot.handle_onexchange_order = FreqtradeBot.handle_onexchange_order.__get__(bot)

    assert not bot.handle_onexchange_order(trade, orders=[recovered])
    assert Order.order_by_id("manual-fill", PAIR) is None
    assert [item.order_id for item in Trade.get_trades([Trade.id == trade.id]).first().orders] == [
        "entry"
    ]


def test_filled_algo_stop_is_not_counted_twice_when_syncing_later_manual_add(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    triggered = stop("algo-stop", status="closed", filled=0.5, amount=0.5, average=90)
    trade.orders.append(Order.parse_from_ccxt_object(triggered, PAIR, "stoploss"))
    trade.recalc_trade_from_orders()
    Trade.commit()
    bot.exchange.fetch_stoploss_order.return_value = {**triggered, "id_stop": "actual-stop"}
    bot.exchange.fetch_orders.return_value = [
        order(),
        order("actual-stop", "sell", amount=0.5, price=90, stamp=NOW - 45),
        order("new-add", amount=0.5, stamp=NOW - 30),
    ]
    bind_real_order_recovery(bot, 1)
    twice(env)
    Trade.session.refresh(trade)
    assert trade.is_open
    assert trade.amount == 1
    assert [o.order_id for o in trade.orders] == ["entry", "algo-stop", "new-add"]
    assert PAIR not in sync.blocked


def test_direction_change_restarts_manual_import_confirmation(env):
    bot, sync, clock = env
    bot.strategy.can_short = True
    sync.run()
    clock[0] += 61
    bot.exchange.fetch_positions.return_value[0]["side"] = "short"
    bot.exchange.fetch_orders.return_value = [order(side="sell")]
    sync.run()
    assert Trade.get_open_trades() == []
    clock[0] += 61
    sync.run()
    assert Trade.get_open_trades()[0].is_short


def test_exchange_error_log_keeps_code_without_signed_url_or_credentials(env, caplog):
    bot, sync, _ = env
    bot.exchange.fetch_positions.side_effect = ccxt.ExchangeError(
        'https://example.invalid/?signature=SECRET {"code": -2015, "msg": "apikey=SECRET"}'
    )
    sync.run()
    assert "code=-2015" in caplog.text
    assert "SECRET" not in caplog.text


def test_partially_executing_algo_stop_waits_for_native_completion(env):
    bot, sync, _ = env
    trade = existing_trade(bot)
    trade.orders.append(Order.parse_from_ccxt_object(stop(), PAIR, "stoploss"))
    Trade.commit()
    bot.exchange.fetch_positions.return_value[0]["contracts"] = 0.8
    bot.exchange.fetch_stoploss_order.return_value = {
        **stop(filled=0.2),
        "id_stop": "actual-stop",
        "status_stop": "triggered",
    }
    bot.exchange.fetch_orders.return_value = [order(), order("actual-stop", "sell", amount=0.2)]
    bind_real_order_recovery(bot, 0.8)
    twice(env)
    assert bot.exchange.fetch_orders.call_count == 0
    assert PAIR in sync.blocked
    assert [o.order_id for o in trade.orders] == ["entry", "stop"]


@pytest.mark.parametrize("missing_price", ["filled_market", "protective_stop"])
def test_import_accepts_real_market_and_stop_orders_without_limit_price(env, missing_price):
    bot, _, _ = env
    if missing_price == "filled_market":
        raw = order()
        raw["price"] = None
        bot.exchange.fetch_orders.return_value = [raw]
    else:
        raw = stop(price=None, average=None, triggerPrice=80)
        bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
            [raw] if kw.get("params") else []
        )
        bot.exchange.fetch_stoploss_order.return_value = raw
    twice(env)
    trades = Trade.get_open_trades()
    assert len(trades) == 1
    assert all(o.ft_price is not None for o in trades[0].orders)


@pytest.mark.parametrize("enabled", [None, False, True])
def test_manual_management_requires_explicit_opt_in(enabled):
    from freqtrade.enums import ExitType
    from freqtrade.trade_policy import trade_exit_allowed

    config = {} if enabled is None else {"manual_position_sync": {"auto_exit_positions": enabled}}
    manual_trade = SimpleNamespace(enter_tag="manual_import")
    assert trade_exit_allowed(config, manual_trade) is (enabled is True)
    assert trade_exit_allowed(config, manual_trade, ExitType.EMERGENCY_EXIT)
    assert trade_exit_allowed(config, manual_trade, ExitType.LIQUIDATION)
    assert trade_exit_allowed(config)
    assert trade_exit_allowed(config, SimpleNamespace(enter_tag="leader"))


@pytest.mark.parametrize(
    ("exchange_id", "trading_mode"),
    [("bybit", TradingMode.FUTURES), ("binance", TradingMode.SPOT)],
)
def test_manual_sync_rejects_unsupported_exchange_or_mode(env, exchange_id, trading_mode):
    bot, _, _ = env
    bot.exchange.id = exchange_id
    bot.trading_mode = trading_mode

    with pytest.raises(OperationalException, match="supports Binance linear futures only"):
        ManualPositionSync(bot)


def test_manual_exit_disabled_blocks_strategy_sales_but_runs_stop_handler(env):
    from freqtrade.enums import ExitCheckTuple, ExitType

    bot, sync, _ = env
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    bot.manual_position_sync = sync
    bot.handle_stoploss_on_exchange = Mock(return_value=False)
    bot.handle_trade = Mock(return_value=False)
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.wallets.check_exit_amount = Mock(return_value=True)
    assert FreqtradeBot.exit_positions(bot, [trade]) == 0
    bot.handle_stoploss_on_exchange.assert_called_once_with(trade)
    bot.handle_trade.assert_not_called()
    for reason in (
        ExitType.EXIT_SIGNAL,
        ExitType.CUSTOM_EXIT,
        ExitType.STOP_LOSS,
        ExitType.TRAILING_STOP_LOSS,
        ExitType.ROI,
        ExitType.PARTIAL_EXIT,
    ):
        assert not FreqtradeBot.execute_trade_exit(bot, trade, 90, ExitCheckTuple(reason))


def test_manual_exit_filter_allows_liquidation_when_auto_exit_is_disabled(env):
    from freqtrade.enums import ExitCheckTuple, ExitType

    bot, sync, _ = env
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    bot.manual_position_sync = sync
    bot.strategy.should_exit = Mock(
        return_value=[
            ExitCheckTuple(ExitType.ROI),
            ExitCheckTuple(ExitType.LIQUIDATION),
        ]
    )
    bot.execute_trade_exit = Mock(return_value=True)
    bot._exit_reason_cache = {}

    assert FreqtradeBot._check_and_execute_exit(bot, trade, 80, False, False, None)
    bot.execute_trade_exit.assert_called_once()
    assert bot.execute_trade_exit.call_args.args[2].exit_type == ExitType.LIQUIDATION


def test_import_populates_amount_requested(env):
    twice(env)
    assert Trade.get_open_trades()[0].amount_requested == 1.0


@pytest.fixture
def manual_protection(env):
    bot, sync, _ = env
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.config["manual_position_sync"].update(
        auto_exit_positions=False, manage_protective_stops=True
    )
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    trade.adjust_stop_loss(100, -1, initial=True)
    Trade.commit()
    stops = {}
    events = []
    bot.exchange.price_to_precision = lambda pair, price, **kw: round(price, 2)
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [o for o in stops.values() if o["status"] == "open"] if kw.get("params") else []
    )
    bot.exchange.fetch_stoploss_order.side_effect = lambda oid, pair: stops[oid].copy()

    def create(t, trigger):
        events.append("create")
        raw = stop("new", amount=t.amount, stopPrice=trigger)
        stops["new"] = raw
        t.orders.append(Order.parse_from_ccxt_object(raw, PAIR, "stoploss"))
        return True

    def cancel(oid, pair, amount):
        events.append("cancel:" + oid)
        stops[oid]["status"] = "canceled"
        return stops[oid].copy()

    bot.create_stoploss_order = Mock(side_effect=create)
    bot.exchange.cancel_stoploss_order_with_result.side_effect = cancel
    position = {**bot.exchange.fetch_positions.return_value[0], "amount": 1.0}
    return bot, sync, trade, position, stops, events


def test_manual_duplicate_stops_keep_stronger_complete_protection(manual_protection):
    bot, sync, trade, position, stops, events = manual_protection
    stops.update(weak=stop("weak", stopPrice=75), strong=stop("strong", stopPrice=85))
    sync._manage_manual_stop(trade, position)
    assert events == ["cancel:weak"]
    bot.create_stoploss_order.assert_not_called()
    assert [o.order_id for o in trade.open_sl_orders] == ["strong"]


@pytest.mark.parametrize("old_amount", [0.5, 1.1])
def test_manual_stop_resized_only_after_confirmed_replacement(manual_protection, old_amount):
    _, sync, trade, position, stops, events = manual_protection
    stops["old"] = stop("old", amount=old_amount, stopPrice=85)
    sync._manage_manual_stop(trade, position)
    assert events == ["create", "cancel:old"]
    assert stops["new"]["amount"] == 1
    assert stops["new"]["stopPrice"] == 85
    assert trade.is_open


@pytest.mark.parametrize("fault", ["create", "confirm", "position_changed", "pending_entry"])
def test_manual_protection_failure_never_removes_existing_stop(manual_protection, fault):
    bot, sync, trade, position, stops, _ = manual_protection
    stops["old"] = stop("old", amount=0.5, stopPrice=85)
    if fault == "create":
        bot.create_stoploss_order.side_effect = None
        bot.create_stoploss_order.return_value = False
    elif fault == "confirm":
        original = bot.exchange.fetch_stoploss_order.side_effect
        bot.exchange.fetch_stoploss_order.side_effect = lambda oid, pair: (
            {**original(oid, pair), "status": "rejected"} if oid == "new" else original(oid, pair)
        )
    elif fault == "position_changed":
        bot.exchange.fetch_positions.return_value = []
    else:
        bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
            list(stops.values()) if kw.get("params") else [order("pending")]
        )
    with pytest.raises(ValueError):
        sync._manage_manual_stop(trade, position)
    assert stops["old"]["status"] == "open"
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()
    assert trade.is_open


def test_manual_no_stop_gets_protection_without_auto_exit(manual_protection):
    _, sync, trade, position, stops, events = manual_protection
    sync._manage_manual_stop(trade, position)
    assert events == ["create"]
    assert stops["new"]["stopPrice"] == 80
    assert trade.is_open


def test_framework_can_create_manual_stop_with_auto_exit_disabled(env):
    bot, _, _ = env
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.exchange.create_stoploss = Mock(return_value=stop("created"))
    assert FreqtradeBot.create_stoploss_order(bot, trade, 80)
    bot.exchange.create_stoploss.assert_called_once()


def test_disabling_manual_sync_restores_native_stop_management(env):
    bot, _, _ = env
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    bot.config["manual_position_sync"].update(enabled=False, manage_protective_stops=False)
    bot.exchange.create_stoploss = Mock(return_value=stop("created"))
    assert FreqtradeBot.create_stoploss_order(bot, trade, 80)


def test_protection_can_be_disabled_separately(manual_protection):
    bot, sync, trade, position, _, events = manual_protection
    bot.config["manual_position_sync"]["manage_protective_stops"] = False
    sync._manage_manual_stop(trade, position)
    assert events == []


def test_orphan_cancellation_rechecks_delayed_exchange_confirmation(env):
    bot, _, _ = env
    bot.exchange.fetch_positions.return_value = []
    bot.exchange._api.fetch_open_orders.side_effect = lambda *a, **kw: (
        [stop()] if kw.get("params") else []
    )
    bot.exchange.cancel_stoploss_order_with_result.return_value = stop(status="open")
    bot.exchange.fetch_stoploss_order.return_value = stop(status="canceled")
    twice(env)
    bot.exchange.fetch_stoploss_order.assert_called_once_with("stop", PAIR)


def test_invalid_manual_stop_triggers_emergency_sale(env):
    from freqtrade.exceptions import InvalidOrderException

    bot, _, _ = env
    trade = existing_trade(bot)
    trade.enter_tag = "manual_import"
    bot.strategy.order_types = {"stoploss_on_exchange": True}
    bot.exchange.create_stoploss = Mock(side_effect=InvalidOrderException("invalid stop"))
    bot.emergency_exit = Mock()
    assert not FreqtradeBot.create_stoploss_order(bot, trade, 80)
    bot.emergency_exit.assert_called_once_with(trade, 80)
