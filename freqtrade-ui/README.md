# freqtrade-ui

一个独立的 **Freqtrade** 交易控制台，用 React + TypeScript + Vite + [Semi Design](https://semi.design) 重写了 [freqUI](https://github.com/freqtrade/frequi) 的全部功能页面。

- **黑白两种主题**：灰阶承担全部结构层次，彩色只留给“有符号的数据”（盈亏、多空）和“状态”（运行/暂停/停止、干跑/实盘）。
- **高信息密度**：小号控件、紧凑行距、等宽数字（`ft-num`）、22px 图标块划分区块。
- **直连 8081 REST API**：不依赖 freqtrade 内置的静态 UI，可独立部署。

---

## 快速开始

```bash
cd freqtrade-ui
env -u npm_config_allow_scripts -u npm_config_local_prefix npm install
npm run dev
```

打开 <http://127.0.0.1:5273>，在登录页填写：

| 字段 | 示例 |
| --- | --- |
| 名称 | `main` |
| API 地址 | `http://127.0.0.1:8081` |
| 用户名 / 密码 | `api_server.username` / `api_server.password` |

多个机器人可以同时保存，在顶栏下拉切换。凭据与 JWT 只存在浏览器 `localStorage`。

### 跨域：两条路，选一条

浏览器直连 8081 需要后端放行本页面的来源。二选一：

**A. 配置后端 CORS**（改一次，永久生效）—— 在 freqtrade 配置的 `api_server` 中加：

```json
"CORS_origins": ["http://localhost:5273", "http://127.0.0.1:5273"]
```

改完需要重启 freqtrade。

**B. 用开发服务器代理**（无需重启机器人，推荐用于实盘）—— 所有请求变成同源：

```bash
VITE_USE_PROXY=true VITE_PROXY_TARGET=http://127.0.0.1:8081 npm run dev
```

此时 API 地址填 `http://127.0.0.1:5273`（代理会转发 `/api` 到 8081，包括 WebSocket）。

---

## 构建

```bash
npm run build      # 产出 dist/
npm run preview    # 本地预览构建结果
```

`dist/` 是纯静态文件，可以用任何 web server 托管。若与 freqtrade 同域部署，把 `dist/`
放到 `api_server` 能访问的路径下即可；若跨域部署，记得同时配置 `CORS_origins`。

环境变量（构建期）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | `http://127.0.0.1:8081` | 登录页 API 地址的默认值 |
| `VITE_USE_PROXY` | – | `true` 时开发服务器代理 `/api` |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8081` | 代理目标 |

---

## 校验脚本

需要先起开发服务器（脚本默认访问 `http://127.0.0.1:5273`），并保证
`http://127.0.0.1:8081` 上有可登录的机器人。

```bash
export SMOKE_USER='<api_server.username>'
export SMOKE_PASSWORD='<api_server.password>'
npm run smoke        # 走完全部 15 条路由，检查白屏 / 控制台报错
npm run audit        # 测量渲染后的计算样式，校验配色与信息密度
npm run shots        # 输出 8 页 × 深浅两主题的截图到 /tmp/ftui-shots
```

`npm run audit` 是这套黑白设计的回归防线：它遍历可见节点，把所有绘制出来的颜色
分成「无彩色」和「语义色」两类，任何第三种有彩色都会判 FAIL 并列出具体色值与属性。
语义色只允许 8 个：`--ft-up/-down/-warn/-info` 及其 `-bg`。

`npm run structure` 在 2040px 视口下逐页报告页面宽度占比、每个面板的高度与其内容的
自然高度之差（死区）、以及面板内的横向溢出。它同时会打印面板数量——**渲染出 0 个面板
会直接判 FAIL**，否则一个白屏路由会被静默当成「没问题」。

---

## 布局约定

这几条是踩过坑之后定下来的，改布局前值得先读：

| 约定 | 原因 |
| --- | --- |
| 面板里的长列表加 `.ft-list-viewport` | 不加上限时，125 笔的平仓表把面板撑到 1589px、「表现」表撑到 2333px，旁边留出等高的空白 |
| `.ft-grid` 用 `align-items: start` | 默认 `stretch` 会把短面板拉成空心盒子（实测死区 945px） |
| 表格单元格 `white-space: nowrap` | 时间戳折成两行会让行高从 36px 变成 57px，面板高度直接翻倍 |
| 宽而窄的表用 `.ft-perf-split` 拆两栏 | Semi 表格必然撑满 100%，全宽单表会让标签列被拉到 1500px、数字散到两端 |
| 短内容不要用折叠面板 | 藏四行数据要多点一次，不如直接展开（`更多明细` / `策略参数` / `订单`） |
| 暗色 token 挂在 `html[theme-mode='dark']` | 只挂 `body` 的话 `html` 拿不到，根滚动条会用浅色值（暗色下白滚动条） |


### 关于 Semi 的配色覆盖

Semi Design 的语义色全部由调色板变量派生（`--semi-color-primary: rgba(var(--semi-blue-5), 1)`），
所以只覆盖 `--semi-color-primary` 会漏掉 `-hover` / `-active` / `-light-*` 这些变体，
残留蓝色。`src/styles/semi-palette.css` 由脚本生成，保留 Semi 的明度结构但抹掉色相：

```bash
npm run gen:palette   # 重新生成 src/styles/semi-palette.css
```

装饰性调色板（blue / cyan / purple / violet / pink / teal / lime / indigo / …）全部灰阶化；
状态调色板（green / red / yellow / orange / amber）只把色相旋转到本项目的
up / down / warn，饱和度与明度沿用 Semi 原值。

覆盖选择器写成 `html body[theme-mode='dark']` 而非 `body[theme-mode='dark']`：
Semi 把主题变量块重复打包进了多个组件 CSS chunk，这些 chunk 会在入口样式表之后注入，
同优先级会因顺序而输掉，多一个元素选择器才能在优先级上稳定取胜。

---

## 功能范围

对照 freqUI 的页面逐一对齐：

| 分组 | 页面 |
| --- | --- |
| 交易 | 总览、交易台、持仓、历史成交、资金 |
| 分析 | K 线图、交易对列表、Pairlist 配置 |
| 工具 | 回测、下载数据、未来函数分析、递归分析 |
| 系统 | 日志、设置 |

覆盖的能力包括：机器人启停/暂停/重载、强制买入与卖出、逐笔订单操作（部分平仓、取消挂单、
加仓、重载、删除）、K 线与成交量、累计收益 / 收益分布 / 逐笔收益 / 资金曲线、Pairlist 链式
配置与评估、回测运行与结果分析（含历史结果载入、指标对比、笔记）、数据下载、回测结果的
K 线可视化、日志查看、WebSocket 实时推送。

### 与 freqUI 的若干有意差异

- **图表**：用 `lightweight-charts` + 内联 SVG 环图替代 ECharts，省掉约 1 MB 依赖。
- **布局**：固定响应式网格替代可拖拽面板（freqUI 的拖拽布局状态无法跨版本稳定迁移）。
- **`TimeframeSelect` 取值**：freqUI 上游的 `TimeframeSelect` 存在 `v-model` 绑定缺陷
  （声明 `value` 却 `emit('input')`），导致所选周期从未真正写入回测参数。这里已修正，
  因此回测请求会**真的带上** `timeframe` / `timeframe_detail`。
- **黑名单删除**：按后端声明使用重复的 `pairs_to_delete` 查询参数（而非 JSON body）。

### 运行模式说明

freqtrade 只有在 **webserver 模式**下才提供 `/strategies`、`/exchanges`、`/available_pairs`、
`/pairlists/available`、`/backtest/*`、`/background` 等端点；交易模式下这些接口返回
`{"detail":"Bot is not in the correct state."}`。UI 会识别这种情况并降级展示（回测页给出
明确提示），而不是报错。

K 线页同理：交易模式下 `pair_candles` 只对机器人当前 `timeframe` 和交易对列表内的币种有缓存，
其它组合会返回空数据。

---

## 代码结构

```
src/
  api/
    client.ts        # BotApi：每机器人独立 token、401 自动刷新、UTF-8 Basic 认证、WS URL
    endpoints.ts     # 按域分组的接口 + 位置型响应的解码（decodeCandles/decodeLogs/...）
    types.ts         # freqtrade API 类型
  state/
    bots.tsx         # 多机器人连接与切换（localStorage）
    theme.tsx        # 黑白主题切换（body[theme-mode]）
    live.tsx         # WebSocket：指数退避重连、按 topic 订阅、事件环形缓冲
    snapshot.tsx     # 快照轮询：快 5s（持仓/锁）、慢 60s（配置/收益/资金/白名单）
  hooks/
    usePolling.ts    # 通用轮询（页面可见性暂停、错误描述）
    useJobPolling.ts # 后台任务：POST 拿 job_id → 1s 轮询 /background/{id}，并恢复已运行任务
  components/        # Panel/StatTile/Tag 等原语、TradeList、选择器、图表
  layout/AppShell.tsx
  pages/             # 与路由一一对应
  styles/
    tokens.css       # 设计令牌 + Semi 主题变量覆写（黑白两套）
    app.css          # 布局与密集表格样式
```

---

## 开发备注

- **`npm install` 必须清掉两个环境变量**：本机 shell 里预设的
  `npm_config_allow_scripts` / `npm_config_local_prefix` 会让 npm 12 报
  `EALLOWSCRIPTS`。用上面的 `env -u ...` 前缀安装。
- **Semi 的 CSS 路径**：`@douyinfe/semi-ui` 2.103 把样式表放在 `dist/css/`，但没有写进
  `package.json` 的 `exports`，直接 import 会解析失败。`vite.config.ts` 用 alias 把它指向
  真实文件。
- **React 19**：Semi 需要先加载 `@douyinfe/semi-ui/react19-adapter`，已在 `main.tsx` 顶部导入。
- **主题挂在 `body` 上**：Semi 的暗色选择器是 `body[theme-mode=dark]`，因此 `index.html`
  里有一段内联脚本在 `<body>` 开头设置该属性，避免首屏闪烁。
