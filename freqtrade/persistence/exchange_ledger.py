"""Exchange evidence and reconciliation checkpoints; no historical PnL versions."""

import json
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from freqtrade.persistence.base import ModelBase


class ExchangeLedger(ModelBase):
    """Persist immutable exchange evidence and the latest trade checkpoint."""

    __tablename__ = "exchange_ledger"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "pair", "record_type", "record_id", name="exchange_ledger_event"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    exchange: Mapped[str] = mapped_column(String(25))
    pair: Mapped[str] = mapped_column(String(50))
    record_type: Mapped[str] = mapped_column(String(20))  # fill / funding / checkpoint
    record_id: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[int] = mapped_column(BigInteger, index=True)
    payload: Mapped[str] = mapped_column(Text)

    @property
    def data(self) -> dict[str, Any]:
        """Deserialize the JSON payload."""
        return json.loads(self.payload)

    @data.setter
    def data(self, value: dict[str, Any]) -> None:
        """Serialize ``value`` as strict JSON."""
        self.payload = json.dumps(value, allow_nan=False, separators=(",", ":"))
