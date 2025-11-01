"""
策略资金快照数据库模型
记录每个bot loop的资金情况
"""
import logging
from datetime import datetime
from typing import Any, ClassVar, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from freqtrade.persistence.base import ModelBase, SessionType
from freqtrade.util import dt_now


logger = logging.getLogger(__name__)


class StrategySnapshot(ModelBase):
    """
    策略资金快照数据库模型
    每个bot loop记录一次当前的资金状态

    字段说明:
    - strategy_name: 策略名称
    - timestamp: 快照时间
    - initial_balance: 初始资金
    - wallet_balance: 钱包余额
    - total_balance: 总资产（含持仓）
    - total_profit_pct: 总收益率
    - open_trade_count: 持仓订单数
    - closed_trade_count: 已平仓订单数
    - short_balance: 做空账户余额
    - short_stake: 做空开仓金额
    - short_open_profit: 做空持仓盈亏
    - short_closed_profit: 做空已平仓盈亏
    - short_position_profit_pct: 做空持仓盈利率
    - short_total_profit_pct: 做空总收益率
    - long_balance: 做多账户余额
    - long_stake: 做多开仓金额
    - long_open_profit: 做多持仓盈亏
    - long_closed_profit: 做多已平仓盈亏
    - long_position_profit_pct: 做多持仓盈利率
    - long_total_profit_pct: 做多总收益率
    - extra_data: 策略自定义数据（JSON格式）
    """

    __tablename__ = "strategy_snapshots"
    __allow_unmapped__ = True
    session: ClassVar[SessionType]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 基本信息
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=dt_now, index=True)

    # 总账户信息
    initial_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wallet_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    open_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 做空账户信息
    short_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    short_stake: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    short_open_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    short_closed_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    short_position_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    short_total_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 做多账户信息
    long_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    long_stake: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    long_open_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    long_closed_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    long_position_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    long_total_profit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 策略自定义数据（JSON字符串）
    extra_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self):
        return (
            f"StrategySnapshot(id={self.id}, strategy={self.strategy_name}, "
            f"timestamp={self.timestamp}, total_balance={self.total_balance:.2f}, "
            f"profit={self.total_profit_pct:.2f}%)"
        )

    @classmethod
    def create_snapshot(
        cls,
        strategy_name: str,
        initial_balance: float,
        wallet_balance: float,
        total_balance: float,
        total_profit_pct: float,
        open_trade_count: int,
        closed_trade_count: int,
        short_balance: float,
        short_stake: float,
        short_open_profit: float,
        short_closed_profit: float,
        short_position_profit_pct: float,
        short_total_profit_pct: float,
        long_balance: float,
        long_stake: float,
        long_open_profit: float,
        long_closed_profit: float,
        long_position_profit_pct: float,
        long_total_profit_pct: float,
        extra_data: Optional[dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> "StrategySnapshot":
        """
        创建一个策略快照并保存到数据库

        :param strategy_name: 策略名称
        :param initial_balance: 初始资金
        :param wallet_balance: 钱包余额
        :param total_balance: 总资产
        :param total_profit_pct: 总收益率
        :param open_trade_count: 持仓订单数
        :param closed_trade_count: 已平仓订单数
        :param short_balance: 做空账户余额
        :param short_stake: 做空开仓金额
        :param short_open_profit: 做空持仓盈亏
        :param short_closed_profit: 做空已平仓盈亏
        :param short_position_profit_pct: 做空持仓盈利率
        :param short_total_profit_pct: 做空总收益率
        :param long_balance: 做多账户余额
        :param long_stake: 做多开仓金额
        :param long_open_profit: 做多持仓盈亏
        :param long_closed_profit: 做多已平仓盈亏
        :param long_position_profit_pct: 做多持仓盈利率
        :param long_total_profit_pct: 做多总收益率
        :param extra_data: 策略自定义数据
        :param timestamp: 快照时间（默认当前时间）
        :return: StrategySnapshot对象
        """
        import json

        snapshot = cls(
            strategy_name=strategy_name,
            timestamp=timestamp or dt_now(),
            initial_balance=initial_balance,
            wallet_balance=wallet_balance,
            total_balance=total_balance,
            total_profit_pct=total_profit_pct,
            open_trade_count=open_trade_count,
            closed_trade_count=closed_trade_count,
            short_balance=short_balance,
            short_stake=short_stake,
            short_open_profit=short_open_profit,
            short_closed_profit=short_closed_profit,
            short_position_profit_pct=short_position_profit_pct,
            short_total_profit_pct=short_total_profit_pct,
            long_balance=long_balance,
            long_stake=long_stake,
            long_open_profit=long_open_profit,
            long_closed_profit=long_closed_profit,
            long_position_profit_pct=long_position_profit_pct,
            long_total_profit_pct=long_total_profit_pct,
            extra_data=json.dumps(extra_data) if extra_data else None,
        )

        try:
            cls.session.add(snapshot)
            cls.session.commit()
            logger.debug(f"策略快照已保存: {snapshot}")
        except SQLAlchemyError as e:
            # 数据库操作失败，回滚
            logger.error(f"保存策略快照失败: {e}", exc_info=True)
            try:
                cls.session.rollback()
            except Exception as rollback_error:
                logger.error(f"回滚失败: {rollback_error}", exc_info=True)
        except Exception as e:
            # 其他异常（如 JSON 序列化错误）
            logger.error(f"创建快照时发生未知错误: {e}", exc_info=True)

        return snapshot

    @classmethod
    def get_latest_snapshot(cls, strategy_name: str) -> Optional["StrategySnapshot"]:
        """
        获取指定策略的最新快照

        :param strategy_name: 策略名称
        :return: StrategySnapshot对象或None
        """
        try:
            return cls.session.scalars(
                select(cls)
                .filter(cls.strategy_name == strategy_name)
                .order_by(cls.timestamp.desc())
                .limit(1)
            ).first()
        except SQLAlchemyError as e:
            logger.error(f"查询最新快照失败: {e}", exc_info=True)
            try:
                cls.session.rollback()
            except Exception:
                pass
            return None

    @classmethod
    def get_snapshots(
        cls,
        strategy_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list["StrategySnapshot"]:
        """
        查询策略快照

        :param strategy_name: 策略名称（可选）
        :param start_time: 起始时间（可选）
        :param end_time: 结束时间（可选）
        :param limit: 返回数量限制
        :return: StrategySnapshot列表
        """
        try:
            query = select(cls)
            filters = []

            if strategy_name:
                filters.append(cls.strategy_name == strategy_name)
            if start_time:
                filters.append(cls.timestamp >= start_time)
            if end_time:
                filters.append(cls.timestamp <= end_time)

            if filters:
                query = query.filter(*filters)

            query = query.order_by(cls.timestamp.desc()).limit(limit)

            return list(cls.session.scalars(query).all())
        except SQLAlchemyError as e:
            logger.error(f"查询快照失败: {e}", exc_info=True)
            try:
                cls.session.rollback()
            except Exception:
                pass
            return []
