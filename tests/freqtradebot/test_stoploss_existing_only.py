from freqtrade.enums import ExitType
from freqtrade.persistence import Order, Trade
from tests.conftest import get_patched_freqtradebot


_STOPLOSS_ID = "existing-stoploss"
_STOPLOSS_PRICE = 1.8


def _existing_stoploss_order(trade: Trade) -> Order:
    return Order(
        ft_order_side="stoploss",
        ft_pair=trade.pair,
        ft_is_open=True,
        ft_amount=trade.amount,
        ft_price=_STOPLOSS_PRICE,
        order_id=_STOPLOSS_ID,
        status="open",
        symbol=trade.pair,
        order_type="stop_loss_limit",
        side=trade.exit_side,
        price=_STOPLOSS_PRICE,
        average=_STOPLOSS_PRICE,
        filled=0.0,
        remaining=trade.amount,
        cost=_STOPLOSS_PRICE * trade.amount,
        order_date=trade.open_date,
    )


def _stoploss_response(trade: Trade, status: str) -> dict:
    closed = status == "closed"
    return {
        "id": _STOPLOSS_ID,
        "status": status,
        "symbol": trade.pair,
        "type": "stop_loss_limit",
        "side": trade.exit_side,
        "price": _STOPLOSS_PRICE,
        "average": _STOPLOSS_PRICE,
        "amount": trade.amount,
        "filled": trade.amount if closed else 0.0,
        "remaining": 0.0 if closed else trade.amount,
    }


def _disabled_bot_with_trade(mocker, default_conf_usdt, open_trade_usdt, with_stoploss: bool):
    freqtrade = get_patched_freqtradebot(mocker, default_conf_usdt)
    freqtrade.strategy.order_types["stoploss_on_exchange"] = False

    trade = open_trade_usdt
    trade.orders = [trade.orders[0]]
    trade.stop_loss = _STOPLOSS_PRICE
    trade.fee_open_currency = None
    trade.fee_close_currency = None
    if with_stoploss:
        trade.orders.append(_existing_stoploss_order(trade))
    Trade.session.add(trade)
    Trade.commit()

    mocker.patch.object(freqtrade.exchange, "get_trades_for_order", return_value=[])
    mocker.patch.object(freqtrade.wallets, "check_exit_amount", return_value=True)
    mocker.patch.object(freqtrade, "handle_trade", return_value=False)
    return freqtrade, trade


def test_disabled_stoploss_keeps_existing_open_order(mocker, default_conf_usdt, open_trade_usdt):
    freqtrade, trade = _disabled_bot_with_trade(
        mocker, default_conf_usdt, open_trade_usdt, with_stoploss=True
    )
    fetch_stoploss = mocker.patch.object(
        freqtrade.exchange,
        "fetch_stoploss_order",
        return_value=_stoploss_response(trade, "open"),
    )
    create_stoploss = mocker.patch.object(freqtrade, "create_stoploss_order", return_value=False)
    trail_stoploss = mocker.patch.object(freqtrade, "handle_trailing_stoploss_on_exchange")
    freqtrade.config["trailing_stop"] = True

    assert freqtrade.exit_positions([trade]) == 0
    fetch_stoploss.assert_called_once_with(_STOPLOSS_ID, trade.pair)
    assert trade.has_open_sl_orders
    assert trade.open_sl_orders[0].status == "open"
    create_stoploss.assert_not_called()
    trail_stoploss.assert_not_called()


def test_disabled_stoploss_does_not_recreate_canceled_order(
    mocker, default_conf_usdt, open_trade_usdt
):
    freqtrade, trade = _disabled_bot_with_trade(
        mocker, default_conf_usdt, open_trade_usdt, with_stoploss=True
    )
    mocker.patch.object(
        freqtrade.exchange,
        "fetch_stoploss_order",
        return_value=_stoploss_response(trade, "canceled"),
    )
    create_stoploss = mocker.patch.object(freqtrade, "create_stoploss_order", return_value=False)

    assert freqtrade.exit_positions([trade]) == 0
    assert not trade.has_open_sl_orders
    assert trade.is_open
    create_stoploss.assert_not_called()


def test_disabled_stoploss_still_syncs_closed_order(mocker, default_conf_usdt, open_trade_usdt):
    freqtrade, trade = _disabled_bot_with_trade(
        mocker, default_conf_usdt, open_trade_usdt, with_stoploss=True
    )
    mocker.patch.object(
        freqtrade.exchange,
        "fetch_stoploss_order",
        return_value=_stoploss_response(trade, "closed"),
    )
    create_stoploss = mocker.patch.object(freqtrade, "create_stoploss_order", return_value=False)

    assert freqtrade.exit_positions([trade]) == 1
    assert not trade.is_open
    assert trade.exit_reason == ExitType.STOPLOSS_ON_EXCHANGE.value
    create_stoploss.assert_not_called()


def test_disabled_stoploss_does_not_create_without_existing_order(
    mocker, default_conf_usdt, open_trade_usdt
):
    freqtrade, trade = _disabled_bot_with_trade(
        mocker, default_conf_usdt, open_trade_usdt, with_stoploss=False
    )
    fetch_stoploss = mocker.patch.object(freqtrade.exchange, "fetch_stoploss_order")
    create_stoploss = mocker.patch.object(freqtrade, "create_stoploss_order", return_value=False)

    assert freqtrade.exit_positions([trade]) == 0
    assert not trade.has_open_sl_orders
    fetch_stoploss.assert_not_called()
    create_stoploss.assert_not_called()
