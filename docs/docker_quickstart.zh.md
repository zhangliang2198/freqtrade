# 使用 Docker 运行 Freqtrade

本页说明如何借助 Docker 启动机器人。请注意，这并不是开箱即用的完整指南，你仍需阅读文档并正确配置。

## 安装 Docker

先在所在平台安装 Docker / Docker Desktop：

* [Mac](https://docs.docker.com/docker-for-mac/install/)
* [Windows](https://docs.docker.com/docker-for-windows/install/)
* [Linux](https://docs.docker.com/install/)

!!! Info "安装 docker compose"
    文档以 Docker Desktop（或 docker compose 插件）为基准。  
    如果使用独立的 `docker-compose` 可执行文件，需要把所有 `docker compose` 命令替换为 `docker-compose`（例如 `docker compose up -d` 改为 `docker-compose up -d`）。

??? Warning "Windows 上的 Docker"
    若刚在 Windows 上安装 Docker，请务必重启系统，否则可能出现容器网络异常等难以解释的问题。

## 使用 Docker 运行 Freqtrade

Freqtrade 在 [Docker Hub](https://hub.docker.com/r/freqtradeorg/freqtrade/) 提供官方镜像，并附带可直接使用的 [docker-compose.yml](https://github.com/freqtrade/freqtrade/blob/stable/docker-compose.yml)。

!!! Note
    * 下面的示例假设当前用户已安装并可直接使用 `docker`。
    * 所有命令都默认在包含 `docker-compose.yml` 的目录中执行。

### 快速上手

创建目录并下载 compose 文件：

``` bash
mkdir ft_userdata
cd ft_userdata/
curl https://raw.githubusercontent.com/freqtrade/freqtrade/stable/docker-compose.yml -o docker-compose.yml

docker compose pull
docker compose run --rm freqtrade create-userdir --userdir user_data
docker compose run --rm freqtrade new-config --config user_data/config.json
```

上述脚本会创建 `ft_userdata` 目录、下载最新的 compose 文件并拉取镜像。最后两步分别生成 `user_data` 目录和交互式配置文件。

!!! Question "如何修改机器人配置？"
    配置文件位于 `user_data/config.json`（在 `ft_userdata` 目录下）。你可以随时编辑该文件。  
    同时也可以修改 `docker-compose.yml` 中的命令部分来调整策略或运行模式。

#### 添加自定义策略

1. 配置文件位于 `user_data/config.json`
2. 将自定义策略复制到 `user_data/strategies/`
3. 在 `docker-compose.yml` 中的命令参数里填写策略类名

默认会运行 `SampleStrategy`。

!!! Danger "`SampleStrategy` 仅用于演示"
    示例策略仅用于参考，请务必先回测并在 Dry-run 模式中运行一段时间，再投入真实资金。更多内容请查阅[策略文档](strategy-customization.md)。

完成以上步骤后，即可启动机器人（根据配置运行 Dry-run 或实盘）：

``` bash
docker compose up -d
```

!!! Warning "默认配置"
    生成的默认配置基本可用，但仍需检查是否符合你的需求（价格源、交易对列表等）后再启动。

#### 访问 Web UI

如果在 `new-config` 步骤中启用了 FreqUI，那么默认可通过 `localhost:8080` 访问 UI。

??? Note "远程服务器的 UI 访问"
    在 VPS 上运行时，建议通过 SSH 隧道或 VPN（OpenVPN、WireGuard 等）访问，以避免直接暴露在公网。FreqUI 默认不提供 HTTPS。  
    请同时阅读[在 Docker 中配置 API](rest-api.md#configuration-with-docker)。

#### 监控机器人

使用 `docker compose ps` 查看容器状态；若未运行，可通过 `docker compose logs` 查看日志。

#### 日志

日志会被挂载到宿主机的 `user_data/logs` 目录，便于查看和持久化。

#### 更新镜像

若要获取最新镜像：

``` bash
docker compose pull
docker compose up -d
```

#### 通过 compose 执行其他命令

可以使用 `docker compose run --rm freqtrade <命令>` 运行任意 freqtrade 子命令，例如：

* 下载数据：`docker compose run --rm freqtrade download-data ...`
* 回测策略：`docker compose run --rm freqtrade backtesting ...`
* 查看命令帮助：`docker compose run --rm freqtrade --help`

!!! Warning
    `docker compose run` 会创建临时容器，请避免在其中运行需要长时间保持的交易实例。

!!! Note "`docker compose run --rm`"
    `--rm` 会在命令执行完毕后自动删除容器，除了实盘交易（持续运行的 `freqtrade trade`）外都建议加上。

??? Note "不使用 docker compose"
    某些无需认证的命令（如 `list-pairs`）可以直接使用 `docker run --rm`，例如：  
    `docker run --rm freqtradeorg/freqtrade:stable list-pairs --exchange binance --quote BTC --print-json`

#### 示例：下载数据

``` bash
docker compose run --rm freqtrade download-data --pairs ETH/BTC --exchange binance --days 5 -t 1h
```

数据会保存在宿主机的 `user_data/data/` 下。更多信息请参阅[数据下载文档](data-download.md)。

#### 示例：回测

``` bash
docker compose run --rm freqtrade backtesting --config user_data/config.json --strategy SampleStrategy --timerange 20190801-20191001 -i 5m
```

更多内容请参阅[回测文档](backtesting.md)。

### 在 Docker 中安装额外依赖

若策略需要默认镜像之外的依赖，请自建镜像。可参考 `docker/Dockerfile.custom`，创建包含新增依赖的 Dockerfile，然后在 `docker-compose.yml` 中取消注释 `build` 部分并修改镜像名称。构建命令：

``` bash
docker compose build --pull
```

### 绘图

如需使用 `freqtrade plot-profit`、`freqtrade plot-dataframe`，请在 compose 文件中改用带 `_plot` 的镜像标签。生成的图表会保存到 `user_data/plot`。

### 使用 docker-compose 进行数据分析

项目提供了一个专用于 Jupyter Lab 的 compose 文件：

``` bash
docker compose -f docker/docker-compose-jupyter.yml up
```

服务地址为 `https://127.0.0.1:8888/lab`。建议不时执行 `docker compose -f docker/docker-compose-jupyter.yml build --no-cache` 以获取最新依赖。

## 故障排除

### Windows 环境

* 错误 “Timestamp for this request is outside of the recvWindow.”：需要重启 WSL 与 Docker（`wsl --shutdown` 后重新启动 Docker Desktop），或改在 Linux 主机运行。
* 新安装 Docker 后无法连接：请重启系统，并确认 [UI 访问配置](#访问-web-ui) 是否正确。

!!! Warning
    基于上述原因，我们不建议在 Windows 上把 Docker 用于生产，仅适合实验、数据下载与回测。更可靠的做法是在 Linux VPS 上运行 Freqtrade。
