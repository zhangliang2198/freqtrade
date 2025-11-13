# BaseStrategyWithSnapshot 使用说明（资金快照 + Long/Short 账户分离）

本基类为策略提供：
- 资金快照：每个 bot 循环记录资金状态（可配置频率），并写入数据库；
- 账户分离：按方向（Long/Short）划分可用“预算”，分别统计盈亏与占用；
- 严格额度限制：当某方向预算不足时，阻止继续为该方向开新仓。

适用场景：实盘、DryRun、回测、Hyperopt（默认在 Hyperopt 降噪日志与快照频率）。

---

## 1. 快速上手配置

在全局配置或独立文件（例如 `user_data/accounts.json`）中添加：

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
  }
}
```

说明：
- 当 `use_ratio = true` 时，忽略具体金额，按比例拆分总初始资金；如 `1 : 1` 即 50%/50%。
- 如需固定金额，设 `use_ratio = false` 并提供 `long_initial_balance` / `short_initial_balance`。
- 示例配置详见 `config_examples/strategy_account_config.example.json`。

---

## 2. 账户分离的核心概念

- “账户分离”并不改变钱包余额，而是为 Long 与 Short 各自设定一个“预算池”。
- 每个方向单独累计三类量：
  1) 初始资金（预算上限的起点）
  2) 已平仓盈亏（盈利增加预算、亏损减少预算）
  3) 当前持仓占用（含加仓后的最大占用）

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

## 8. 相关文件

- 策略基类实现：`freqtrade/strategy/BaseStrategyWithSnapshot.py`
- 快照模型：`freqtrade/persistence/strategy_snapshot.py`
- 配置示例：`config_examples/strategy_account_config.example.json`
- 示例策略：`user_data/strategies/ExampleStrategyWithAccountLimit.py`

