# BaseStrategyWithSnapshot：让量化策略更智能的增强基类

## 📖 概述

[`BaseStrategyWithSnapshot`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py) 是基于 Freqtrade 原生 [`IStrategy`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/interface.py) 接口的增强策略基类，为量化交易策略提供了**资产统计、账户分离、黑名单管理**等企业级功能。如果你正在使用 Freqtrade 进行量化交易，这个基类可以让你的策略更加专业和可控。

本基类为策略提供：
- 📊 **资金快照**：每个 bot 循环记录资金状态（可配置频率），并写入数据库；
- 💰 **账户分离**：按方向（Long/Short）划分可用"预算"，分别统计盈亏与占用；
- 🚫 **严格额度限制**：当某方向预算不足时，阻止继续为该方向开新仓；
- 🎯 **黑名单管理**：Long/Short 分离的黑名单过滤；
- 🔧 **智能适配**：不同运行模式（实盘、DryRun、回测、Hyperopt）自动优化性能。

---

## 🆚 核心区别对比

### **原生 IStrategy**
- ✅ 提供基础的策略框架（入场/出场信号生成）
- ✅ 支持技术指标计算
- ✅ 支持做多/做空
- ❌ **没有资产跟踪功能**
- ❌ **没有账户分离管理**
- ❌ **没有详细的资金日志**
- ❌ **没有数据持久化**

### **BaseStrategyWithSnapshot**
- ✅ **继承所有 IStrategy 功能**
- ✅ **自动统计资产变化**（Long/Short 分离统计）
- ✅ **账户余额分离管理**（严格限制 Long/Short 资金使用）
- ✅ **详细的资金日志输出**
- ✅ **[资金快照数据库存储](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/persistence/strategy_snapshot.py)**
- ✅ **Long/Short 黑名单分离过滤**
- ✅ **智能运行模式检测**（回测/优化/实盘自动适配）

---

## 1. 快速上手配置

在全局配置或独立文件（参考 [`config_examples/strategy_account_config.example.json`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/config_examples/strategy_account_config.example.json)）中添加：

```json
{
  "strategy_account": {
    "enabled": true,
    "use_ratio": true,
    "long_ratio": 1,
    "short_ratio": 1
  },
  "strategy_snapshot": {
    "enabled": true,
    "enable_detailed_logs": true,
    "enable_strategy_logs": true,
    "snapshot_frequency": 1
  },
  "strategy_blacklist": {
    "enabled": true,
    "long_blacklist": ["BTC/USDT:USDT"],
    "short_blacklist": ["DOGE/.*"],
    "common_blacklist": [".*BULL/.*", ".*BEAR/.*"]
  }
}
```

**配置说明**（参考 [`__init__()` 方法](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L41-L175)）：
- 当 `use_ratio = true` 时，忽略具体金额，按比例拆分总初始资金；如 `1 : 1` 即 50%/50%。
- 如需固定金额，设 `use_ratio = false` 并提供 `long_initial_balance` / `short_initial_balance`。
- 黑名单支持正则表达式匹配，可分别为 Long/Short 设置不同规则。

---

## 2. 账户分离的核心概念

