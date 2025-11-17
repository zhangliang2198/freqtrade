"""
This module contains the class to persist trades into SQLite
"""

import functools
import logging
import threading
from contextvars import ContextVar
from typing import Any, Final

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import NoSuchModuleError
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from freqtrade.exceptions import OperationalException
from freqtrade.persistence.base import ModelBase
from freqtrade.persistence.custom_data import _CustomData
from freqtrade.persistence.key_value_store import _KeyValueStoreModel
from freqtrade.persistence.llm_models import LLMDecision, LLMPerformanceMetric
from freqtrade.persistence.migrations import check_migrate
from freqtrade.persistence.pairlock import PairLock
from freqtrade.persistence.strategy_snapshot import StrategySnapshot
from freqtrade.persistence.trade_model import Order, Trade


logger = logging.getLogger(__name__)


REQUEST_ID_CTX_KEY: Final[str] = "request_id"
_request_id_ctx_var: ContextVar[str | None] = ContextVar(REQUEST_ID_CTX_KEY, default=None)


def get_request_or_thread_id() -> str | None:
    """
    Helper method to get either async context (for fastapi requests), or thread id
    """
    request_id = _request_id_ctx_var.get()
    if request_id is None:
        # when not in request context - use thread id
        request_id = str(threading.current_thread().ident)

    return request_id


_SQL_DOCS_URL = "http://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls"


def init_db(db_url: str, config: dict[str, Any] | None = None) -> None:
    """
    Initializes this module with the given config,
    registers all known command handlers
    and starts polling for message updates
    :param db_url: Database to use
    :param config: Optional configuration dict for database pool settings
    :return: None
    """
    kwargs: dict[str, Any] = {}

    if db_url == "sqlite:///":
        raise OperationalException(
            f"Bad db-url {db_url}. For in-memory database, please use `sqlite://`."
        )
    if db_url == "sqlite://":
        kwargs.update(
            {
                "poolclass": StaticPool,
            }
        )
    # Take care of thread ownership
    if db_url.startswith("sqlite://"):
        kwargs.update(
            {
                "connect_args": {"check_same_thread": False},
            }
        )

    # 为所有非 SQLite 数据库配置连接池（SQLite 使用 StaticPool）
    # 支持：PostgreSQL、MySQL、MariaDB 等客户端-服务器数据库
    if not db_url.startswith("sqlite"):
        # 从配置获取连接池设置，或使用默认值
        pool_size = 20  # 默认基础连接池大小
        max_overflow = 40  # 默认溢出连接数
        pool_recycle = 3600  # 默认每小时回收连接
        pool_pre_ping = True  # 默认启用连接健康检查

        if config:
            pool_size = config.get("db_pool_size", pool_size)
            max_overflow = config.get("db_max_overflow", max_overflow)
            pool_recycle = config.get("db_pool_recycle", pool_recycle)
            pool_pre_ping = config.get("db_pool_pre_ping", pool_pre_ping)

        kwargs.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_recycle": pool_recycle,  # 定期回收连接,防止连接过期
                "pool_pre_ping": pool_pre_ping,  # 使用前验证连接是否有效
            }
        )

        # 确定数据库类型用于日志记录
        db_type = "未知数据库"
        if db_url.startswith("postgresql"):
            db_type = "PostgreSQL"
        elif db_url.startswith("mysql"):
            db_type = "MySQL"
        elif db_url.startswith("mariadb"):
            db_type = "MariaDB"

        logger.info(
            f"{db_type} 连接池已配置: "
            f"pool_size={pool_size}, max_overflow={max_overflow}, "
            f"total_max={pool_size + max_overflow}"
        )

    try:
        engine = create_engine(db_url, future=True, **kwargs)
    except NoSuchModuleError:
        raise OperationalException(
            f"Given value for db_url: '{db_url}' is no valid database URL! (See {_SQL_DOCS_URL})"
        )

    # https://docs.sqlalchemy.org/en/13/orm/contextual.html#thread-local-scope
    # Scoped sessions proxy requests to the appropriate thread-local session.
    # Since we also use fastAPI, we need to make it aware of the request id, too
    Trade.session = scoped_session(
        sessionmaker(bind=engine, autoflush=False), scopefunc=get_request_or_thread_id
    )
    Order.session = Trade.session
    PairLock.session = Trade.session
    _KeyValueStoreModel.session = Trade.session
    _CustomData.session = scoped_session(
        sessionmaker(bind=engine, autoflush=True), scopefunc=get_request_or_thread_id
    )
    StrategySnapshot.session = Trade.session
    LLMDecision.session = Trade.session
    LLMPerformanceMetric.session = Trade.session

    previous_tables = inspect(engine).get_table_names()
    ModelBase.metadata.create_all(engine)
    check_migrate(engine, decl_base=ModelBase, previous_tables=previous_tables)


def custom_data_rpc_wrapper(func):
    """
    Wrapper for RPC methods when using custom_data
    Similar behavior to deps.get_rpc() - but limited to custom_data.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            _CustomData.session.rollback()
            return func(*args, **kwargs)
        finally:
            _CustomData.session.rollback()
            # Ensure the session is removed after use
            _CustomData.session.remove()

    return wrapper
