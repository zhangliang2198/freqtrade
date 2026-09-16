"""Production leader configuration creates leverage-aware exchange protection."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freqtrade.freqtradebot import FreqtradeBot
from freqtrade.persistence import Trade
from freqtrade.util.datetime_helpers import dt_now
from tests.strategy.leader_squeeze_test_helpers import PUBLIC_CONFIG


@pytest.mark.parametrize("leverage,short,stop", [(5, False, 80), (10, False, 90), (5, True, 120)])
@pytest.mark.parametrize("liquidation_first", [False, True])
def test_hundred_percent_margin_stop_uses_actual_leverage_and_respects_liquidation(
    leverage,
    short,
    stop,
    liquidation_first,
):
    bot = FreqtradeBot.__new__(FreqtradeBot)
    order_types = deepcopy(PUBLIC_CONFIG["order_types"])
    assert order_types["stoploss_on_exchange"] is True
    assert order_types["stoploss"] == "market"
    assert order_types["stoploss_price_type"] == "mark"
    assert PUBLIC_CONFIG["stoploss"] == -1.0
    bot.strategy = SimpleNamespace(order_types=order_types)
    bot.config = {"trailing_stop": False, "use_custom_stoploss": False}
    trade = Trade(
        pair="BTC/USDT:USDT",
        amount=2,
        open_rate=100,
        open_date=dt_now(),
        fee_open=0,
        fee_close=0,
        leverage=leverage,
        is_short=short,
        is_open=True,
    )
    trade.adjust_stop_loss(100, PUBLIC_CONFIG["stoploss"], initial=True)
    assert trade.stop_loss == pytest.approx(stop)
    if liquidation_first:
        trade.liquidation_price = stop - 1 if short else stop + 1
    trigger = trade.stoploss_or_liquidation
    side = "buy" if short else "sell"
    order = {
        "id": "protect",
        "status": "open",
        "type": "stop_market",
        "side": side,
        "amount": 2,
        "filled": 0,
        "remaining": 2,
        "price": None,
        "stopPrice": trigger,
    }
    bot.exchange = SimpleNamespace(
        create_stoploss=Mock(return_value=order),
        fetch_stoploss_order=Mock(return_value=order),
        get_option=Mock(return_value=False),
    )
    bot.update_trade_state = Mock()
    assert bot.handle_stoploss_on_exchange(trade) is False
    bot.exchange.create_stoploss.assert_called_once_with(
        pair=trade.pair,
        amount=2,
        stop_price=trigger,
        order_types=order_types,
        side=side,
        leverage=leverage,
    )
    assert trade.has_open_sl_orders
    assert trade.open_sl_orders[0].order_id == "protect"
    # The next cycle reconciles the existing stop instead of creating another.
    assert bot.handle_stoploss_on_exchange(trade) is False
    assert bot.exchange.create_stoploss.call_count == 1
    bot.update_trade_state.assert_called_once()


def test_nonblocking_futures_stop_is_kept_until_exit_fill_then_cancelled():
    from freqtrade.enums import MarginMode
    from freqtrade.persistence import Order

    bot = FreqtradeBot.__new__(FreqtradeBot)
    bot.margin_mode = MarginMode.ISOLATED
    bot.strategy = SimpleNamespace(order_filled=Mock(), use_custom_stoploss=False)
    bot.wallets = SimpleNamespace(update=Mock())
    trade = Trade(
        pair="BTC/USDT:USDT",
        amount=2,
        open_rate=100,
        open_date=dt_now(),
        leverage=5,
        fee_open=0,
        fee_close=0,
        is_open=True,
    )
    raw_stop = {
        "id": "protect",
        "status": "open",
        "type": "stop_market",
        "side": "sell",
        "amount": 2,
        "filled": 0,
        "remaining": 2,
        "price": None,
        "stopPrice": 80,
    }
    trade.orders.append(Order.parse_from_ccxt_object(raw_stop, trade.pair, "stoploss", 2, 80))
    cancelled = {**raw_stop, "status": "canceled"}
    bot.exchange = SimpleNamespace(
        get_option=Mock(return_value=False),
        cancel_stoploss_order_with_result=Mock(return_value=cancelled),
    )
    # Isolate fill/fee bookkeeping; apply the returned cancellation to the real Order.
    bot.update_trade_state = Mock(
        side_effect=lambda t, oid, order, **kwargs: t.select_order_by_order_id(
            oid
        ).update_from_ccxt_object(order)
    )
    bot.cancel_stoploss_on_exchange(trade, allow_nonblocking=True)
    bot.exchange.cancel_stoploss_order_with_result.assert_not_called()
    assert trade.has_open_sl_orders
    # Framework has now received and applied the full exit fill.
    trade.is_open = False
    exit_order = SimpleNamespace(status="closed", ft_order_side="sell")
    bot._update_trade_after_fill(trade, exit_order, send_msg=True)
    bot.exchange.cancel_stoploss_order_with_result.assert_called_once_with("protect", trade.pair, 2)
    assert not trade.has_open_sl_orders