"账户分离"并不改变钱包余额，而是为 Long 与 Short 各自设定一个"预算池"（通过 [`get_account_available_balance()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L407-L478) 实现）。

每个方向单独累计三类量：
  1. **初始资金**（预算上限的起点）
  2. **已平仓盈亏**（盈利增加预算、亏损减少预算）
  3. **当前持仓占用**（含加仓后的最大占用）

---

## 3. 可用余额计算公式（方向维度）

可用余额（Available）按方向计算：

```
Available = 初始资金 + 已平仓盈亏 − 当前持仓占用
```

- 若 `Available > 0`：该方向仍有预算，可继续开仓（受其他限额与风控约束）。
- 若 `Available ≤ 0`：该方向预算已用尽或透支，将阻止继续开新仓。

注意：这是“预算”的可用额度，并非交易所“钱包可用余额”。

---

## 4. 日志里的“可用余额为负”是什么意思？

当 `Available < 0` 时，日志会给出提示，例如：

```
⚠️ LONG 账户可用余额为负: -53.94 USDT (初始: 4950.00,
已平仓盈亏: -193.94 [盈利: 0.00, 亏损: -193.94], 持仓占用: 4810.01)
```

含义：按“方向预算”核算后，当前持仓占用已超过该方向可用预算，处于“透支”状态。
这常见于：
- 该方向出现了一些亏损（降低预算），但仍有较大的未平仓持仓；
- 或者存在加仓（DCA/摊平），占用被放大；
- 杠杆方向下，占用与盈亏的幅度更敏感。

重要：框架在实际使用时会将该值钳制为非负数（`max(0.0, Available)`），也就是“最多就是 0”。
因此虽然日志提示为负，但不会用“负值”参与下单决策；表现为“该方向不再允许开新仓”。

---

## 5. 如何减少/避免出现负数提示

- 提高该方向的初始预算：
  - 比例模式：调整 `long_ratio` / `short_ratio`；
  - 金额模式：设置更高的 `long_initial_balance` / `short_initial_balance`。
- 降低单笔开仓规模与并发：
  - 调小 stake、减少同时持仓数、降低/限制加仓层数与幅度；
- 限制方向性风险：
  - 给策略加方向黑名单、限制某方向入场频率；
- 若不需要严格分离：
  - 设 `strategy_account.enabled = false`，回到传统“统一钱包”模式（不再按方向拆分预算）。

---

## 6. 与钱包余额的关系

- 钱包余额始终来自 `wallets.get_total("USDT")`（实盘/回测/DryRun/Hyperopt 统一行为）。
- 方向预算只是“内部分账”逻辑，不会让钱包真的变成负数。

---

## 7. 常见问答（FAQ）

- Q：日志出现负数，是不是系统算错了？
  - A：不是。那是“方向预算”的核算结果，用于提示与限额控制；实际决策会把负数视为 0。
- Q：为什么明明钱包还有钱，却提示该方向不能开仓？
  - A：因为开启了“账户分离”，该方向的预算已用尽（或已被亏损压缩），尽管钱包仍有余额。
- Q：`use_ratio = true` 且 `long_ratio = 1, short_ratio = 1` 是什么意思？
  - A：按比例归一化后，即 Long/Short 各占 50% 初始预算。

---

## 8. 核心功能详解

### **8.1 自动资产统计与跟踪**

每个交易循环自动计算（通过 [`bot_loop_start()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L177-L240) 方法）：

- 📊 **Long 账户资产**：初始资金、持仓金额、浮动盈亏、已实现盈亏
- 📊 **Short 账户资产**：独立统计做空账户的所有数据
- 💰 **总资产统计**：钱包余额、总盈利率、持仓订单数

**核心方法**：

- [`_get_detailed_assets()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L242-L358) - 计算详细资产情况
- [`get_assets_in_usdt()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L620-L637) - 获取资产统计（兼容旧版本）

### **8.2 资金快照数据库存储**

