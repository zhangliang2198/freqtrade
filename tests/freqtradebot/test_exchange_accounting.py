from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from freqtrade.exchange_accounting import KEY, ExchangeAccounting
from freqtrade.persistence import Trade
from tests.freqtradebot.test_manual_position_sync import (
    NOW,
    PAIR,
    env,  # noqa: F401
    existing_trade,
    order,
)


@pytest.fixture
def ledger(request):
    bot, _, clock = request.getfixturevalue("env")
    bot.config[KEY] = {
        "enabled": True,
        "interval_seconds": 900,
        "overlap_seconds": 120,
        "settlement_delay_seconds": 120,
        "initial_lookback_days": 7,
        "page_size": 1000,
        "max_pages_per_trade": 30,
        "batch_size": 3,
    }
    bot.exchange.markets = {PAIR: {"id": "BTCUSDT", "linear": True, "settle": "USDT"}}
    bot.exchange._api.fapiPrivateGetUserTrades = Mock(return_value=[])
    bot.exchange._api.fapiPrivateGetIncome = Mock(return_value=[])
    trade = existing_trade(bot)
    trade.open_date = datetime.fromtimestamp(NOW - 1000, UTC)
    trade.orders[0].order_date = trade.open_date
    trade.orders[0].order_filled_date = trade.open_date
    Trade.commit()
    clock[0] = NOW
    return bot, ExchangeAccounting(bot), trade, clock


def fill(
    fid="1",
    oid="entry",
    side="BUY",
    quantity="1",
    price="100",
    fee="0.1",
    pnl="0",
    stamp=NOW - 1000,
):
    return {
        "id": fid,
        "orderId": oid,
        "symbol": "BTCUSDT",
        "side": side,
        "qty": quantity,
        "price": price,
        "commission": fee,
        "commissionAsset": "USDT",
        "realizedPnl": pnl,
        "positionSide": "BOTH",
        "time": int(stamp * 1000),
    }


def funding(tid="f1", amount="-0.2", stamp=NOW - 500):
    return {
        "tranId": tid,
        "symbol": "BTCUSDT",
        "incomeType": "FUNDING_FEE",
        "asset": "USDT",
        "income": amount,
        "time": int(stamp * 1000),
    }


def close_trade(trade):
    from freqtrade.persistence import Order

    trade.orders.append(
        Order.parse_from_ccxt_object(
            order("exit", "sell", price=110, stamp=NOW - 200), PAIR, "sell"
        )
    )
    trade.close(110)
    trade.close_date = datetime.fromtimestamp(NOW - 200, UTC)
    Trade.commit()


def test_actual_cash_ledger_corrects_closed_performance_without_double_fees(ledger):
    bot, accounting, trade, _ = ledger
    close_trade(trade)
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [
        fill(),
        fill("2", "exit", "SELL", price="110", fee="0.11", pnl="10", stamp=NOW - 200),
    ]
    bot.exchange._api.fapiPrivateGetIncome.return_value = [funding(), funding()]
    accounting.reconcile(trade, NOW)
    assert trade.close_profit_abs == pytest.approx(9.59)
    expected_stake = trade._calc_open_trade_value(1, 100)
    assert trade.close_profit == pytest.approx(9.59 / expected_stake * trade.leverage)
    assert trade.funding_fees == -0.2
    assert Trade.get_overall_performance()[0]["profit_abs"] == pytest.approx(9.59)
    data = accounting.state(trade)
    assert data["status"] == "verified"
    assert len(accounting._records(trade, "funding")) == 1


def test_verified_ledger_profit_can_be_restored_after_fee_recalculation(ledger):
    bot, accounting, trade, _ = ledger
    close_trade(trade)
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [
        fill(),
        fill("2", "exit", "SELL", price="110", fee="0.11", pnl="10", stamp=NOW - 200),
    ]
    bot.exchange._api.fapiPrivateGetIncome.return_value = [funding()]
    accounting.reconcile(trade, NOW)
    expected = (
        trade.close_profit_abs,
        trade.close_profit,
        trade.realized_profit,
        trade.funding_fees,
    )
    trade.close_profit_abs = 1
    trade.close_profit = 2
    trade.realized_profit = 3
    trade.funding_fees = 4
    Trade.commit()

    assert accounting.restore_verified_profit(trade)
    assert (
        trade.close_profit_abs,
        trade.close_profit,
        trade.realized_profit,
        trade.funding_fees,
    ) == expected


