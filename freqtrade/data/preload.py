"""
数据预加载模块

在启动时从磁盘加载历史 OHLCV 数据到内存缓存,
避免每次启动都重新下载所有数据,只需下载增量数据。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from pandas import DataFrame

from freqtrade.constants import Config
from freqtrade.data.history import get_datahandler
from freqtrade.enums import CandleType
from freqtrade.exchange import Exchange
from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_seconds


logger = logging.getLogger(__name__)


def preload_ohlcv_data(
    exchange: Exchange,
    pairs: list[str],
    timeframe: str,
    config: Config,
    candle_type: CandleType = CandleType.SPOT,
    informative_pairs: list[tuple[str, str, CandleType]] | None = None,
) -> tuple[int, int]:
    """
    从磁盘预加载历史 OHLCV 数据到 exchange._klines 内存缓存
    
    这样可以避免启动时重新下载所有历史数据,只需下载最新的增量数据。
    
    参数:
        exchange: Exchange 实例
        pairs: 交易对列表
        timeframe: 主时间周期
        config: 配置字典
        candle_type: K 线类型 (SPOT/FUTURES)
        informative_pairs: informative 交易对列表 [(pair, timeframe, candle_type), ...]
    
    返回:
        (成功加载的数量, 总尝试数量)
    """
    if not config.get("preload_ohlcv_data", False):
        logger.debug("数据预加载已禁用")
        return 0, 0
    
    datadir = config.get("datadir")
    if not datadir:
        logger.warning("未配置 datadir,跳过数据预加载")
        return 0, 0
    
    data_format = config.get("dataformat_ohlcv", "feather")
    data_handler = get_datahandler(datadir, data_format)
    
    # 收集所有需要加载的 (pair, timeframe, candle_type) 组合
    pairs_to_load: set[tuple[str, str, CandleType]] = set()
    
    # 主时间周期
    for pair in pairs:
        pairs_to_load.add((pair, timeframe, candle_type))
    
    # informative 时间周期
    if informative_pairs:
        for inf_pair, inf_tf, inf_ct in informative_pairs:
            pairs_to_load.add((inf_pair, inf_tf, inf_ct))
    
    loaded_count = 0
    total_count = len(pairs_to_load)
    
    if total_count == 0:
        return 0, 0
    
    logger.info(f"开始预加载 {total_count} 个数据集...")
    
    for pair, tf, ct in pairs_to_load:
        try:
            # 从磁盘加载数据
            df = data_handler.ohlcv_load(
                pair=pair,
                timeframe=tf,
                candle_type=ct,
                fill_missing=False,
                drop_incomplete=True,
                startup_candles=0,  # 加载所有可用数据
            )
            
            if df.empty:
                logger.debug(f"磁盘上没有数据: {pair} {tf} {ct}")
                continue
            
            # 检查数据是否太旧
            last_candle_time = df.iloc[-1]['date']
            now = datetime.now(timezone.utc)
            age_seconds = (now - last_candle_time).total_seconds()
            max_age_seconds = timeframe_to_seconds(tf) * 10  # 最多允许 10 个周期的延迟
            
            if age_seconds > max_age_seconds:
                logger.debug(
                    f"数据太旧,跳过预加载: {pair} {tf} "
                    f"(最后更新: {last_candle_time}, {age_seconds:.0f}秒前)"
                )
                continue
            
            # 加载到内存缓存
            exchange._klines[(pair, tf, ct)] = df
            
            # 记录最后刷新时间 (毫秒时间戳)
            last_ts = int(last_candle_time.timestamp() * 1000)
            exchange._pairs_last_refresh_time[(pair, tf, ct)] = last_ts
            
            loaded_count += 1
            
            logger.debug(
                f"预加载成功: {pair} {tf} {ct} "
                f"({len(df)} 根K线, 最后更新: {last_candle_time})"
            )
            
        except FileNotFoundError:
            logger.debug(f"文件不存在: {pair} {tf} {ct}")
        except Exception as e:
            logger.warning(f"预加载失败 {pair} {tf} {ct}: {e}")
    
    if loaded_count > 0:
        logger.info(
            f"✅ 数据预加载完成: {loaded_count}/{total_count} 个数据集 "
            f"({loaded_count/total_count*100:.1f}%)"
        )
    else:
        logger.info("⚠️ 未找到可用的历史数据,将从交易所下载")
    
    return loaded_count, total_count


def save_ohlcv_data(
    exchange: Exchange,
    config: Config,
    pairs: list[str] | None = None,
) -> int:
    """
    将内存中的 OHLCV 数据保存到磁盘
    
    参数:
        exchange: Exchange 实例
        config: 配置字典
        pairs: 要保存的交易对列表 (None = 保存所有)
    
    返回:
        保存的数据集数量
    """
    if not config.get("save_ohlcv_data", True):
        logger.debug("数据保存已禁用")
        return 0
    
    datadir = config.get("datadir")
    if not datadir:
        logger.warning("未配置 datadir,跳过数据保存")
        return 0
    
    data_format = config.get("dataformat_ohlcv", "feather")
    data_handler = get_datahandler(datadir, data_format)
    
    saved_count = 0
    
    for (pair, timeframe, candle_type), df in exchange._klines.items():
        # 如果指定了 pairs,只保存这些交易对
        if pairs and pair not in pairs:
            continue
        
        if df.empty:
            continue
        
        try:
            data_handler.ohlcv_store(
                pair=pair,
                timeframe=timeframe,
                data=df,
                candle_type=candle_type,
            )
            saved_count += 1
            logger.debug(f"保存数据: {pair} {timeframe} {candle_type} ({len(df)} 根K线)")
            
        except Exception as e:
            logger.warning(f"保存数据失败 {pair} {timeframe} {candle_type}: {e}")
    
    if saved_count > 0:
        logger.info(f"✅ 保存了 {saved_count} 个数据集到磁盘")
    
    return saved_count


def get_preload_statistics(exchange: Exchange) -> dict:
    """
    获取预加载统计信息
    
    返回:
        统计信息字典
    """
    total_pairs = len(exchange._klines)
    total_candles = sum(len(df) for df in exchange._klines.values())
    
    # 按时间周期分组
    by_timeframe: dict[str, int] = {}
    for (pair, timeframe, candle_type), df in exchange._klines.items():
        key = f"{timeframe} ({candle_type.value})"
        by_timeframe[key] = by_timeframe.get(key, 0) + 1
    
    return {
        "total_pairs": total_pairs,
        "total_candles": total_candles,
        "by_timeframe": by_timeframe,
    }

