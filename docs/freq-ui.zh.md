# FreqUI

Freqtrade 内置 Web 服务器，可提供 [FreqUI](https://github.com/freqtrade/frequi) 前端界面。

默认情况下（无论脚本安装还是 Docker），都会自动安装 UI。也可以手动运行 `freqtrade install-ui` 安装或升级到最新版本。

当机器人以 `freqtrade trade` 进入实盘或 Dry-run 时，UI 会在配置的 API 端口（默认 `http://127.0.0.1:8080`）可用。

??? Note "想为 freqUI 做贡献？"
    开发者请直接按照 [freqUI 仓库](https://github.com/freqtrade/frequi) 中的步骤获取源码并构建，需要安装 Node.js。

!!! tip "运行 Freqtrade 不需要 freqUI"
    freqUI 只是一个方便监控与交互的前端，机器人本身无需 UI 也能正常工作。

## 配置

FreqUI 没有单独的配置文件，它依赖 [REST API](rest-api.md) 的正确配置。请参考相关章节完成设置后再启用 UI。

## 界面概览

FreqUI 是现代响应式 Web 应用，支持浅色/深色主题，可通过页面顶部按钮切换。文档中的截图会根据当前文档主题自动切换。

### 登录

首次访问会看到登录页：

![FreqUI - login](assets/frequi-login-CORS.png#only-dark)
![FreqUI - login](assets/frequi-login-CORS-light.png#only-light)

!!! Hint "CORS"
    如果 UI 与 API 不同源，则需正确配置 [CORS](#cors)，否则浏览器会提示跨域错误。

### 交易视图

交易视图可展示实时仓位、订单与历史交易，还能执行常用操作（启动/停止机器人、强制开仓/平仓等）。

![FreqUI - trade view](assets/freqUI-trade-pane-dark.png#only-dark)
![FreqUI - trade view](assets/freqUI-trade-pane-light.png#only-light)

### 绘图配置器

可通过策略中的 `plot_config` 或 UI 内置的“Plot Configurator”（齿轮按钮）自定义图表。你可以保存多个配置，用于不同的视角。

![FreqUI - plot configuration](assets/freqUI-plot-configurator-dark.png#only-dark)
![FreqUI - plot configuration](assets/freqUI-plot-configurator-light.png#only-light)

### 设置

设置页面提供部分 UI 选项，例如：

* 时区
* 浏览器标签页的持仓指示
* 蜡烛颜色（上涨/下跌）
* 各类通知的启用与关闭

![FreqUI - Settings view](assets/frequi-settings-dark.png#only-dark)
![FreqUI - Settings view](assets/frequi-settings-light.png#only-light)

## Webserver 模式

当以 [webserver 模式](utils.md#webserver-mode) 启动（`freqtrade webserver`）时，UI 会解锁更多功能，例如：

* 数据下载
* 交易对列表测试
* [回测策略](#backtesting)
* 后续还会扩展更多工具

### 回测界面

在 webserver 模式下，UI 提供图形化的回测面板，可执行回测、查看结果并对比历史回测数据。

![FreqUI - Backtesting](assets/freqUI-backtesting-dark.png#only-dark)
![FreqUI - Backtesting](assets/freqUI-backtesting-light.png#only-light)

--8<-- "includes/cors.md"