def test_incremental_cursor_survives_restart_and_deduplicates_overlap(ledger):
    bot, accounting, trade, _ = ledger
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    bot.exchange._api.fapiPrivateGetIncome.return_value = [funding(stamp=NOW - 150)]
    accounting.reconcile(trade, NOW)
    cursor = accounting.state(trade)["cursor_ms"]
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = []
    restarted = ExchangeAccounting(bot)
    restarted.reconcile(trade, NOW + 900)
    request = bot.exchange._api.fapiPrivateGetUserTrades.call_args.args[0]
    assert request["startTime"] == cursor - 120000
    assert len(accounting._records(trade, "funding")) == 1
    assert accounting.state(trade)["net_profit"] == pytest.approx(-0.3)


@pytest.mark.parametrize(
    "fault", ["missing_fill", "unknown_order", "wrong_currency", "wrong_symbol", "nan", "hedged"]
)
def test_incomplete_evidence_never_overwrites_profit_or_advances_cursor(ledger, fault):
    bot, accounting, trade, _ = ledger
    close_trade(trade)
    before = trade.close_profit_abs
    rows = [fill(), fill("2", "exit", "SELL", price="110", pnl="10", stamp=NOW - 200)]
    if fault == "missing_fill":
        rows.pop()
    elif fault == "unknown_order":
        rows[0]["orderId"] = "untracked"
    elif fault == "wrong_currency":
        rows[0]["commissionAsset"] = "BNB"
    elif fault == "wrong_symbol":
        rows[0]["symbol"] = "ETHUSDT"
    elif fault == "nan":
        rows[0]["realizedPnl"] = "NaN"
    else:
        rows[0]["positionSide"] = "LONG"
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = rows
    accounting.run()
    assert trade.close_profit_abs == before
    state = accounting.state(trade)
    assert state["status"] == "pending"
    assert "cursor_ms" not in state


def test_full_pages_are_split_and_all_fills_are_counted_once(ledger):
    bot, accounting, trade, _ = ledger
    accounting.settings["page_size"] = 2
    rows = [
        fill("1", quantity="0.5", fee="0.05"),
        fill("2", quantity="0.5", fee="0.05", stamp=NOW - 900),
    ]
    bot.exchange._api.fapiPrivateGetUserTrades.side_effect = lambda req: [
        row for row in rows if req["startTime"] <= row["time"] <= req["endTime"]
    ][:2]
    accounting.reconcile(trade, NOW)
    assert len(accounting._records(trade, "fill")) == 2
    assert accounting.state(trade)["actual_commission"] == 0.1
    assert bot.exchange._api.fapiPrivateGetUserTrades.call_count > 1


def test_page_budget_failure_does_not_advance_cursor(ledger):
    bot, accounting, trade, _ = ledger
    accounting.settings.update(page_size=1, max_pages_per_trade=1)
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    accounting.run()
    assert "cursor_ms" not in accounting.state(trade)


def test_closed_verified_trade_does_not_refetch_entire_history(ledger):
    bot, accounting, trade, clock = ledger
    close_trade(trade)
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [
        fill(),
        fill("2", "exit", "SELL", price="110", fee="0.11", pnl="10", stamp=NOW - 200),
    ]
    accounting.run()
    bot.exchange._api.fapiPrivateGetUserTrades.reset_mock()
    clock[0] += 901
    ExchangeAccounting(bot).run()
    bot.exchange._api.fapiPrivateGetUserTrades.assert_not_called()


def test_funding_overlapping_another_trade_is_not_guessed(ledger):
    bot, accounting, trade, _ = ledger
    other = Trade(
        pair=PAIR,
        amount=1,
        open_rate=100,
        stake_amount=20,
        fee_open=0,
        fee_close=0,
        exchange="binance",
        is_open=True,
        open_date=datetime.fromtimestamp(NOW - 700, UTC),
    )
    Trade.session.add(other)
    Trade.commit()
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    bot.exchange._api.fapiPrivateGetIncome.return_value = [funding()]
    with pytest.raises(ValueError, match="overlaps"):
        accounting.reconcile(trade, NOW)


def test_dry_run_accounting_never_reads_private_exchange(ledger):
    bot, accounting, _, _ = ledger
    bot.config["dry_run"] = True
    accounting.run()
    bot.exchange._api.fapiPrivateGetUserTrades.assert_not_called()


