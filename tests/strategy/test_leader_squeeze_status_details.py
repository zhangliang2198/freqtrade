"""Status tables expose cached heat and position details without side effects."""

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.text import Text

from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    _status_strategy,
)


PAIR = "BTC/USDT:USDT"
EXTERNAL_PAIR = "ETH/USDT:USDT"
OLD_PAIR = "OLD/USDT:USDT"
MISSING_PAIR = "MISSING/USDT:USDT"


def _plain(value: object) -> str:
    return value.plain if isinstance(value, Text) else str(value)


def _table_rows(record) -> list[dict[str, str]]:
    table = record.strategy_log_table
    headers = [column.header for column in table.columns]
    return [
        {
            header: _plain(column._cells[index])
            for header, column in zip(headers, table.columns, strict=True)
        }
        for index in range(len(table.rows))
    ]


def _status_table(caplog, title: str):
    records = [record for record in caplog.records if title in record.getMessage()]
    assert len(records) == 1
    return records[0].strategy_log_table


def test_status_tables_show_heat_price_and_opening_scores_without_side_effects(caplog) -> None:
    strategy = _status_strategy()
    strategy.settings["entry_heat_max_penalty"] = 0.20
    strategy._entry_pairs = {PAIR}
    strategy._entry_decisions = {PAIR: "入选"}
    strategy._scores = {PAIR: 80.0}
    strategy._position_details = {
        PAIR: {"markPrice": "123.45"},
        EXTERNAL_PAIR: {"entryPrice": "180.0", "markPrice": "200.0"},
    }
    strategy._last_position_sync = 900.0
    strategy.wallets.get_all_positions.return_value = {
        PAIR: SimpleNamespace(side="long", position=2.0, leverage=5, unrealized_pnl=1.25),
        EXTERNAL_PAIR: SimpleNamespace(side="long", position=1.0, leverage=3, unrealized_pnl=-0.5),
    }
    stored_trade = SimpleNamespace(
        pair=PAIR,
        open_date_utc=datetime.fromtimestamp(950, UTC),
        open_rate=100.0,
        leverage=5,
        stoploss_or_liquidation=90.0,
        has_open_sl_orders=True,
        enter_tag="squeeze_12.3",
        get_custom_data=Mock(return_value={"score": 77.7, "source": "confirmation"}),
    )
    old_tag_trade = SimpleNamespace(
        pair=OLD_PAIR,
        enter_tag="squeeze_66.6",
        open_date_utc=datetime.fromtimestamp(100, UTC),
    )
    missing_score_trade = SimpleNamespace(pair=MISSING_PAIR, enter_tag="manual_import")
    heat = Mock(
        side_effect={
            PAIR: {
                "return_15d": 0.42,
                "penalty": 0.125,
            },
            EXTERNAL_PAIR: None,
            OLD_PAIR: None,
            MISSING_PAIR: None,
        }.get
    )
    strategy._entry_heat_metrics = heat
    before = (
        strategy._entry_block_reason,
        strategy._entry_pairs.copy(),
        strategy._entry_decisions.copy(),
        strategy._scores.copy(),
    )

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(
            MODULE.Trade,
            "get_open_trades",
            return_value=[stored_trade, old_tag_trade, missing_score_trade],
        ),
    ):
        strategy._log_strategy_status(1_000.0)

    selection_table = _status_table(caplog, "📊 评分综合明细")
    selection = {
        row["交易对"]: row
        for row in _table_rows(
            next(record for record in caplog.records if "📊 评分综合明细" in record.getMessage())
        )
    }
    assert selection[PAIR]["15日涨幅"] == "+42.0%"
    assert selection[PAIR]["热度折扣"] == "12.5%"
    assert selection[PAIR]["买入评分"] == "70.0"
    assert selection_table.columns[0].header == "排名"

    holding_record = next(
        record for record in caplog.records if "📦 持仓明细" in record.getMessage()
    )
    holding_table = holding_record.strategy_log_table
    holding_rows = _table_rows(holding_record)
    holding = {row["交易对"]: row for row in holding_rows}
    assert [row["交易对"] for row in holding_rows] == [
        PAIR,
        EXTERNAL_PAIR,
        MISSING_PAIR,
        OLD_PAIR,
    ]
    assert holding[PAIR]["15日涨幅"] == "+42.0%"
    assert holding[PAIR]["热度折扣"] == "12.5%"
    assert holding[PAIR]["当前价(标记)"] == "123.45(旧)"
    assert holding[PAIR]["本金(USDT)"] == "40.00"
    assert holding[PAIR]["当前涨幅(含杠杆)"] == "+117.2%(旧)"
    assert holding[PAIR]["开仓分数"] == "77.7"
    assert holding[EXTERNAL_PAIR]["当前价(标记)"] == "200(旧)"
    assert holding[EXTERNAL_PAIR]["本金(USDT)"] == "60.00"
    assert holding[EXTERNAL_PAIR]["当前涨幅(含杠杆)"] == "+33.3%(旧)"
    assert holding[EXTERNAL_PAIR]["开仓分数"] == "未记录"
    assert holding[OLD_PAIR]["开仓分数"] == "66.6(标签)"
    assert holding[MISSING_PAIR]["开仓分数"] == "未记录"
    assert holding[PAIR]["框架对账"] == "已跟踪"
    assert holding[PAIR]["持仓时间"] == "50秒"
    assert holding[OLD_PAIR]["持仓时间"] == "15分钟"
    assert holding[MISSING_PAIR]["持仓时间"] == "未知"
    assert holding[EXTERNAL_PAIR]["持仓时间"] == "未知"
    assert holding[OLD_PAIR]["框架对账"] == "已跟踪"
    assert holding[MISSING_PAIR]["框架对账"] == "已接管"
    assert holding[EXTERNAL_PAIR]["框架对账"] == "等待框架导入"
    assert holding[EXTERNAL_PAIR]["15日涨幅"] == "未知"
    assert holding[EXTERNAL_PAIR]["热度折扣"] == "未知"
    assert holding[MISSING_PAIR]["15日涨幅"] == "未知"
    assert holding[MISSING_PAIR]["热度折扣"] == "未知"
    assert all(
        value != "0.0%"
        for row in holding.values()
        for key, value in row.items()
        if key in {"15日涨幅", "热度折扣"} and row["交易对"] in {EXTERNAL_PAIR, MISSING_PAIR}
    )

    expected_headers = [
        "交易对",
        "来源",
        "方向",
        "数量",
        "杠杆",
        "开仓价",
        "当前价(标记)",
        "本金(USDT)",
        "当前涨幅(含杠杆)",
        "未实现盈亏(USDT)",
        "策略止损价",
        "开仓分数",
        "热度折扣",
        "15日涨幅",
        "交易所止损记录",
        "框架对账",
        "1h趋势",
        "4h背景",
        "持仓时间",
    ]
    assert [column.header for column in holding_table.columns] == expected_headers
    assert all(len(column._cells) == len(holding_table.rows) for column in holding_table.columns)

    assert strategy._entry_block_reason == before[0]
    assert strategy._entry_pairs == before[1]
    assert strategy._entry_decisions == before[2]
    assert strategy._scores == before[3]
    assert strategy.dp._exchange.mock_calls == []
    assert heat.call_count >= 4


