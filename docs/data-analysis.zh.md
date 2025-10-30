# 使用 Jupyter Notebook 分析机器人数据

你可以借助 Jupyter Notebook 轻松分析回测结果与交易历史。初始化用户目录（`freqtrade create-userdir --userdir user_data`）后，示例笔记本会位于 `user_data/notebooks/`。

## 使用 Docker 快速上手

Freqtrade 提供了一个 docker-compose 文件，用于启动 Jupyter Lab 服务器。
运行命令 `docker compose -f docker/docker-compose-jupyter.yml up` 即可。

该命令会创建一个运行 Jupyter Lab 的容器，可通过 `https://127.0.0.1:8888/lab` 访问。请使用启动后控制台打印出的链接进行快捷登录。

更多信息请参阅[通过 Docker 进行数据分析](docker_quickstart.md#data-analysis-using-docker-compose)章节。

### 小提示

* 使用说明可参考 [jupyter.org](https://jupyter.org/documentation)。
* 别忘了在 Conda 或 venv 环境中启动 Notebook 服务器，或安装 [nb_conda_kernels](https://github.com/Anaconda-Platform/nb_conda_kernels)。
* 在修改示例 Notebook 前，先复制一份，避免下次更新 freqtrade 时被覆盖。

### 在系统级 Jupyter 中使用虚拟环境

若希望使用系统级的 Jupyter Notebook，同时使用虚拟环境中的内核，可按下列步骤操作。这能避免在同一台机器上多次安装完整的 Jupyter 套件，也方便在不同任务间切换。

首先激活虚拟环境，然后执行：

``` bash
source .venv/bin/activate

pip install ipykernel
ipython kernel install --user --name=freqtrade
# 重启 jupyter (lab / notebook)
# 在 Notebook 中选择 "freqtrade" 内核
```

!!! Note
    此章节旨在提供参考，Freqtrade 团队不会针对该方案提供完整支持。我们仍建议直接在虚拟环境内安装 Jupyter，这是最简单的方式。如需帮助，请查阅 [Project Jupyter](https://jupyter.org/) 的[文档](https://jupyter.org/documentation)或[社区支持渠道](https://jupyter.org/community)。

!!! Warning
    部分任务在 Notebook 中运行体验较差，例如使用异步执行的功能。此外，freqtrade 的主要入口是命令行界面，在 Notebook 中直接运行 Python 会绕过 CLI 参数，缺少某些帮助函数所需的对象和参数。你可能需要手动设置这些值或构造期望的对象。

## 推荐工作流程

| 任务 | 工具 |
  --- | ---
机器人运行 | CLI
重复性任务 | Shell 脚本
数据分析与可视化 | Notebook

1. 使用 CLI

    * 下载历史数据
    * 运行回测
    * 连接实时行情
    * 导出结果

1. 将这些操作整理成 Shell 脚本

    * 保存复杂命令及参数
    * 执行多步操作
    * 自动化测试策略并准备分析数据

1. 使用 Notebook

    * 可视化数据
    * 整理并绘制图表，挖掘洞察

## 实用代码片段

### 切换到项目根目录

Notebook 默认从所在目录执行。以下代码可搜索并切换至项目根目录，确保相对路径一致。

```python
import os
from pathlib import Path

# 切换目录
# 可以修改此单元以确保输出的路径正确
# 后续所有路径请相对于该项目根目录定义
project_root = "somedir/freqtrade"
i = 0
try:
    os.chdir(project_root)
    assert Path('LICENSE').is_file()
except:
    while i < 4 and (not Path('LICENSE').is_file()):
        os.chdir(Path(Path.cwd(), '../'))
        i += 1
    project_root = Path.cwd()
print(Path.cwd())
```

### 加载多个配置文件

该示例可以查看传入多个配置文件后的结果，同时会完整执行配置初始化，便于后续调用其他方法。

``` python
import json
from freqtrade.configuration import Configuration

# 从多个文件加载配置
config = Configuration.from_files(["config1.json", "config2.json"])

# 查看内存中的配置
print(json.dumps(config['original_config'], indent=2))
```

在交互式环境中，建议额外提供一个包含 `user_data_dir` 的配置文件，并在最后传入，这样就无需在运行机器人时手动切换目录。最好避免相对路径，因为 Notebook 默认从自身目录开始执行（除非你手动更改）。

``` json
{
    "user_data_dir": "~/.freqtrade/"
}
```

### 更多数据分析文档

* [策略调试](strategy_analysis_example.md) —— 也提供 Jupyter Notebook 示例 (`user_data/notebooks/strategy_analysis_example.ipynb`)
* [绘图](plotting.md)
* [标签分析](advanced-backtesting.md)

如果你有更好的数据分析想法，欢迎提交 Issue 或 Pull Request 来丰富本文档。
