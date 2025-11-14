"""
带快照功能的策略基类
提供通用的资产统计、日志记录和数据库存储功能
"""
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import logging
import re

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.persistence.strategy_snapshot import StrategySnapshot
from freqtrade.strategy.interface import IStrategy
from freqtrade.enums import RunMode

logger = logging.getLogger(__name__)


class BaseStrategyWithSnapshot(IStrategy):
    """
    策略基类，提供通用的资产管理和统计功能

    功能：
    1. 自动统计long/short账户的资金情况
    2. 每个bot loop记录详细日志
    3. 将资金快照保存到数据库
    4. 在 advise_entry 阶段自动根据黑名单过滤入场信号（做多/做空分离）
    5. 子类可以通过重写 get_extra_snapshot_data() 添加自定义数据
    6. 子类可以通过重写 log_strategy_specific_info() 添加策略特定日志

    所有继承此类的策略都可以使用:
    - get_assets_in_usdt(): 获取详细的资产统计
    - bot_loop_start(): 每个循环自动更新资产情况并记录到数据库
    - 黑名单过滤: 自动在 advise_entry 阶段过滤，无需子类干预
    """

    def __init__(self, config) -> None:
        super().__init__(config)

        # 保存配置引用
        self.config = config

        # 检测运行模式
        self.runmode = config.get('runmode', RunMode.OTHER) if hasattr(config, 'get') else RunMode.OTHER
        self.is_hyperopt = self.runmode == RunMode.HYPEROPT
        self.is_backtest = self.runmode == RunMode.BACKTEST
        self.is_optimize_mode = self.runmode in [RunMode.BACKTEST, RunMode.HYPEROPT]
        self.is_live_mode = self.runmode in [RunMode.LIVE, RunMode.DRY_RUN]

        # 初始化总资金
        self.dry_run_wallet = config.get('dry_run_wallet', 0) if hasattr(config, 'get') else 0

        # ========== 账户分离配置 ==========
        account_config = config.get('strategy_account', {}) if hasattr(config, 'get') else {}

        # 账户分离开关：启用即严格限制
        self.account_enabled = account_config.get('enabled', False)
        self.strict_account_mode = self.account_enabled  # 启用即严格限制

        # 保存配置，稍后在 bot_loop_start 中获取实际资金
        self._account_config = account_config
        self._use_ratio = account_config.get('use_ratio', False)
        self._long_ratio = account_config.get('long_ratio', 0.5)
        self._short_ratio = account_config.get('short_ratio', 0.5)

        # 初始化为0，第一次 bot_loop_start 时获取实际资金
        self.long_initial_balance = 0.0
        self.short_initial_balance = 0.0
        self._initial_balance_initialized = False
        self._account_usage_stats: Dict[str, Dict[str, float]] = {
            "long": {
                "initial_balance": 0.0,
                "used_balance": 0.0,
                "available_balance": 0.0,
            },
            "short": {
                "initial_balance": 0.0,
                "used_balance": 0.0,
                "available_balance": 0.0,
            },
        }

        # ========== 快照和日志配置 ==========
        snapshot_config = config.get('strategy_snapshot', {}) if hasattr(config, 'get') else {}

        # 在 hyperopt 模式下自动禁用快照和日志（除非明确配置）
        if self.is_hyperopt:
            # Hyperopt 默认禁用所有输出
            default_snapshot_enabled = snapshot_config.get('enabled', False)
            default_detailed_logs = snapshot_config.get('enable_detailed_logs', False)
            default_strategy_logs = snapshot_config.get('enable_strategy_logs', False)
            default_frequency = snapshot_config.get('snapshot_frequency', 100)  # 降低频率
        elif self.is_backtest:
            # 回测默认启用，但频率较低
            default_snapshot_enabled = snapshot_config.get('enabled', True)
            default_detailed_logs = snapshot_config.get('enable_detailed_logs', True)
            default_strategy_logs = snapshot_config.get('enable_strategy_logs', True)
            default_frequency = snapshot_config.get('snapshot_frequency', 10)
        else:
            # 实盘/模拟盘默认全部启用
            default_snapshot_enabled = snapshot_config.get('enabled', True)
            default_detailed_logs = snapshot_config.get('enable_detailed_logs', True)
            default_strategy_logs = snapshot_config.get('enable_strategy_logs', True)
            default_frequency = snapshot_config.get('snapshot_frequency', 1)

        self.enable_snapshot = default_snapshot_enabled
        self.enable_detailed_logs = default_detailed_logs
        self.enable_strategy_logs = default_strategy_logs
        self.snapshot_frequency = default_frequency

        # 循环计数器（用于控制快照频率）
        self.bot_loop_counter = 0

        # 资产统计变量
        self.total_short_usdt = 0.0
        self.short_profit_ratio = 0.0
        self.total_long_usdt = 0.0
        self.long_profit_ratio = 0.0
        self.real_usdt = 0.0
        self.total_profit_pct = 0.0

        # ========== 黑名单配置 ==========
        blacklist_config = config.get('strategy_blacklist', {}) if hasattr(config, 'get') else {}

        self.blacklist_enabled = blacklist_config.get('enabled', False)
        self.long_blacklist = blacklist_config.get('long_blacklist', [])
        self.short_blacklist = blacklist_config.get('short_blacklist', [])
        self.common_blacklist = blacklist_config.get('common_blacklist', [])

        # 编译正则表达式以提高性能
        self._long_blacklist_patterns = [re.compile(pattern) for pattern in self.long_blacklist]
        self._short_blacklist_patterns = [re.compile(pattern) for pattern in self.short_blacklist]
        self._common_blacklist_patterns = [re.compile(pattern) for pattern in self.common_blacklist]

        # 只在非 hyperopt 模式下输出初始化日志
        if not self.is_hyperopt:
            logger.info("=" * 80)
            logger.info("📋 策略账户配置:")
            logger.info(f"  运行模式: {self.runmode.value.upper()}")
            logger.info(f"  账户分离: {'✅ 启用 (严格限制)' if self.account_enabled else '❌ 禁用'}")
            if self.account_enabled:
                if self._use_ratio:
                    logger.info(f"  资金分配: Long {self._long_ratio:.1%} / Short {self._short_ratio:.1%}")
                else:
                    long_amt = self._account_config.get('long_initial_balance', '自动(50%)')
                    short_amt = self._account_config.get('short_initial_balance', '自动(50%)')
                    logger.info(f"  Long 账户: {long_amt} USDT" if isinstance(long_amt, (int, float)) else f"  Long 账户: {long_amt}")
                    logger.info(f"  Short 账户: {short_amt} USDT" if isinstance(short_amt, (int, float)) else f"  Short 账户: {short_amt}")
            logger.info(f"  数据库快照: {'✅ 启用' if self.enable_snapshot else '❌ 禁用'}")
            if self.enable_snapshot:
                logger.info(f"  快照频率: 每 {self.snapshot_frequency} 个 loop")
            logger.info(f"  详细日志: {'✅ 启用' if self.enable_detailed_logs else '❌ 禁用'}")
            logger.info(f"  策略日志: {'✅ 启用' if self.enable_strategy_logs else '❌ 禁用'}")
            logger.info(f"  分离黑名单: {'✅ 启用' if self.blacklist_enabled else '❌ 禁用'}")
            if self.blacklist_enabled:
                logger.info(f"  Long 黑名单: {len(self.long_blacklist)} 条规则")
                logger.info(f"  Short 黑名单: {len(self.short_blacklist)} 条规则")
                logger.info(f"  通用黑名单: {len(self.common_blacklist)} 条规则")
            logger.info("=" * 80)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """
        在每个bot循环开始时自动更新资产情况
        """
        try:
            # ========== 首次运行时初始化账户余额 ==========
            if not self._initial_balance_initialized and self.account_enabled:
                initial_usdt = 0.0

                # 尝试获取实际钱包余额
                if hasattr(self, 'wallets') and self.wallets:
                    try:
                        # 优先使用 get_starting_balance()
                        initial_usdt = float(self.wallets.get_starting_balance())
                    except Exception:
                        try:
                            # 备选方案：使用当前总余额
                            initial_usdt = float(self.wallets.get_total("USDT"))
                        except Exception:
                            # 都失败了，使用配置中的 dry_run_wallet
                            initial_usdt = self.dry_run_wallet
                else:
                    # 钱包还没准备好，使用配置中的 dry_run_wallet
                    initial_usdt = self.dry_run_wallet

                # 根据配置计算 long/short 初始余额
                if self._use_ratio:
                    # 使用比例分配
                    long_ratio = self._long_ratio
                    short_ratio = self._short_ratio
                    total_ratio = long_ratio + short_ratio
                    if total_ratio > 0:
                        # 归一化比例
                        long_ratio = long_ratio / total_ratio
                        short_ratio = short_ratio / total_ratio
                    else:
                        # 比例无效，使用 50/50
                        long_ratio = 0.5
                        short_ratio = 0.5

                    self.long_initial_balance = initial_usdt * long_ratio
                    self.short_initial_balance = initial_usdt * short_ratio
                else:
                    # 使用具体金额
                    configured_long = float(self._account_config.get(
                        'long_initial_balance',
                        initial_usdt * 0.5  # 默认 50/50
                    ))
                    configured_short = float(self._account_config.get(
                        'short_initial_balance',
                        initial_usdt * 0.5  # 默认 50/50
                    ))

                    total_configured = configured_long + configured_short
                    self.long_initial_balance = configured_long
                    self.short_initial_balance = configured_short

                    # 如果钱包资金不足以覆盖固定金额，则按比例缩放
                    if initial_usdt > 0 and total_configured > initial_usdt and total_configured > 0:
                        scale = initial_usdt / total_configured
                        self.long_initial_balance = configured_long * scale
                        self.short_initial_balance = configured_short * scale

                        if not self.is_optimize_mode:
                            logger.warning(
                                "⚠️ 固定账户余额配置超过实际钱包资金，总资金不足。"
                                f" 已按比例缩放至 Long {self.long_initial_balance:.2f} / "
                                f"Short {self.short_initial_balance:.2f}（总资金 {initial_usdt:.2f}）。"
                            )

                self._initial_balance_initialized = True

                # 只在非优化模式下输出日志
                if not self.is_optimize_mode:
                    logger.info("=" * 80)
                    logger.info("💰 账户余额初始化完成:")
                    logger.info(f"  总初始资金: {initial_usdt:.2f} USDT")
                    logger.info(f"  Long 账户: {self.long_initial_balance:.2f} USDT")
                    logger.info(f"  Short 账户: {self.short_initial_balance:.2f} USDT")
                    logger.info("=" * 80)

            # 增加循环计数
            self.bot_loop_counter += 1

            # 判断是否需要在本次循环记录快照
            should_snapshot = (
                self.enable_snapshot
                and self.snapshot_frequency > 0
                and (self.bot_loop_counter % self.snapshot_frequency == 0)
            )

            # 获取资产统计
            asset_data = self._get_detailed_assets()

            # 更新实例变量
            self.total_short_usdt = asset_data['total_short_usdt']
            self.short_profit_ratio = asset_data['short_position_profit_pct']
            self.total_long_usdt = asset_data['total_long_usdt']
            self.long_profit_ratio = asset_data['long_position_profit_pct']
            self.real_usdt = asset_data['real_usdt']
            self.total_profit_pct = asset_data['total_profit_pct']

            # 根据配置决定是否输出日志
            if self.enable_detailed_logs:
                logger.info("=" * 80)
                logger.info(f"⏰ 当前时间: {current_time}")
                self._log_asset_summary(asset_data)

            # 子类可以添加策略特定的日志
            if self.enable_strategy_logs:
                self.log_strategy_specific_info(current_time, asset_data, **kwargs)

            # 保存快照到数据库（根据频率）
            if should_snapshot:
                self._save_snapshot(current_time, asset_data)

        except Exception as e:
            logger.error(f"❌ 更新资产情况失败: {e}", exc_info=True)
            # 设置默认值避免后续代码出错
            self.total_short_usdt = 0.0
            self.short_profit_ratio = 0.0
            self.total_long_usdt = 0.0
            self.long_profit_ratio = 0.0
            self.real_usdt = 0.0
            self.total_profit_pct = 0.0

        return super().bot_loop_start(current_time=current_time, **kwargs)

    def _get_detailed_assets(self) -> dict[str, Any]:
        """
        计算详细的资产情况

        返回值: 包含所有资产信息的字典
        """
        # 1. 获取初始资金
        # 优先使用账户配置的初始余额，否则从钱包获取
        if self.account_enabled:
            initial_usdt = self.long_initial_balance + self.short_initial_balance
        elif self.wallets:
            initial_usdt = float(self.wallets.get_starting_balance())
        else:
            raise RuntimeError("钱包未初始化，无法获取初始资金")

        if initial_usdt == 0:
            logger.warning("⚠️ 初始资金为0，资产统计可能不准确")

        # 2. 获取所有交易
        all_open_trades = Trade.get_trades_proxy(is_open=True)
        all_closed_trades = Trade.get_trades_proxy(is_open=False)

        # 3. 缓存价格
        pairs = list({t.pair for t in all_open_trades})
        last_close = {}

        for pair in pairs:
            # get_analyzed_dataframe 不会抛异常，只会返回空 DataFrame
            df, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
            if len(df) > 0:
                last_close[pair] = float(df["close"].iloc[-1])
            else:
                logger.debug(f"跳过 {pair}：没有数据")

        # 4. 计算持仓盈亏
        short_open_profit = 0.0
        long_open_profit = 0.0
        short_stake = 0.0
        long_stake = 0.0

        for trade in all_open_trades:
            current_price = last_close.get(trade.pair)
            if current_price is None or not trade.open_rate:
                logger.debug(f"跳过 {trade.pair}：缺少价格数据")
                continue

            # 计算盈亏比率
            if trade.is_short:
                profit_ratio = 1.0 - (current_price / trade.open_rate)
            else:
                profit_ratio = (current_price / trade.open_rate) - 1.0

            profit_ratio *= float(trade.leverage or 1.0)
            profit_amount = float(trade.stake_amount) * profit_ratio

            # 分类累计
            if trade.is_short:
                short_open_profit += profit_amount
                short_stake += float(trade.stake_amount)
            else:
                long_open_profit += profit_amount
                long_stake += float(trade.stake_amount)

        # 5. 计算已平仓盈亏
        short_closed_profit = 0.0
        long_closed_profit = 0.0

        for trade in all_closed_trades:
            profit = float(trade.realized_profit or 0.0)
            if trade.is_short:
                short_closed_profit += profit
            else:
                long_closed_profit += profit

        # 6. 获取钱包余额
        # 所有模式统一从 wallets 获取（包括实盘、DryRun、回测、Hyperopt）
        if not self.wallets:
            raise RuntimeError("钱包未初始化，无法获取当前余额")

        wallet_balance = float(self.wallets.get_total("USDT"))

        # 7. 计算总资产
        total_open_profit = short_open_profit + long_open_profit
        total_closed_profit = short_closed_profit + long_closed_profit
        real_usdt = wallet_balance + total_open_profit

        # 8. 计算各账户情况（使用配置的资金分配）
        initial_short = self.short_initial_balance
        initial_long = self.long_initial_balance

        total_short_usdt = initial_short + short_closed_profit + short_open_profit
        total_long_usdt = initial_long + long_closed_profit + long_open_profit

        # 9. 计算盈利比率
        short_position_profit_pct = (
            0.0 if short_stake == 0
            else 100.0 * short_open_profit / short_stake
        )
        long_position_profit_pct = (
            0.0 if long_stake == 0
            else 100.0 * long_open_profit / long_stake
        )

        short_total_profit_pct = (
            0.0 if initial_short == 0
            else 100.0 * (short_closed_profit + short_open_profit) / initial_short
        )
        long_total_profit_pct = (
            0.0 if initial_long == 0
            else 100.0 * (long_closed_profit + long_open_profit) / initial_long
        )

        total_profit_pct = (
            0.0 if initial_usdt == 0
            else 100.0 * (total_closed_profit + total_open_profit) / initial_usdt
        )

        return {
            'initial_usdt': initial_usdt,
            'initial_short': initial_short,
            'initial_long': initial_long,
            'wallet_balance': wallet_balance,
            'total_balance': real_usdt,
            'real_usdt': real_usdt,
            'total_profit_pct': total_profit_pct,
            'open_trade_count': len(all_open_trades),
            'closed_trade_count': len(all_closed_trades),
            # Short数据
            'total_short_usdt': total_short_usdt,
            'short_stake': short_stake,
            'short_open_profit': short_open_profit,
            'short_closed_profit': short_closed_profit,
            'short_position_profit_pct': short_position_profit_pct,
            'short_total_profit_pct': short_total_profit_pct,
            # Long数据
            'total_long_usdt': total_long_usdt,
            'long_stake': long_stake,
            'long_open_profit': long_open_profit,
            'long_closed_profit': long_closed_profit,
            'long_position_profit_pct': long_position_profit_pct,
            'long_total_profit_pct': long_total_profit_pct,
        }

    def _log_asset_summary(self, asset_data: dict[str, Any]) -> None:
        """
        输出通用的资产汇总日志
        """
        logger.info("=" * 80)
        logger.info("📊 资产情况汇总")
        logger.info("=" * 80)

        # Short 账户信息
        logger.info("📉 【做空账户 (SHORT)】")
        logger.info(f"  💰 初始资金: {asset_data['initial_short']:>12.2f} USDT")
        logger.info(f"  📍 当前开仓金额: {asset_data['short_stake']:>12.2f} USDT")
        logger.info(
            f"  💵 持仓浮动盈亏: {asset_data['short_open_profit']:>12.2f} USDT "
            f"({asset_data['short_position_profit_pct']:>7.2f}%)"
        )
        logger.info(f"  ✅ 已平仓盈亏: {asset_data['short_closed_profit']:>12.2f} USDT")
        logger.info(f"  📊 账户总资产: {asset_data['total_short_usdt']:>12.2f} USDT")
        logger.info(
            f"  📈 总收益率: {asset_data['short_total_profit_pct']:>12.2f}% (基于初始资金)"
        )
        logger.info("-" * 80)

        # Long 账户信息
        logger.info("📈 【做多账户 (LONG)】")
        logger.info(f"  💰 初始资金: {asset_data['initial_long']:>12.2f} USDT")
        logger.info(f"  📍 当前开仓金额: {asset_data['long_stake']:>12.2f} USDT")
        logger.info(
            f"  💵 持仓浮动盈亏: {asset_data['long_open_profit']:>12.2f} USDT "
            f"({asset_data['long_position_profit_pct']:>7.2f}%)"
        )
        logger.info(f"  ✅ 已平仓盈亏: {asset_data['long_closed_profit']:>12.2f} USDT")
        logger.info(f"  📊 账户总资产: {asset_data['total_long_usdt']:>12.2f} USDT")
        logger.info(
            f"  📈 总收益率: {asset_data['long_total_profit_pct']:>12.2f}% (基于初始资金)"
        )
        logger.info("-" * 80)

        # 总览信息
        logger.info("💼 【账户总览】")
        logger.info(f"  💰 初始总资金: {asset_data['initial_usdt']:>12.2f} USDT")
        logger.info(f"  💳 钱包余额: {asset_data['wallet_balance']:>12.2f} USDT")
        logger.info(
            f"  💵 持仓浮动盈亏: "
            f"{asset_data['short_open_profit'] + asset_data['long_open_profit']:>12.2f} USDT"
        )
        logger.info(f"  📊 账户总资产: {asset_data['real_usdt']:>12.2f} USDT (含持仓)")
        logger.info(f"  📈 总收益率: {asset_data['total_profit_pct']:>12.2f}%")
        logger.info(f"  📝 持仓订单数: {asset_data['open_trade_count']:>12} 个")
        logger.info(f"  ✅ 已平仓订单数: {asset_data['closed_trade_count']:>12} 个")
        logger.info("=" * 80)

    def _save_snapshot(self, current_time: datetime, asset_data: dict[str, Any]) -> None:
        """
        保存快照到数据库
        """
        try:
            # 获取策略特定的额外数据
            extra_data = self.get_extra_snapshot_data(asset_data)

            # 创建快照
            StrategySnapshot.create_snapshot(
                strategy_name=self.__class__.__name__,
                timestamp=current_time,
                initial_balance=asset_data['initial_usdt'],
                wallet_balance=asset_data['wallet_balance'],
                total_balance=asset_data['real_usdt'],
                total_profit_pct=asset_data['total_profit_pct'],
                open_trade_count=asset_data['open_trade_count'],
                closed_trade_count=asset_data['closed_trade_count'],
                short_balance=asset_data['total_short_usdt'],
                short_stake=asset_data['short_stake'],
                short_open_profit=asset_data['short_open_profit'],
                short_closed_profit=asset_data['short_closed_profit'],
                short_position_profit_pct=asset_data['short_position_profit_pct'],
                short_total_profit_pct=asset_data['short_total_profit_pct'],
                long_balance=asset_data['total_long_usdt'],
                long_stake=asset_data['long_stake'],
                long_open_profit=asset_data['long_open_profit'],
                long_closed_profit=asset_data['long_closed_profit'],
                long_position_profit_pct=asset_data['long_position_profit_pct'],
                long_total_profit_pct=asset_data['long_total_profit_pct'],
                extra_data=extra_data,
            )
            logger.debug("💾 资金快照已保存到数据库")
        except Exception as e:
            logger.error(f"❌ 保存资金快照失败: {e}", exc_info=True)

    # ========== 资金限制辅助方法 ==========

    def get_account_available_balance(self, side: str) -> float:
        """
        获取指定账户（long/short）的可用余额

        仅在启用严格账户模式时有效。如果未启用，返回钱包总余额。

        :param side: "long" 或 "short"
        :return: 可用余额（USDT）
        """
        if not self.strict_account_mode:
            # 非严格模式：不分离 long/short 账户
            # 所有模式（实盘/DryRun/回测/Hyperopt）都从钱包获取余额
            # - 实盘：wallets.get_total() 返回交易所的真实余额
            # - DryRun/回测/Hyperopt：wallets.get_total() 返回基于 dry_run_wallet 的模拟余额

            if not self.wallets:
                # 钱包未初始化（可能是首次循环），返回0忽略本轮操作
                logger.error(
                    "⚠️ 钱包未初始化，无法获取可用余额。"
                    "本轮不开仓，等待下次循环。"
                    "如果此错误持续出现，请检查 FreqtradeBot 初始化流程。"
                )
                return 0.0

            # 所有模式统一：直接返回钱包余额（包括0）
            return float(self.wallets.get_total("USDT"))

        # 严格模式：计算该账户已使用的资金
        try:
            # 获取该方向的所有持仓
            open_trades = Trade.get_trades_proxy(is_open=True)

            used_balance = 0.0
            for trade in open_trades:
                trade_is_long = not trade.is_short
                # 使用 max_stake_amount 以包含所有加仓金额
                stake = float(trade.max_stake_amount) if hasattr(trade, 'max_stake_amount') else float(trade.stake_amount)
                if side == "long" and trade_is_long:
                    used_balance += stake
                elif side == "short" and trade.is_short:
                    used_balance += stake

            # 该账户的初始资金
            initial_balance = self.long_initial_balance if side == "long" else self.short_initial_balance

            # 可用余额 = 初始资金 - 当前使用资金
            available = initial_balance - used_balance

            # 如果可用余额为负数，记录警告（但不阻止，让框架自己处理）
            if available < 0:
                logger.warning(
                    f"⚠️ {side.upper()} 账户可用余额为负: {available:.2f} USDT "
                    f"(初始: {initial_balance:.2f}, 持仓占用: {used_balance:.2f})"
                )

            available_balance = max(0.0, available)
            self._account_usage_stats[side] = {
                "initial_balance": float(initial_balance),
                "used_balance": float(used_balance),
                "available_balance": float(available_balance),
            }

            return available_balance

        except Exception as e:
            logger.error(f"计算{side}账户可用余额失败: {e}", exc_info=True)
            return 0.0

    def get_account_usage_stats(self, side: str) -> Dict[str, float]:
        """
        返回指定账户的最新资金使用详情

        :param side: "long" 或 "short"
        :return: 包含初始资金、可用资金、已用资金以及已实现盈亏的字典
        """
        side = side.lower()
        if side not in self._account_usage_stats:
            return {
                "initial_balance": 0.0,
                "used_balance": 0.0,
                "available_balance": 0.0,
            }
        return self._account_usage_stats[side].copy()

    def check_account_balance_limit(
        self,
        side: str,
        proposed_stake: float,
        pair: str = "",
    ) -> Tuple[bool, float]:
        """
        检查提议的开仓金额是否超过账户限制

        :param side: "long" 或 "short"
        :param proposed_stake: 提议的开仓金额
        :param pair: 交易对名称（用于日志）
        :return: (是否允许, 调整后的金额)
        """
        if not self.strict_account_mode:
            # 非严格模式，不限制
            return True, proposed_stake

        available = self.get_account_available_balance(side)

        if proposed_stake <= available:
            return True, proposed_stake

        # 超过限制
        if available <= 0:
            logger.warning(
                f"⚠️ {side.upper()}账户余额不足，无法开仓 {pair} "
                f"(需要: {proposed_stake:.2f}, 可用: {available:.2f})"
            )
            return False, 0.0

        # 调整为可用余额
        logger.warning(
            f"⚠️ {side.upper()}账户余额不足，调整开仓金额 {pair} "
            f"(原: {proposed_stake:.2f} -> 调整: {available:.2f})"
        )
        return True, available

    # ========== 黑名单辅助方法 ==========

    def _is_pair_in_blacklist(self, pair: str, patterns: list) -> bool:
        """
        检查交易对是否匹配黑名单中的任何模式

        :param pair: 交易对名称
        :param patterns: 已编译的正则表达式模式列表
        :return: 是否在黑名单中
        """
        for pattern in patterns:
            if pattern.match(pair):
                return True
        return False

    def is_pair_blacklisted(self, pair: str, side: str, log_reason: bool = True) -> bool:
        """
        检查交易对是否在黑名单中

        :param pair: 交易对
        :param side: "long" 或 "short"
        :param log_reason: 是否输出拒绝原因日志
        :return: True 在黑名单中（应拒绝），False 不在黑名单中（可以交易）
        """
        # 如果未启用黑名单，直接返回 False（不在黑名单）
        if not self.blacklist_enabled:
            return False

        # 检查通用黑名单
        if self._is_pair_in_blacklist(pair, self._common_blacklist_patterns):
            if log_reason:
                logger.info(f"🚫 {pair} 在通用黑名单中，拒绝 {side.upper()} 开仓")
            return True

        # 检查方向特定的黑名单
        if side == "long":
            if self._is_pair_in_blacklist(pair, self._long_blacklist_patterns):
                if log_reason:
                    logger.info(f"🚫 {pair} 在 LONG 黑名单中，拒绝开仓")
                return True
        elif side == "short":
            if self._is_pair_in_blacklist(pair, self._short_blacklist_patterns):
                if log_reason:
                    logger.info(f"🚫 {pair} 在 SHORT 黑名单中，拒绝开仓")
                return True

        # 不在黑名单中
        return False

    def advise_entry(self, dataframe, metadata: dict):
        """
        重写 advise_entry，在信号生成后根据黑名单过滤

        :param dataframe: DataFrame with populated indicators
        :param metadata: Additional information, like the currently traded pair
        :return: DataFrame with entry signals, filtered by blacklist
        """
        # 1. 调用父类方法生成入场信号
        df = super().advise_entry(dataframe, metadata)

        # 2. 如果黑名单未启用，直接返回
        if not self.blacklist_enabled:
            return df

        # 3. 获取交易对名称
        pair = metadata.get('pair', '')

        # 4. 根据黑名单过滤信号
        # 检查是否在通用黑名单中
        if self._is_pair_in_blacklist(pair, self._common_blacklist_patterns):
            logger.info(f"🚫 {pair} 在通用黑名单中，清除所有入场信号")
            df.loc[:, 'enter_long'] = 0
            df.loc[:, 'enter_short'] = 0
            return df

        # 检查 long 黑名单
        if self._is_pair_in_blacklist(pair, self._long_blacklist_patterns):
            if 'enter_long' in df.columns and df['enter_long'].sum() > 0:
                logger.info(f"🚫 {pair} 在 LONG 黑名单中，清除做多信号")
                df.loc[:, 'enter_long'] = 0

        # 检查 short 黑名单
        if self._is_pair_in_blacklist(pair, self._short_blacklist_patterns):
            if 'enter_short' in df.columns and df['enter_short'].sum() > 0:
                logger.info(f"🚫 {pair} 在 SHORT 黑名单中，清除做空信号")
                df.loc[:, 'enter_short'] = 0

        return df

    # ========== 子类可重写的方法 ==========

    def get_extra_snapshot_data(self, asset_data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        子类可以重写此方法，返回策略特定的数据，将被保存到数据库的extra_data字段

        :param asset_data: 当前的资产数据
        :return: 策略特定数据字典，或None
        """
        return None

    def log_strategy_specific_info(
        self, current_time: datetime, asset_data: dict[str, Any], **kwargs
    ) -> None:
        """
        子类可以重写此方法，记录策略特定的日志

        :param current_time: 当前时间
        :param asset_data: 当前的资产数据
        :param kwargs: bot_loop_start的其他参数
        """
        pass

    def get_assets_in_usdt(
        self,
    ) -> Tuple[float, float, float, float, float, float]:
        """
        获取资产情况（兼容旧版本）

        返回值:
            (total_short_usdt, short_profit_ratio, total_long_usdt,
             long_profit_ratio, real_usdt, total_profit_pct)
        """
        try:
            asset_data = self._get_detailed_assets()
            return (
                asset_data['total_short_usdt'],
                asset_data['short_position_profit_pct'],
                asset_data['total_long_usdt'],
                asset_data['long_position_profit_pct'],
                asset_data['real_usdt'],
                asset_data['total_profit_pct'],
            )
        except Exception as e:
            logger.error(f"计算资产情况时发生错误: {e}", exc_info=True)
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