def test_out_of_window_open_trade_is_recorded_once(ledger, monkeypatch, caplog):
    bot, accounting, trade, _ = ledger
    now = [NOW]
    monkeypatch.setattr("freqtrade.exchange_accounting.time.time", lambda: now[0])
    opened = datetime.fromtimestamp(NOW - 8 * 86400, UTC)
    trade.open_date = opened
    trade.orders[0].order_date = opened
    trade.orders[0].order_filled_date = opened
    Trade.commit()

    accounting.run()
    state = accounting.state(trade)
    assert state["status"] == "out_of_window"
    assert state["lookback_days"] == 7
    assert "cursor_ms" not in state

    now[0] += 901
    accounting.run()
    assert (
        sum("Exchange ledger outside initial lookback" in message for message in caplog.messages)
        == 1
    )
    bot.exchange._api.fapiPrivateGetUserTrades.assert_not_called()


def test_failed_commit_rolls_back_profit_evidence_and_cursor(ledger, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    bot, accounting, trade, _ = ledger
    close_trade(trade)
    before = trade.close_profit_abs
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [
        fill(),
        fill("2", "exit", "SELL", price="110", pnl="10", stamp=NOW - 200),
    ]
    commit = Trade.commit
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            Trade.session.flush()
            raise SQLAlchemyError("simulated failure after flush")
        commit()

    monkeypatch.setattr(Trade, "commit", fail_once)
    accounting.run()
    assert trade.close_profit_abs == before
    assert accounting._records(trade, "fill") == {}
    assert "cursor_ms" not in accounting.state(trade)
    assert accounting.state(trade)["status"] == "pending"


def test_deleting_trade_removes_its_ledger(ledger):
    from sqlalchemy import select

    from freqtrade.persistence import ExchangeLedger

    bot, accounting, trade, _ = ledger
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    accounting.reconcile(trade, NOW)
    trade_id = trade.id
    assert len(accounting._records(trade, "fill")) == 1
    trade.delete()
    assert not Trade.session.scalars(
        select(ExchangeLedger).where(ExchangeLedger.trade_id == trade_id)
    ).all()


def test_recent_fills_wait_for_ledger_settlement(ledger):
    bot, accounting, trade, _ = ledger
    trade.orders[0].order_filled_date = datetime.fromtimestamp(NOW - 10, UTC)
    accounting.run()
    bot.exchange._api.fapiPrivateGetUserTrades.assert_not_called()
    assert accounting.state(trade) == {}


@pytest.mark.parametrize(
    "name,value",
    [
        ("interval_seconds", 0),
        ("interval_seconds", True),
        ("overlap_seconds", 901),
        ("settlement_delay_seconds", -1),
        ("page_size", 1001),
        ("batch_size", 0),
    ],
)
def test_invalid_accounting_config_is_rejected(ledger, name, value):
    from freqtrade.exceptions import OperationalException

    bot, _, _, _ = ledger
    bot.config[KEY][name] = value
    with pytest.raises(OperationalException):
        ExchangeAccounting(bot)


def test_trade_created_after_exchange_fill_does_not_lose_opening_fee(ledger):
    from datetime import timedelta

    bot, accounting, trade, _ = ledger
    trade.open_date += timedelta(milliseconds=400)
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    accounting.reconcile(trade, NOW)
    req = bot.exchange._api.fapiPrivateGetUserTrades.call_args.args[0]
    assert req["startTime"] == int((NOW - 1000) * 1000)
    assert accounting.state(trade)["actual_commission"] == 0.1


def test_batch_delay_does_not_turn_fifteen_minute_sync_into_thirty(ledger):
    bot, accounting, trade, clock = ledger
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = [fill()]
    accounting.reconcile(trade, NOW)
    state = accounting.state(trade)
    state["checked_at"] = NOW + 30  # Later trades finish after the round's start timestamp.
    accounting._save(trade, state)
    Trade.commit()
    accounting.last_run = NOW
    clock[0] = NOW + 901
    bot.exchange._api.fapiPrivateGetUserTrades.reset_mock()
    bot.exchange._api.fapiPrivateGetUserTrades.return_value = []
    accounting.run()
    bot.exchange._api.fapiPrivateGetUserTrades.assert_called_once()


def test_initial_history_is_collected_one_seven_day_chunk_per_round(ledger):
    bot, accounting, trade, _ = ledger
    accounting.settings["initial_lookback_days"] = 30
    opened = datetime.fromtimestamp(NOW - 15 * 86400, UTC)
    trade.open_date = opened
    trade.orders[0].order_date = opened
    trade.orders[0].order_filled_date = opened
    Trade.commit()

    accounting.reconcile(trade, NOW)

    request = bot.exchange._api.fapiPrivateGetUserTrades.call_args.args[0]
    assert request["endTime"] - request["startTime"] < 7 * 86400 * 1000
    assert accounting.state(trade)["status"] == "collecting"
    assert accounting.state(trade)["cursor_ms"] == request["endTime"]
