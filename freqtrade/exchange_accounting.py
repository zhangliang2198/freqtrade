"""Incremental exchange cash-ledger reconciliation for tracked Binance futures trades.

This module never submits/cancels orders. Only fully reconciled closed trades have
their reported PnL corrected; incomplete evidence leaves the existing figures intact.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from freqtrade.enums import TradingMode
from freqtrade.exceptions import OperationalException
from freqtrade.manual_position_sync import ManualPositionSync
from freqtrade.persistence import ExchangeLedger, Trade


if TYPE_CHECKING:
    from freqtrade.freqtradebot import FreqtradeBot

logger = logging.getLogger(__name__)
KEY = "exchange_accounting"
DAY_MS = 86_400_000


def money(value: Any) -> Decimal:
    """Convert an exchange amount to a finite :class:`Decimal`."""
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("non-finite ledger amount")
    return result


class ExchangeAccounting:
    """Reconcile local futures trades against Binance cash-ledger evidence."""

    def __init__(self, bot: FreqtradeBot):
        self.bot = bot
        self.settings = bot.config.get(KEY, {})
        self.enabled = self.settings.get("enabled", False)
        self.last_run = -math.inf
        self.pending: deque[int] = deque()
        if type(self.enabled) is not bool:
            raise OperationalException("exchange_accounting.enabled must be boolean")
        if not self.enabled:
            return
        bounds = {
            "interval_seconds": (60, 86400),
            "overlap_seconds": (1, 3600),
            "settlement_delay_seconds": (1, 3600),
            "initial_lookback_days": (1, 89),
            "page_size": (1, 1000),
            "max_pages_per_trade": (1, 200),
            "batch_size": (1, 20),
        }
        for name, (low, high) in bounds.items():
            value = self.settings.get(name)
            if type(value) is not int or not low <= value <= high:
                raise OperationalException(f"exchange_accounting.{name} must be in [{low}, {high}]")
        if self.settings["overlap_seconds"] > self.settings["interval_seconds"]:
            raise OperationalException("exchange_accounting overlap must not exceed interval")
        if bot.exchange.id != "binance" or bot.trading_mode != TradingMode.FUTURES:
            raise OperationalException("exchange_accounting supports Binance linear futures only")

    @staticmethod
    def _records(trade: Trade, kind: str) -> dict:
        rows = Trade.session.scalars(
            select(ExchangeLedger).where(
                ExchangeLedger.trade_id == trade.id, ExchangeLedger.record_type == kind
            )
        ).all()
        return {row.record_id: dict(row.data) for row in rows}

    def state(self, trade: Trade) -> dict:
        """Return the latest persisted reconciliation checkpoint for ``trade``."""
        return self._records(trade, "checkpoint").get(str(trade.id), {})

    def restore_verified_profit(self, trade: Trade) -> bool:
        """Restore authoritative ledger PnL after a framework order recalculation."""
        state = self.state(trade)
        if (
            trade.is_open
            or state.get("status") != "verified"
            or state.get("signature") != self._signature(trade)
        ):
            return False
        required = ("net_profit", "actual_funding", "profit_ratio")
        if any(key not in state for key in required):
            return False
        trade.close_profit_abs = float(state["net_profit"])
        trade.realized_profit = float(state["net_profit"])
        trade.close_profit = float(state["profit_ratio"])
        trade.funding_fees = float(state["actual_funding"])
        Trade.commit()
        return True

    def _trade_write_lock(self):
        """Serialize short database updates with RPC exits; exchange reads stay outside."""
        return getattr(self.bot, "_exit_lock", None) or nullcontext()

    @staticmethod
    def _save(trade: Trade, state: dict, fills: dict | None = None, funding: dict | None = None):
        rows = Trade.session.scalars(
            select(ExchangeLedger).where(ExchangeLedger.trade_id == trade.id)
        ).all()
        known = {(row.record_type, row.record_id): row for row in rows}
        for kind, records in (
            ("fill", fills or {}),
            ("funding", funding or {}),
            ("checkpoint", {str(trade.id): state}),
        ):
            for record_id, data in records.items():
                row = known.get((kind, record_id))
                if row is None:
                    row = ExchangeLedger(
                        trade_id=trade.id,
                        exchange=trade.exchange,
                        pair=trade.pair,
                        record_type=kind,
                        record_id=record_id,
                    )
                    Trade.session.add(row)
                row.timestamp = int(data.get("time", state.get("cursor_ms", 0)))
                row.data = dict(data)
        # Caller commits evidence, cursor and corrected Trade PnL together.

    @staticmethod
    def _signature(trade: Trade) -> list:
        return [
            trade.is_open,
            trade.leverage,
            [
                [o.order_id, o.ft_order_side, o.safe_filled, o.safe_price, o.ft_is_open]
                for o in trade.orders
            ],
        ]

    def run(self) -> None:
        """Reconcile a bounded batch when the configured interval has elapsed."""
        if not self.enabled or self.bot.config["dry_run"]:
            return
        now = time.time()
        if not self.pending:
            if 0 <= now - self.last_run < self.settings["interval_seconds"]:
                return
            self.last_run = now
            since = datetime.fromtimestamp(now, UTC) - timedelta(
                days=self.settings["initial_lookback_days"]
            )
            trades = Trade.get_trades(
                [
                    Trade.trading_mode == TradingMode.FUTURES,
                    Trade.exchange == self.bot.exchange.id,
                    or_(Trade.is_open.is_(True), Trade.close_date >= since),
                ]
            ).all()
            self.pending.extend(trade.id for trade in trades)
        for _ in range(min(len(self.pending), self.settings["batch_size"])):
            trade = Trade.get_trades([Trade.id == self.pending.popleft()]).first()
            if trade is None:
                continue
            state = self.state(trade)
            if (
                state.get("status") == "out_of_window"
                and state.get("signature") == self._signature(trade)
                and state.get("lookback_days") == self.settings["initial_lookback_days"]
            ):
                continue
            if (
                not trade.is_open
                and state.get("status") == "verified"
                and state.get("signature") == self._signature(trade)
                and trade.close_profit_abs == state.get("net_profit")
            ):
                continue
            try:
                self.reconcile(trade, now)
            except Exception as exc:
                with self._trade_write_lock():
                    Trade.rollback()
                    current = Trade.get_trades([Trade.id == trade.id]).first()
                    if current is None:
                        continue
                    # Keep prior committed chunks. Failure must never skip a time window.
                    state = self.state(current)
                    state.update(
                        status="pending",
                        checked_at=now,
                        reason=ManualPositionSync._error_reason(exc),
                    )
                    self._save(current, state)
                    Trade.commit()
                logger.warning(
                    "Exchange ledger pending %s trade=%s | %s | preserving prior statistics "
                    "and incremental progress",
                    trade.pair,
                    trade.id,
                    state["reason"],
                )

    def _fetch(self, method, symbol: str, start: int, end: int, budget: list[int], **extra) -> list:
        """Split full pages by time rather than silently truncate or lose same-ms fills."""
        if start > end:
            return []
        if budget[0] <= 0:
            raise ValueError("ledger page budget exhausted")
        budget[0] -= 1
        rows = method(
            {
                "symbol": symbol,
                "startTime": start,
                "endTime": end,
                "limit": self.settings["page_size"],
                **extra,
            }
        )
        if not isinstance(rows, list):
            raise ValueError("invalid ledger response")
        if len(rows) >= self.settings["page_size"]:
            if start == end:
                raise ValueError("ledger millisecond page may be truncated")
            middle = (start + end) // 2
            return self._fetch(method, symbol, start, middle, budget, **extra) + self._fetch(
                method, symbol, middle + 1, end, budget, **extra
            )
        return rows

    def _collect(self, symbol: str, start: int, end: int) -> tuple[list, list]:
        api = self.bot.exchange._api
        fills, funding = [], []
        budget = [self.settings["max_pages_per_trade"]]
        while start <= end:
            stop = min(end, start + 7 * DAY_MS - 1)
            fills.extend(self._fetch(api.fapiPrivateGetUserTrades, symbol, start, stop, budget))
            funding.extend(
                self._fetch(
                    api.fapiPrivateGetIncome, symbol, start, stop, budget, incomeType="FUNDING_FEE"
                )
            )
            start = stop + 1
        return fills, funding

    def _filled_order_ids(self, trade: Trade) -> dict[str, Any]:
        result = {}
        for order in trade.orders:
            if not order.safe_filled:
                continue
            if order.ft_is_open:
                raise ValueError("order fill still pending")
            oid = order.order_id
            if order.ft_order_side == "stoploss":
                raw = self.bot.exchange.fetch_stoploss_order(oid, trade.pair)
                oid = str(raw.get("id_stop") or oid)
            if oid in result:
                raise ValueError("execution order is assigned twice")
            result[oid] = order
        if not result:
            raise ValueError("no confirmed fills")
        return result

    @staticmethod
    def _opening_ms(trade: Trade) -> int:
        # Local Trade creation can follow the exchange fill by several hundred milliseconds.
        dates = [trade.open_date_utc]
        for order in trade.orders:
            if order.safe_filled and order.ft_order_side == trade.entry_side:
                dates.append(order.order_date_utc)
                if order.order_filled_utc:
                    dates.append(order.order_filled_utc)
        return int(min(dates).timestamp() * 1000)

    def reconcile(self, trade: Trade, now: float) -> None:
        """Incrementally reconcile one trade from exchange ledger evidence."""
        market = self.bot.exchange.markets[trade.pair]
        if not market.get("linear") or market.get("settle") != trade.stake_currency:
            raise ValueError("unsupported ledger market")
        state = self.state(trade)
        start = self._opening_ms(trade)
        end = int((now - self.settings["settlement_delay_seconds"]) * 1000)
        if not trade.is_open:
            end = min(end, int(trade.close_date_utc.timestamp() * 1000))
        if start < (now - self.settings["initial_lookback_days"] * 86400) * 1000 and not state.get(
            "cursor_ms"
        ):
            state.update(
                status="out_of_window",
                checked_at=now,
                signature=self._signature(trade),
                lookback_days=self.settings["initial_lookback_days"],
                reason="opening predates configured complete-history window",
            )
            self._save(trade, state)
            Trade.commit()
            logger.warning(
                "Exchange ledger outside initial lookback %s trade=%s | preserving prior "
                "statistics without repeated queries",
                trade.pair,
                trade.id,
            )
            return
        if end < start:
            return
        ids = self._filled_order_ids(trade)
        if any(
            int((o.order_filled_utc or o.order_date_utc).timestamp() * 1000) > end
            for o in ids.values()
        ):
            return  # Give recently filled orders/ledger postings time to settle.
        cursor = max(
            start, int(state.get("cursor_ms", start)) - self.settings["overlap_seconds"] * 1000
        )
        # Binance ledger endpoints are limited to seven days. Persist one chunk per
        # accounting round so an initial 89-day recovery cannot monopolize a bot loop.
        fetch_end = min(end, cursor + 7 * DAY_MS - 1)
        expected_signature = self._signature(trade)
        raw_fills, raw_funding = self._collect(market["id"], cursor, fetch_end)
        with self._trade_write_lock():
            Trade.session.expire(trade)
            if self._signature(trade) != expected_signature:
                raise ValueError("trade changed during ledger collection")
            fills = self._records(trade, "fill")
            funding = self._records(trade, "funding")
            previous_fills, previous_funding = len(fills), len(funding)
            self._merge_records(
                trade,
                market["id"],
                ids,
                cursor,
                fetch_end,
                fills,
                funding,
                raw_fills,
                raw_funding,
            )
            if fetch_end < end:
                state.update(
                    status="collecting",
                    cursor_ms=fetch_end,
                    checked_at=now,
                    signature=self._signature(trade),
                    reason=None,
                )
            else:
                net, fees, funded, _entry_notional = self._verify(trade, ids, fills, funding, end)
                closed_ready = not trade.is_open and end >= int(
                    trade.close_date_utc.timestamp() * 1000
                )
                profit_ratio = self._profit_ratio(trade, net) if closed_ready else None
                if closed_ready:
                    trade.close_profit_abs = float(net)
                    trade.realized_profit = float(net)
                    trade.close_profit = profit_ratio
                    trade.funding_fees = float(funded)
                state.update(
                    status="verified" if closed_ready else "open_reconciled",
                    cursor_ms=end,
                    checked_at=now,
                    net_profit=float(net),
                    actual_commission=float(fees),
                    actual_funding=float(funded),
                    profit_ratio=profit_ratio,
                    signature=self._signature(trade),
                    ratio_basis="framework fee-inclusive entry stake",
                    reason=None,
                )
            self._save(trade, state, fills, funding)
            Trade.commit()
        logger.info(
            "交易所账本对账完成 %s trade=%s | new_fills=%s new_funding=%s status=%s",
            trade.pair,
            trade.id,
            len(fills) - previous_fills,
            len(funding) - previous_funding,
            state["status"],
        )

    @staticmethod
    def _profit_ratio(trade: Trade, net: Decimal) -> float:
        total_stake = sum(
            (
                money(trade._calc_open_trade_value(order.safe_amount_after_fee, order.safe_price))
                for order in trade.orders
                if not order.ft_is_open
                and order.safe_filled
                and order.ft_order_side == trade.entry_side
            ),
            Decimal(0),
        )
        denominator = money(total_stake)
        if denominator <= 0:
            raise ValueError("invalid fee-inclusive entry stake")
        return float(net / denominator * money(trade.leverage))

    def _merge_records(
        self, trade, symbol, ids, cursor, end, fills, funding, raw_fills, raw_funding
    ):
        for row in raw_fills:
            stamp = int(row["time"])
            if row["symbol"] != symbol or not cursor <= stamp <= end:
                raise ValueError("fill outside requested market/time window")
            oid = str(row["orderId"])
            if oid not in ids:
                raise ValueError("exchange fill has no matching local order")
            if row.get("positionSide", "BOTH") != "BOTH":
                raise ValueError("hedged fill cannot be assigned safely")
            if row["commissionAsset"] != trade.stake_currency:
                raise ValueError("fee currency needs historical conversion")
            fills[str(row["id"])] = {
                "id": str(row["id"]),
                "order": oid,
                "time": stamp,
                "side": row["side"].lower(),
                "quantity": str(money(row["qty"])),
                "price": str(money(row["price"])),
                "commission": str(money(row["commission"])),
                "realized_pnl": str(money(row["realizedPnl"])),
            }
        for row in raw_funding:
            stamp = int(row["time"])
            if (
                row["symbol"] != symbol
                or row["incomeType"] != "FUNDING_FEE"
                or row["asset"] != trade.stake_currency
                or not cursor <= stamp <= end
            ):
                raise ValueError("funding outside requested market/time/currency")
            funding[str(row["tranId"])] = {"time": stamp, "amount": str(money(row["income"]))}

    def _verify(self, trade, ids, fills, funding, end) -> tuple:
        quantities: dict[str, Decimal] = {}
        running = Decimal(0)
        fees = pnl = entry_notional = Decimal(0)
        rows = sorted(fills.values(), key=lambda r: (r["time"], int(r["id"])))
        for index, row in enumerate(rows):
            quantity, price = money(row["quantity"]), money(row["price"])
            if quantity <= 0 or price <= 0 or row["side"] not in {"buy", "sell"}:
                raise ValueError("invalid execution amount/price/side")
            quantities[row["order"]] = quantities.get(row["order"], Decimal(0)) + quantity
            order = ids.get(row["order"])
            expected_side = (
                trade.exit_side
                if order and order.ft_order_side == "stoploss"
                else order.ft_order_side
                if order
                else None
            )
            if row["side"] != expected_side:
                raise ValueError("execution side does not match local order")
            entering = row["side"] == trade.entry_side
            running += quantity if entering else -quantity
            if running < 0 or (running == 0 and index < len(rows) - 1):
                raise ValueError("ledger contains separate or incomplete position cycles")
            if entering:
                entry_notional += quantity * price * money(trade.contract_size or 1)
            fees += money(row["commission"])
            pnl += money(row["realized_pnl"])
        for oid, order in ids.items():
            amount = self.bot.exchange._contracts_to_amount(
                trade.pair, float(quantities.get(oid, 0))
            )
            if not math.isclose(amount, order.safe_filled, rel_tol=1e-8, abs_tol=1e-12):
                raise ValueError("execution quantity does not match local filled order")
        if not trade.is_open and running != 0:
            raise ValueError("closed position has remaining execution quantity")
        if entry_notional <= 0 or trade.leverage <= 0:
            raise ValueError("invalid profit denominator")
        funded = self._verify_funding_ownership(trade, funding, rows, end)
        return pnl - fees + funded, fees, funded, entry_notional

    @staticmethod
    def _verify_funding_ownership(trade, funding, fills, end) -> Decimal:
        # A funding row belongs to a holding interval, not an order ID. Overlaps are ambiguous.
        if funding:
            first_fill = min(row["time"] for row in fills)
            last_fill = max(row["time"] for row in fills) if not trade.is_open else end
            if any(not first_fill <= row["time"] <= last_fill for row in funding.values()):
                raise ValueError("funding outside actual holding interval")
            others = Trade.get_trades([Trade.pair == trade.pair, Trade.id != trade.id]).all()
            for other in others:
                other_start = ExchangeAccounting._opening_ms(other)
                other_end = (
                    int(other.close_date_utc.timestamp() * 1000) if not other.is_open else end
                )
                if any(other_start <= row["time"] <= other_end for row in funding.values()):
                    raise ValueError("funding overlaps another local trade")
        funded = sum((money(row["amount"]) for row in funding.values()), Decimal(0))
        return funded
