import logging
from typing import Any

from freqtrade.enums import RunMode


logger = logging.getLogger(__name__)


def start_convert_db(args: dict[str, Any]) -> None:
    from sqlalchemy import func, select
    from sqlalchemy.orm import make_transient

    from freqtrade.configuration.config_setup import setup_utils_configuration
    from freqtrade.persistence import Order, Trade, init_db
    from freqtrade.persistence.migrations import set_sequence_ids
    from freqtrade.persistence.pairlock import PairLock

    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)

    init_db(config["db_url"], config)
    session_target = Trade.session
    init_db(config["db_url_from"], config)
    logger.info("Starting db migration.")

    trade_count = 0
    pairlock_count = 0
    result = Trade.get_trades()
    try:
        for trade in result:
            trade_count += 1
            make_transient(trade)
            for o in trade.orders:
                make_transient(o)

            session_target.add(trade)
    finally:
        Trade.session.remove()

    session_target.commit()

    for pairlock in PairLock.get_all_locks():
        pairlock_count += 1
        make_transient(pairlock)
        session_target.add(pairlock)
    session_target.commit()

    # Update sequences
    max_trade_id = session_target.scalar(select(func.max(Trade.id)))
    max_order_id = session_target.scalar(select(func.max(Order.id)))
    max_pairlock_id = session_target.scalar(select(func.max(PairLock.id)))

    set_sequence_ids(
        session_target.get_bind(),
        trade_id=max_trade_id,
        order_id=max_order_id,
        pairlock_id=max_pairlock_id,
    )

    logger.info(f"Migrated {trade_count} Trades, and {pairlock_count} Pairlocks.")
