"""持仓明细与盈利保护状态两张表的第一列固定为从 1 开始的行号 `#`。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    _status_strategy,
)


PAIR = "BTC/USDT:USDT"
EXTERNAL_PAIR = "ETH/USDT:USDT"


def _table_rows(record) -> list[dict[str, str]]:
    table = record.strategy_log_table
    headers = [column.header for column in table.columns]
    return [
        {
            header: (cell.plain if hasattr(cell, "plain") else str(cell))
            for header, cell in zip(
                headers, [column._cells[index] for column in table.columns], strict=True
            )
        }
        for index in range(len(table.rows))
    ]


def test_holding_detail_rows_are_numbered_from_one(caplog) -> None:
    strategy = _status_strategy()
    strategy._candidate_pairs = [PAIR]
    strategy._scores = {PAIR: 80.0}
    strategy._entry_pairs = {PAIR}
    strategy._entry_decisions = {PAIR: "入选"}
    strategy._position_details = {EXTERNAL_PAIR: {"entryPrice": 2_000, "leverage": 3}}
    strategy.wallets.get_all_positions.return_value = {
        PAIR: SimpleNamespace(side="long", position=2.0, leverage=5, unrealized_pnl=1.25),
        EXTERNAL_PAIR: SimpleNamespace(side="long", position=1.0, leverage=3, unrealized_pnl=-0.5),
    }
    db_trade = SimpleNamespace(
        pair=PAIR,
        open_rate=100.0,
        leverage=5,
        stoploss_or_liquidation=90.0,
        has_open_sl_orders=True,
    )

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[db_trade]),
    ):
        strategy._log_strategy_status(1_000.0)

    record = next(record for record in caplog.records if "📦 持仓明细" in record.getMessage())
    table = record.strategy_log_table
    headers = [column.header for column in table.columns]
    assert headers[0] == "#"
    # 策略只做多单, 方向列已移除; 列数必须与表头一致, 否则 rich 会静默补空单元格。
    assert "方向" not in headers
    assert all(len(column._cells) == len(table.rows) for column in table.columns)
    rows = _table_rows(record)
    assert [row["#"] for row in rows] == ["1", "2"]
    # 行号跟着实际排序: 先按未实现盈亏从高到低。
    assert [row["交易对"] for row in rows] == [PAIR, EXTERNAL_PAIR]
    # 抽样校验列没有整体错位 (移除方向列后最容易出的错)。
    assert rows[0]["数量"] == "2.00000000"
    assert rows[0]["杠杆"] == "5"
    assert rows[0]["开仓价"] == "100.0"


def test_profit_protection_rows_are_numbered_after_sorting() -> None:
    strategy = _status_strategy()
    strategy.settings["profit_shadow_enabled"] = True
    strategy._profit_shadow = {
        "A/USDT:USDT": {"trade_id": 1},
        "B/USDT:USDT": {"trade_id": 2},
    }
    strategy._valid_profit_record = Mock(return_value=True)
    strategy._profit_position_row = Mock(
        side_effect=lambda now, pair, trade, record: (
            1.0 if pair == "A/USDT:USDT" else 2.0,
            [pair],
            "green",
        )
    )
    log_table = Mock()

    with patch.dict(
        strategy._log_profit_position_table.__func__.__globals__, {"_log_table": log_table}
    ):
        strategy._log_profit_position_table(
            1_000.0,
            {
                "A/USDT:USDT": SimpleNamespace(id=1),
                "B/USDT:USDT": SimpleNamespace(id=2),
            },
        )

    headers, rows = log_table.call_args.args[1], log_table.call_args.args[2]
    assert headers[0] == "#"
    # 没有持仓顺序时按 R 兜底: 排序键大的排前面, 行号在排序之后从 1 开始。
    assert rows == [["1", "B/USDT:USDT"], ["2", "A/USDT:USDT"]]


def test_both_tables_number_the_same_pair_identically(caplog) -> None:
    """盈利保护状态跟随持仓明细排序: 同一个交易对在两表里的 `#` 必须相同。"""
    strategy = _status_strategy()
    strategy._candidate_pairs = [PAIR]
    strategy.settings["profit_shadow_enabled"] = True
    strategy._position_details = {EXTERNAL_PAIR: {"entryPrice": 2_000, "leverage": 3}}
    strategy.wallets.get_all_positions.return_value = {
        PAIR: SimpleNamespace(side="long", position=2.0, leverage=5, unrealized_pnl=1.25),
        EXTERNAL_PAIR: SimpleNamespace(side="long", position=1.0, leverage=3, unrealized_pnl=-0.5),
    }
    trades = [
        SimpleNamespace(
            pair=PAIR,
            id=1,
            open_rate=100.0,
            leverage=5,
            stoploss_or_liquidation=90.0,
            has_open_sl_orders=True,
        ),
        SimpleNamespace(
            pair=EXTERNAL_PAIR,
            id=2,
            open_rate=2_000.0,
            leverage=3,
            stoploss_or_liquidation=1_800.0,
            has_open_sl_orders=True,
        ),
    ]
    strategy._profit_shadow = {PAIR: {"trade_id": 1}, EXTERNAL_PAIR: {"trade_id": 2}}
    strategy._valid_profit_record = Mock(return_value=True)
    # R 顺序故意与盈亏顺序相反, 证明第二张表跟的是持仓明细而不是自己的 R。
    strategy._profit_position_row = Mock(
        side_effect=lambda now, pair, trade, record: (
            1.0 if pair == PAIR else 9.0,
            [pair],
            "green",
        )
    )

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(MODULE.Trade, "get_open_trades", return_value=trades),
    ):
        strategy._log_strategy_status(1_000.0)

    holding = _table_rows(
        next(record for record in caplog.records if "📦 持仓明细" in record.getMessage())
    )
    profit = _table_rows(
        next(record for record in caplog.records if "🛡️ 盈利保护状态" in record.getMessage())
    )
    assert [row["交易对"] for row in holding] == [PAIR, EXTERNAL_PAIR]
    assert [row["交易对"] for row in profit] == [row["交易对"] for row in holding]
    assert [row["#"] for row in profit] == [row["#"] for row in holding]


def test_profit_numbering_keeps_holdings_rank_when_a_position_has_no_record(caplog) -> None:
    """没有盈利保护记录的仓位必须让后面的行跳号, 而不是整体上移一位。"""
    wallet_only = "SOL/USDT:USDT"
    strategy = _status_strategy()
    strategy._candidate_pairs = [PAIR]
    strategy.settings["profit_shadow_enabled"] = True
    strategy._position_details = {
        EXTERNAL_PAIR: {"entryPrice": 2_000, "leverage": 3},
        wallet_only: {"entryPrice": 100, "leverage": 5},
    }
    strategy.wallets.get_all_positions.return_value = {
        PAIR: SimpleNamespace(side="long", position=2.0, leverage=5, unrealized_pnl=1.25),
        EXTERNAL_PAIR: SimpleNamespace(side="long", position=1.0, leverage=3, unrealized_pnl=-0.5),
        wallet_only: SimpleNamespace(side="long", position=1.0, leverage=5, unrealized_pnl=-1.0),
    }
    # 交易所钱包里有 SOL, 但框架没有对应交易记录 -> 盈利保护表里没有它。
    trades = [
        SimpleNamespace(
            pair=PAIR,
            id=1,
            open_rate=100.0,
            leverage=5,
            stoploss_or_liquidation=90.0,
            has_open_sl_orders=True,
        ),
        SimpleNamespace(
            pair=wallet_only,
            id=3,
            open_rate=100.0,
            leverage=5,
            stoploss_or_liquidation=90.0,
            has_open_sl_orders=True,
        ),
    ]
    strategy._profit_shadow = {PAIR: {"trade_id": 1}, wallet_only: {"trade_id": 3}}
    strategy._valid_profit_record = Mock(return_value=True)
    strategy._profit_position_row = Mock(
        side_effect=lambda now, pair, trade, record: (1.0, [pair], "green")
    )

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(MODULE.Trade, "get_open_trades", return_value=trades),
    ):
        strategy._log_strategy_status(1_000.0)

    holding = _table_rows(
        next(record for record in caplog.records if "📦 持仓明细" in record.getMessage())
    )
    profit = _table_rows(
        next(record for record in caplog.records if "🛡️ 盈利保护状态" in record.getMessage())
    )
    assert [(row["#"], row["交易对"]) for row in holding] == [
        ("1", PAIR),
        ("2", EXTERNAL_PAIR),
        ("3", wallet_only),
    ]
    # SOL 没有盈利保护记录, 所以它跳过 2 号; BTC 的编号在两表里仍然是 1。
    assert [(row["#"], row["交易对"]) for row in profit] == [("1", PAIR), ("3", wallet_only)]
