# 开发者指南

本文面向希望参与 Freqtrade 开发、贡献文档，或想深入了解自身部署版本的开发者。

欢迎提交任何贡献、问题报告、修复、文档改进、优化与新想法。我们在 [GitHub Issues](https://github.com/freqtrade/freqtrade/issues) 追踪问题，并在 [Discord](https://discord.gg/p7nuUNVfP7) 设有开发频道供提问交流。

## 文档

官方文档托管于 [https://freqtrade.io](https://www.freqtrade.io/)，所有新功能 PR 都应附带文档更新。

常用的文档注释（如 Note 框）可参考 [Material for MkDocs 提示样式](https://squidfunk.github.io/mkdocs-material/reference/admonitions/)。

如需本地预览文档，可执行：

``` bash
pip install -r docs/requirements-docs.txt
mkdocs serve
```

命令会启动本地服务（默认在 8000 端口），方便检查最终呈现效果。

## 开发环境配置

你可以使用以下方式准备开发环境：

* 使用 [DevContainer](#devcontainer-setup)；
* 运行 `setup.sh` 并在提示 “Do you want to install dependencies for dev [y/N]?” 时回答 “y”；
* 或者按照手动安装流程，执行 `pip3 install -r requirements-dev.txt`，然后运行 `pip3 install -e .[all]`。

上述步骤会安装开发所需的工具，包括 `pytest`、`ruff`、`mypy`、`coveralls` 等。

随后运行 `pre-commit install` 安装 Git Hook，这样在提交前会自动执行基础检查，避免等待 CI 才发现格式或 lint 问题。

在提交 Pull Request 之前，请先阅读我们的[贡献指南](https://github.com/freqtrade/freqtrade/blob/develop/CONTRIBUTING.md)。

### DevContainer 配置

最简单的上手方式是使用 [VSCode](https://code.visualstudio.com/) 搭配 Remote Container 插件。这样无需在本地安装 Freqtrade 依赖即可启动完整开发环境。

#### DevContainer 依赖

* [VSCode](https://code.visualstudio.com/)
* [Docker](https://docs.docker.com/install/)
* [Remote Container 插件文档](https://code.visualstudio.com/docs/remote)

更多细节可参考 Remote Container 官方文档。

## 测试

新增代码应至少覆盖基础单元测试。若功能较复杂，Reviewers 可能会要求更完善的测试。Freqtrade 团队可以提供写测试的指导，但不会代写。

### 运行测试

在项目根目录执行 `pytest` 即可运行所有测试，并确认本地环境配置无误。

!!! Note "特性分支"
    测试需要在 `develop` 与 `stable` 分支上保持通过。其他临时分支可能仍在开发中，测试未必通过。

### 检查日志内容

测试中检查日志常用 `log_has()` 与 `log_has_re()`（后者支持正则匹配动态内容）。这两个工具定义于 `tests/conftest.py`，可在任意测试模块中导入。

``` python
from tests.conftest import log_has, log_has_re

def test_method_to_test(caplog):
    method_to_test()

    assert log_has("This event happened", caplog)
    assert log_has_re(r"This dynamic event happened and produced \d+", caplog)
```

## 调试配置

推荐使用安装了 Python 插件的 VSCode，通过 `.vscode/launch.json` 添加如下配置：

``` json
{
    "name": "freqtrade trade",
    "type": "debugpy",
    "request": "launch",
    "module": "freqtrade",
    "console": "integratedTerminal",
    "args": [
        "trade",
        // Optional:
        // "--userdir", "user_data",
        "--strategy",
        "MyAwesomeStrategy"
    ]
}
```

可以在 `"args"` 中加入任意命令行参数，并在策略中设置断点进行调试。

Pycharm 也可采用类似配置：模块名设置为 `freqtrade`，参数填入命令行参数即可。

??? Tip "正确使用虚拟环境"
    推荐始终在虚拟环境中开发，并确保编辑器使用正确的解释器，避免报错或模块缺失。

    #### VSCode

    通过“Python: Select Interpreter”命令选择虚拟环境；若未检测到，可手动指定路径。

    #### Pycharm

    在 “Run/Debug Configurations” 中选择合适的解释器。  
    ![Pycharm debug configuration](assets/pycharm_debug.png)

!!! Note "启动目录"
    上述配置假定你在仓库根目录打开项目（`pyproject.toml` 与仓库同级）。

## 异常处理

Freqtrade 自定义的异常均继承自 `FreqtradeException`，不应直接使用该基类，而应使用更具体的子类。层级结构如下：

```
FreqtradeException
├─ OperationalException
│  └─ ConfigurationError
├─ DependencyException
│  ├─ PricingError
│  └─ ExchangeError
│     ├─ TemporaryError
│     ├─ DDosProtection
│     └─ InvalidOrderException
│        ├─ RetryableOrderError
│        └─ InsufficientFundsError
└─ StrategyError
```

## 插件

### Pairlists

想实现新的交易对筛选逻辑？可以参考 [VolumePairList](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/plugins/pairlist/VolumePairList.py) 的实现，并以此为模板创建自己的 Handler。

将类名与文件名保持一致，基类会提供以下属性：

```python
self._exchange
self._pairlistmanager
self._config
self._pairlistconfig
self._pairlist_pos
```

!!! Tip
    别忘了在 `constants.py` 中的 `AVAILABLE_PAIRLISTS` 注册新 Handler，否则无法选用。

#### Pairlist 配置

在配置文件中，`"pairlists"` 是一个数组，用于按顺序定义多个 Pairlist Handler。一般使用 `"number_assets"` 指定最大交易对数量。

#### `short_desc`

返回给 Telegram 消息使用的描述，例如 `"VolumePairList - top 10 pairs"`。

#### `gen_pairlist`

若 Handler 位于链条首位，可通过该方法生成初始交易对列表。该方法在每次主循环调用，若计算量大可考虑缓存。必要时可调用 `verify_blacklist()` 或 `_whitelist_for_active_markets()` 做基础筛选。

#### `filter_pairlist`

该方法对传入的交易对列表进行过滤（链式执行）。默认实现会对每个交易对调用 `_validate_pair()`，你可以重写该方法或 `_validate_pair()`。如果重写，请返回过滤后的交易对列表。

##### 示例

``` python
def filter_pairlist(self, pairlist: list[str], tickers: dict) -> List[str]:
    pairs = self._calculate_pairlist(pairlist, tickers)
    return pairs
```

### Protections

开发新保护机制前，建议先阅读[相关文档](plugins.md#protections)。实现时应继承 `IProtection`，并实现：

* `short_desc()`
* `global_stop()`
* `stop_per_pair()`

上述方法需返回 `ProtectionReturn` 对象，包含：

* `lock_pair`：是否锁定交易对
* `lock_until`：锁定到期时间（会向上取整到下一根蜡烛）
* `reason`：原因描述
* `lock_side`：`long` / `short` / `*`

锁定时间建议使用基类提供的 `calculate_lock_end()` 计算。

保护应支持 `"stop_duration"` / `"stop_duration_candles"` 来定义持续时间；若需要回溯数据，请使用 `"lookback_period"` / `"lookback_period_candles"`。

#### 局部与全局锁定

* **局部保护（per pair）**：设置 `has_local_stop=True`，`stop_per_pair()` 会在交易平仓后触发。
* **全局保护（global）**：设置 `has_global_stop=True`，`global_stop()` 会在任意交易平仓后触发，锁定全部交易对。

## 接入新交易所（WIP）

!!! Note
    本章节仍在完善中，仅提供接入新交易所的思路。

!!! Note
    在测试前，请确保使用最新版本的 CCXT。

常规检查包括：

* 拉取市场与钱包余额（无需 API Key）
* 获取历史 K 线（包含多个时间框架）
* 获取订单薄
* 创建/取消订单（需要 API Key 与余额）
* 完整交易流程（开仓与平仓），比对交易所与机器人统计结果（尤其是手续费）

### 交易所止损

由于 CCXT 尚未统一交易所止损参数，需要针对特定交易所手动实现。可以参考 `binance.py`，并查阅交易所 API 文档或 [CCXT Issues](https://github.com/ccxt/ccxt/issues) 获取思路。

### 不完整蜡烛

某些交易所返回的最后一根蜡烛可能未收盘，需在导入前丢弃。可以使用以下脚本检测：

``` python
import ccxt
from datetime import datetime, timezone
from freqtrade.data.converter import ohlcv_to_dataframe

ct = ccxt.binance()  # 替换为目标交易所
timeframe = "1d"
pair = "BTC/USDT"
raw = ct.fetch_ohlcv(pair, timeframe=timeframe)

df1 = ohlcv_to_dataframe(raw, timeframe, pair=pair, drop_incomplete=False)

print(df1.tail(1))
print(datetime.now(timezone.utc))
```

如果末尾蜡烛与当前日期相同（或多次运行时成交量变化），说明未收盘，应保持默认 `ohlcv_partial_candle=True`，丢弃最后一根蜡烛；否则可设置为 `False`。

### 更新 Binance 杠杆档位缓存

``` python
import ccxt
import json
from pathlib import Path

exchange = ccxt.binance({
    'apiKey': '<apikey>',
    'secret': '<secret>',
    'options': {'defaultType': 'swap'}
})
_ = exchange.load_markets()

lev_tiers = exchange.fetch_leverage_tiers()

file = Path('freqtrade/exchange/binance_leverage_tiers.json')
json.dump(dict(sorted(lev_tiers.items())), file.open('w'), indent=2)
```

请将更新后的文件提交至上游仓库，以便他人使用。

## 更新示例 Notebook

当你修改示例 Notebook 时，为保持与文档同步，请运行：

``` bash
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --inplace freqtrade/templates/strategy_analysis_example.ipynb
jupyter nbconvert --ClearOutputPreprocessor.enabled=True --to markdown freqtrade/templates/strategy_analysis_example.ipynb --stdout > docs/strategy_analysis_example.md
```

## 回测文档结果

生成回测输出可使用以下命令：

``` bash
freqtrade create-userdir --userdir user_data_bttest/
sed -i "s/can_short: bool = False/can_short: bool = True/" user_data_bttest/strategies/sample_strategy.py

freqtrade download-data --timerange 20250625-20250801 --config tests/testdata/config.tests.usdt.json --userdir user_data_bttest/ -t 5m

freqtrade backtesting --config tests/testdata/config.tests.usdt.json -s SampleStrategy --userdir user_data_bttest/ --cache none --timerange 20250701-20250801
```

## 持续集成

CI 设计要点：

* 运行环境覆盖 Linux（Ubuntu）、macOS、Windows；
* `stable` 与 `develop` 分支均构建多架构 Docker 镜像；
* 带 Plot 依赖的镜像另以 `stable_plot`、`develop_plot` 提供；
* 镜像内包含 `/freqtrade/freqtrade_commit` 文件记录当前提交；
* 每周定时全量重建镜像；
* 部署在 Ubuntu 上执行；
* 提交合并到 `stable` 或 `develop` 前必须通过全部测试。

## 发布流程

以下内容主要面向维护者。

### 创建发布分支

!!! Note
    确保 `stable` 分支已更新到最新状态。

1. 选取大约一周前的提交（避免包含最新实验特性），创建发布分支：

    ``` bash
    git checkout -b new_release <commitid>
    ```

2. 若期间有关键修复，可在新分支上 cherry-pick。
3. 将 `stable` 合并到新分支，更新 `freqtrade/__init__.py` 中的版本号（遵循 PEP440，按日期命名，如 `2019.7`、`2019.7.1` 等）。
4. 推送分支并向 **stable 分支** 提交 PR。
5. 将 `develop` 分支版本号更新为下一阶段（例如 `2019.8-dev`）。

### 根据提交生成变更日志

``` bash
git log --oneline --no-decorate --no-merges stable..new_release
```

可将完整日志嵌入 `<details>` 标签，便于折叠显示。

### FreqUI 发布

若 FreqUI 有较大改动，请在合并发布分支前创建对应 Release，并确保其 CI 通过。

### 创建 GitHub Release/Tag

当 PR 合并进 `stable` 后：

1. 在 GitHub “Releases” 页面点击 “Draft a new release”；
2. Tag 使用新版本号，目标分支选择 `stable`；
3. 将上述变更日志（建议使用代码块格式）填入描述；
4. 参考 Release 模板（`--8<-- "includes/release_template.md"`）补充说明。

## 发布渠道

### PyPI

!!! Warning "手动发布"
    正式发布流程已由 GitHub Actions 自动化，通常无需手动操作。

??? example "手动发布示例"
    如需手动发布，可执行：

    ``` bash
    pip install -U build
    python -m build --sdist --wheel

    # 测试环境
    twine upload --repository-url https://test.pypi.org/legacy/ dist/*

    # 正式环境
    twine upload dist/*
    ```

    请勿将非正式版本上传至正式 PyPI 仓库。
