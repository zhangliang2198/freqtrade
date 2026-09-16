"""Status tables expose cached heat and position details without side effects."""

import logging
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
        EXTERNAL_PAIR: {"markPrice": "200.0"},
    }
    strategy._last_position_sync = 900.0
    strategy.wallets.get_all_positions.return_value = {
        PAIR: SimpleNamespace(side="long", position=2.0, leverage=5, unrealized_pnl=1.25),
        EXTERNAL_PAIR: SimpleNamespace(side="long", position=1.0, leverage=3, unrealized_pnl=-0.5),
    }
    stored_trade = SimpleNamespace(
        pair=PAIR,
        open_rate=100.0,
        leverage=5,
        stoploss_or_liquidation=90.0,
        has_open_sl_orders=True,
        enter_tag="squeeze_12.3",
        get_custom_data=Mock(return_value={"score": 77.7, "source": "confirmation"}),
    )
    old_tag_trade = SimpleNamespace(pair=OLD_PAIR, enter_tag="squeeze_66.6")
    missing_score_trade = SimpleNamespace(pair=MISSING_PAIR, enter_tag=None)
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

    selection_table = _status_table(caplog, "🎯 选币结果")
    selection = {
        row["交易对"]: row
        for row in _table_rows(
            next(record for record in caplog.records if "🎯 选币结果" in record.getMessage())
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
    holding = {row["交易对"]: row for row in _table_rows(holding_record)}
    assert holding[PAIR]["15日涨幅"] == "+42.0%"
    assert holding[PAIR]["热度折扣"] == "12.5%"
    assert holding[PAIR]["当前价(标记)"] == "123.45(旧)"
    assert holding[PAIR]["开仓分数"] == "77.7"
    assert holding[EXTERNAL_PAIR]["当前价(标记)"] == "200(旧)"
    assert holding[EXTERNAL_PAIR]["开仓分数"] == "未记录"
    assert holding[OLD_PAIR]["开仓分数"] == "66.6(标签)"
    assert holding[MISSING_PAIR]["开仓分数"] == "未记录"
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
        "开仓分数",
        "15日涨幅",
        "热度折扣",
        "未实现盈亏(USDT)",
        "策略止损价",
        "交易所止损记录",
        "外部风控",
        "1h趋势",
        "4h背景",
    ]
    assert [column.header for column in holding_table.columns] == expected_headers
    assert all(len(column._cells) == len(holding_table.rows) for column in holding_table.columns)

    assert strategy._entry_block_reason == before[0]
    assert strategy._entry_pairs == before[1]
    assert strategy._entry_decisions == before[2]
    assert strategy._scores == before[3]
    assert strategy.dp._exchange.mock_calls == []
    assert heat.call_count >= 4