def test_leveraged_return_uses_position_direction() -> None:
    strategy = _status_strategy()

    assert strategy._leveraged_return_label(100, 110, 5, "long", stale=False) == "+50.0%"
    assert strategy._leveraged_return_label(100, 90, 5, "short", stale=False) == "+50.0%"
    assert strategy._leveraged_return_label(100, 90, 5, "long", stale=True) == "-50.0%(旧)"
    assert strategy._leveraged_return_label(0, 90, 5, "long", stale=False) == "未知"


def test_holding_duration_uses_readable_largest_units() -> None:
    label = MODULE.LeaderSqueezeStrategy._holding_duration_label
    now = datetime(2026, 1, 3, 3, 4, 59, tzinfo=UTC).timestamp()

    assert label(datetime.fromtimestamp(now - 9, UTC), now) == "9秒"
    assert label(datetime.fromtimestamp(now - 59 * 60 - 59, UTC), now) == "59分钟"
    assert label(datetime.fromtimestamp(now - (3 * 3600 + 4 * 60 + 59), UTC), now) == "3时4分"
    assert label(datetime.fromtimestamp(now - (2 * 86400 + 3 * 3600 + 4 * 60), UTC), now) == (
        "2天3时4分"
    )
    assert label(datetime.fromtimestamp(now + 30, UTC), now) == "0秒"
    assert label(None, now) == "未知"


def test_position_principal_prefers_trade_then_exchange_margin_then_calculation() -> None:
    strategy = _status_strategy()
    trade = SimpleNamespace(stake_amount=75.0)
    position = SimpleNamespace(position=2.0, collateral=60.0)

    assert strategy._position_principal_label(trade, position, 200, 4) == "75.00"
    assert strategy._position_principal_label(None, position, 200, 4) == "60.00"
    position = SimpleNamespace(position=2.0, collateral=0)
    assert strategy._position_principal_label(None, position, 200, 4) == "100.00"
    assert strategy._position_principal_label(None, position, 200, 0) == "未知"