所有资产数据自动保存到数据库 [`strategy_snapshot`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/persistence/strategy_snapshot.py) 表（通过 [`_save_snapshot()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L388-L405) 方法）。

**应用场景**：

- 📈 Grafana 可视化监控
- 📊 策略表现回溯分析
- 🔍 异常情况排查

### **8.3 Long/Short 黑名单分离**

**核心方法**（参考 [`__init__()` 黑名单配置](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L126-L138)）：

- [`is_pair_blacklisted(pair, side)`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L538-L560) - 检查交易对是否在黑名单
- [`advise_entry()`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L562-L597) - 自动过滤入场信号

**特性**：

- ✅ 支持正则表达式匹配
- ✅ 在 `advise_entry` 阶段自动过滤信号
- ✅ 子类无需手动处理黑名单逻辑

### **8.4 智能运行模式适配**

代码会自动检测运行模式并调整行为（参考 [`__init__()` 模式检测](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L41-L124)）：

| 模式 | 快照默认 | 日志默认 | 频率 |
|------|---------|---------|------|
| **Hyperopt** | ❌ 禁用 | ❌ 禁用 | 100 次/快照 |
| **Backtest** | ✅ 启用 | ✅ 启用 | 10 次/快照 |
| **实盘/模拟** | ✅ 启用 | ✅ 启用 | 每次循环 |

**好处**：

- 🚀 Hyperopt 优化时避免海量日志拖慢速度
- 📊 回测时保持详细记录但控制频率
- 💼 实盘时获得最完整的监控信息

### **8.5 子类扩展接口**

提供两个钩子方法，让子类添加自定义逻辑：

```python
class MyStrategy(BaseStrategyWithSnapshot):
    
    def get_extra_snapshot_data(self, asset_data):
        """添加策略特定的数据到快照"""
        return {
            "my_indicator": self.my_custom_value,
            "signal_strength": self.calculate_strength()
        }
    
    def log_strategy_specific_info(self, current_time, asset_data, **kwargs):
        """输出策略特定的日志"""
        logger.info(f"当前信号强度: {self.signal_strength}")
```

**扩展方法**：

- [`get_extra_snapshot_data(asset_data)`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L599-L607) - 返回自定义快照数据
- [`log_strategy_specific_info(current_time, asset_data)`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py#L609-L618) - 输出策略特定日志

---

## 9. 相关文件链接

- **策略基类实现**：[`BaseStrategyWithSnapshot.py`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/BaseStrategyWithSnapshot.py)
- **快照数据模型**：[`strategy_snapshot.py`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/persistence/strategy_snapshot.py)
- **原生接口**：[`IStrategy`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/freqtrade/strategy/interface.py)
- **配置示例**：[`strategy_account_config.example.json`](https://github.com/zhangliang2198/freqtrade/blob/feature/grafana_prometheus/config_examples/strategy_account_config.example.json)

---

## 10. 使用示例

### **基础使用**

```python
from freqtrade.strategy.BaseStrategyWithSnapshot import BaseStrategyWithSnapshot

class MyAwesomeStrategy(BaseStrategyWithSnapshot):
    
    def populate_indicators(self, dataframe, metadata):
        # 正常编写指标
        dataframe['rsi'] = ta.RSI(dataframe)
        return dataframe
    
    def populate_entry_trend(self, dataframe, metadata):
        # 正常生成入场信号（黑名单会自动过滤）
        dataframe.loc[
            (dataframe['rsi'] < 30),
            'enter_long'] = 1
        
        dataframe.loc[
            (dataframe['rsi'] > 70),
            'enter_short'] = 1
        return dataframe
    
    def populate_exit_trend(self, dataframe, metadata):
        # 正常生成出场信号
        dataframe.loc[
            (dataframe['rsi'] > 50),
            'exit_long'] = 1
        
        dataframe.loc[
            (dataframe['rsi'] < 50),
            'exit_short'] = 1
        return dataframe
```

---

## 11. 总结

`BaseStrategyWithSnapshot` 在保持 `IStrategy` 全部能力的基础上，新增了：

| 功能 | 价值 | 相关方法 |
|-----|-----|---------|
| 📊 资产统计 | 实时掌握 Long/Short 账户盈亏 | `_get_detailed_assets()` |
| 💰 账户分离 | 严格控制资金使用，降低风险 | `get_account_available_balance()` |
| 💾 数据持久化 | 支持监控、回溯、分析 | `_save_snapshot()` |
| 🚫 黑名单管理 | 灵活过滤不适合的交易对 | `is_pair_blacklisted()` |
| 🎯 智能适配 | 不同运行模式自动优化性能 | 自动检测 `RunMode` |
| 🔧 可扩展性 | 子类轻松添加自定义功能 | `get_extra_snapshot_data()` |

**一句话总结**：它让你的量化策略从"能跑"升级到"好管理、可监控、易分析"的专业级水平！

---

## 12. 更多文档

- [Freqtrade 官方文档](https://www.freqtrade.io/)
- [策略开发指南](https://www.freqtrade.io/en/stable/strategy-customization/)
- [数据分析文档](https://www.freqtrade.io/en/stable/data-analysis/)

---

*最后更新：2025年11月17日*
