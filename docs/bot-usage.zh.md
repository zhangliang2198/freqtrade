# 启动机器人

本页解释机器人的各项参数以及如何运行它。

!!! Note
    如果你通过 `setup.sh` 安装，不要忘记在运行 freqtrade 命令前激活虚拟环境（`source .venv/bin/activate`）。

!!! Warning "系统时钟需保持同步"
    运行机器人的系统时钟必须准确，并且频繁与 NTP 服务器同步，否则会影响与交易所的通信。

## 机器人指令

--8<-- "commands/main.md"

### 交易相关指令

--8<-- "commands/trade.md"

### 如何指定使用哪个配置文件？

可以通过 `-c/--config` 命令行参数指定机器人使用的配置文件：

```bash
freqtrade trade -c path/far/far/away/config.json
```

默认情况下，机器人会从当前工作目录加载 `config.json`。

### 如何使用多个配置文件？

你可以在命令行中指定多个 `-c/--config` 参数来使用多个配置文件。
后面配置文件中定义的参数会覆盖前面配置文件中同名参数的值。

例如，你可以为真实交易的交易所密钥单独保存一个配置文件，而在 Dry 模式下（不需要真实密钥）使用默认配置文件并保留空的密钥字段：

```bash
freqtrade trade -c ./config.json
```

实盘模式下，则同时指定两个配置文件：

```bash
freqtrade trade -c ./config.json -c path/to/secrets/keys.config.json
```

通过这种方式，可以在本地机器上为包含真实密钥的文件设置合适的权限，保护交易所 API Key 与 Secret，同时也能避免在向项目问题区或网络上分享配置示例时无意泄露敏感信息。

更多示例可参考文档中的[配置文件](configuration.md)章节。

### 自定义数据应存放在哪里？

可以通过 `freqtrade create-userdir --userdir someDirectory` 创建 `user_data` 目录，结构如下：

```
user_data/
├── backtest_results
├── data
├── hyperopts
├── hyperopt_results
├── plot
└── strategies
```

你可以在配置文件中添加 `user_data_dir` 设置，让机器人始终指向该目录；或者在每个命令中传入 `--userdir`。
如果目录不存在，机器人会启动失败，但会自动创建所需的子目录。

该目录应包含你的自定义策略、自定义 hyperopt 与 hyperopt 损失函数、回测历史数据（可以通过回测命令或下载脚本获取）以及绘图输出等。

建议使用版本控制来跟踪策略的变更。

### 如何使用 **--strategy**？

该参数用于加载自定义策略类。
若需测试安装是否成功，可使用 `create-userdir` 子命令安装的 `SampleStrategy`（通常位于 `user_data/strategy/sample_strategy.py`）。

机器人会在 `user_data/strategies` 中查找策略文件。若需使用其他目录，请参考下一节 `--strategy-path`。

只需在该参数中传入策略类名即可加载策略（例如 `CustomStrategy`）。

**示例：**在 `user_data/strategies` 中存在策略文件 `my_awesome_strategy.py`，其中包含策略类 `AwesomeStrategy`，则可通过以下命令加载：

```bash
freqtrade trade --strategy AwesomeStrategy
```

如果未找到策略文件，机器人会在错误信息中说明原因（文件不存在或代码出错）。

关于策略文件的更多信息，请参阅[策略自定义](strategy-customization.md)。

### 如何使用 **--strategy-path**？

该参数可以添加额外的策略搜索路径（必须是目录），并在默认路径之前进行查找：

```bash
freqtrade trade --strategy AwesomeStrategy --strategy-path /some/directory
```

#### 如何安装策略？

非常简单。将策略文件复制到 `user_data/strategies` 目录中，或使用 `--strategy-path` 指定路径，机器人即可使用。

### 如何使用 **--db-url**？

Dry-run 模式下默认不会将交易写入数据库。如果希望记录机器人行为，可以使用 `--db-url` 指定数据库，也可以在实盘模式下指定自定义数据库。例如：

```bash
freqtrade trade -c config.json --db-url sqlite:///tradesv3.dry_run.sqlite
```

## 下一步

机器人的最佳策略会随着市场趋势变化而变化。下一步是前往[策略自定义](strategy-customization.md)章节。
