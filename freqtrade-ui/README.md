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
npm run review       # 整页长图（按内容高度调整视口），用于逐页审查
npm run contrast     # WCAG 对比度审计，两个主题各跑一次
```

`npm run review` 会先把视口拉到内容高度再截图——应用滚动在 `.ft-main` 内部，`fullPage: true`
只能拿到视口。它先等真实内容出现（面板存在且文字超过阈值）再等高度稳定：**只等"高度不再变化"
是不够的，加载中的 spinner 高度恒定，会立刻满足条件**，早先就因此把若干页拍成了加载态。

`npm run contrast` 遍历所有可见文本，向上找到第一个非透明背景算出 WCAG 对比度。
禁用控件按 WCAG 豁免跳过（Semi 把它们渲染成 35% 透明），否则会淹没真正的发现。

`npm run focus` 逐页 Tab 走一遍，把每个聚焦元素的绘制样式与**它未聚焦时**对比。
关键是这个对比：只查 `outline-style` 会误报，因为 Semi 的焦点画在边框色上
（Select 从透明边框变成墨色边框）。

`npm run audit` 是这套黑白设计的回归防线：它遍历可见节点，把所有绘制出来的颜色
分成「无彩色」和「语义色」两类，任何第三种有彩色都会判 FAIL 并列出具体色值与属性。
语义色只允许 8 个：`--ft-up/-down/-warn/-info` 及其 `-bg`。

`npm run structure` 逐页报告页面宽度占比、每个面板的高度与其内容的自然高度之差（死区）、
以及面板内的横向溢出。默认扫 **2 个主题 × 3 个宽度**（2040 / 1440 / 1100，覆盖应用的
1280 与 1100 断点）；可用 `STRUCTURE_THEMES` / `STRUCTURE_WIDTHS` 收窄。

它同时会打印面板数量——**渲染出 0 个面板会直接判 FAIL**，否则一个白屏路由会被静默当成
「没问题」。

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
| 覆盖 Semi 类要写成 `body .semi-a .semi-b …` | Semi 的组件 CSS 在入口样式表**之后**注入，同优先级会因顺序输掉；类名层数也要对齐（`.semi-banner-full .semi-banner-content-wrapper .semi-banner-content` 是 3 层） |
| 别给 Semi 组件传 `style={{ flex }}` 当 flex 项 | `Slider` 把 `style` 转给内层 `.semi-slider-wrapper`，真正的 flex 项是外层 `.semi-slider`（`flex: 0 1 auto`）——轨道被压成 0px，只剩一个悬浮手柄。要用一层 div 承载 flex |
| 图表 `time` 不能用数组下标 | lightweight-charts 把数字当 Unix 时间戳，下标 1/2/3… 会让时间轴永远显示 `00:00`；类别轴应设 `timeScale.visible: false`，把标签渲染在 canvas 下方 |
| 表单标签统一用 `.ft-formgrid` + `.ft-formlabel` | 同一个表单里混用「标签在上」「右对齐网格」「带边框分组」三种排法，看起来像没做完 |
| `/trades` 没有 `pair` 参数 | 后端签名只有 `limit/offset/order_by_id`，传 `pair` 会被**静默忽略**并返回全局历史——按交易对分组只能在前端做 |
| 长列表页用 `.ft-page.fill` | 让面板吃掉剩余高度；否则 12 行表格下方留 650px 空白，可见行数还少一半 |
| 分页器放在滚动视口**外面** | 放里面的话，翻页前得先把 25 行表格滚到底 |
| 进度条 / 开关不用 `--semi-color-success` | Semi 的 `Progress` 和 `Switch` 默认都取该 token，而它被绑定到盈亏绿——中性比例和控件开关会被渲染成「盈利」色 |
| 灰阶要满足 4.5:1 | 原先 `--ft-ink-4: #a3a3a3` 在 paper-1 上只有 **2.42:1**，而它承担 11px 的说明文字、面板副标题、导航分组标签——审计一次报了 108 处 |
| `usePolling` 的 `deps` 变化要清空 data | `deps` 是这次请求的「身份」。不清空的话切换机器人会继续显示上一个机器人的持仓和盈亏，请求失败还会永远留着，而 snapshot 已经重置，外壳和页面各说各话。按元素身份比较，手动刷新（nonce）不清，否则每次轮询都闪 |
| `fetchFast` 失败要保留旧值 | 用 `.catch(() => [])` 代替旧值，一次瞬时错误就会把顶栏、导航徽标和所有持仓表渲染成空仓 |
| 改单后要把该页**所有**派生轮询都刷新 | `afterMutation` 原先只刷 snapshot 和已平仓，`表现`/`时段`/`K线` 会继续显示改动前的数字，最长 2 分钟 |
| 详情面板的选中项要按当前列表**重新解析** | 面板持有的是被传入的对象；删除成交后它会继续渲染一个已经不存在的交易。改为每次从列表里按 id 查 |
| 列表窗口不一致要用按 id 兜底 | 仪表盘取 500 行、交易台 200 行，点第 201–500 名会跳到 `/trade` 显示「未选择交易」且无任何提示。用一直闲置的 `GET /trade/{id}` 兜底，而不是对齐两个魔法数字 |
| 设置项必须真的有效果 | 审计发现 **9 项设置只有设置页自己读**：`openTradesInTitle`/`confirmDialog`/`multiPaneButtonsShowText`/`chartLabelSide`/`useReducedPairCalls`/`showMarkArea`/`profitDistributionBins`/`timeProfitPeriod`/`timeProfitPreference`/`backtestAdditionalMetrics`/`notifications`。一个不起作用的开关比没有更糟 |
| `formatTimestamp` 默认读 `currentSettings().timezone` | 原先默认写死 `'UTC'`，只有日志页传了设置值——设置页宣称「影响所有时间戳」是假的，23 处调用里 22 处无视它 |
| `GET /pair_candles` 不能过滤列，要用 POST | GET 的签名只有 `(pair, timeframe, limit)`；POST 变体才接受 `columns`。这一条同时修好了「只请求必要的列」设置和绘图配置里选了却从未发出的列 |
| 没有落点的设置要删掉，不是留着 | `多窗格按钮显示文字` 的「多窗格」在源码里只出现在设置页自己——它是 freqUI 遗留，本实现没有对应概念，已删除 |
| 会调用浏览器 API 的设置必须带授权入口 | `notifications` 四个开关依赖 `Notification.permission`，而浏览器只在用户手势里授权。没有「允许桌面通知」按钮时，开关永远是死的 |
| WS 主题订阅了就必须消费 | `whitelist`/`status` 被订阅、被计数却从不读取，导致推送的交易对轮换要等 60 秒慢轮询才出现 |
| 后台任务被丢弃要 resolve 等待方 | `dismiss` 停轮询、移除任务，但从不 resolve `waitFor`，`await` 永久挂起 → 按钮一直禁用。现在 resolve `null` 表示「已取消」 |
| 快慢两个轮询的时间戳要分开 | 一个 `lastUpdated` 无法诚实：快轮询 5s、慢轮询 60s，用一个值会让余额/收益（60s 数据）显示成 5 秒前更新 |
| 选中行要让它对应的面板可见 | 交易台详情面板在两张表下方，选中后什么都不动，看起来像没反应。用 `Panel` 的 ref + `scrollIntoView`（K 线图页早有此模式） |
| 后端会返回重复的「名字」 | 黑名单来源里 `PairInformationFilter` 出现两次，`key={method}` 直接触发 React 重复 key。凡 key 取自后端字符串，都要拼上下标 |
| 列表上限要假设数据量会变 | 白名单一轮刷新从 57 涨到 322，交易对网格瞬间变成 1246px 高的面板——`max-height` 不是可选项 |
| 中止是「请求」不是「完成」 | `abort` 之后后端可能仍报 `running: true`；无条件 `stopPolling()` 会让进度条永久冻结在「回测运行中」且结果永远不加载。要等状态真正落定 |
| 同一份数据的第二个副本要一起刷新 | 备注保存后只更新了内存副本，历史列表是**自己单独拉取**的，所以还显示旧文本。用 revision 推动它刷新 |
| 异步动作的每个分支都要走完 | 回测中止、历史载入这类路径要保证 `finally` 一定执行，否则按钮永久禁用（见「丢弃任务要 resolve 等待方」） |
| 审计脚本本身也要验证 | `structure` 的主题曾被硬编码成 `dark`，于是「浅色」那几轮实际跑的是深色——**会静默产出假的通过结果**。加参数后先确认日志里的 THEME 真的变了 |
| 布局要在多个宽度下测 | 2040px 全绿的三处问题（白名单网格 1253px、余额表无上限、环形图图例溢出 13px）都只在 1100px 才暴露。断点 1280/1100 必须纳入扫描 |
| 图表设置要在每个画图的地方生效 | 交易台的 K 线硬编码 `limit: 300` 且忽略 Heikin-Ashi，而 K 线图页两项都遵守。蜡烛变换提到 `utils/candles.ts` 共享，避免再次分叉 |
| 顶栏放不下时要「按优先级丢弃」 | 1100px 下策略名折成两行、持仓与收益数字互相挤压。给可选项加 `.ft-topbar-optional`，1320px 以下先丢掉身份详情（每个页头都重复） |
| `cols-2` 在 1280px 就该塌成单列 | 两张十列的成交表并排时各只有约 440px，大部分列被切掉。原先到 860px 才塌 |
| 静默裁切要能被审计发现 | 加了 `CLIPPED` 检测：元素自身 `overflow: hidden` 且 `scrollWidth > clientWidth` 而没有 `text-overflow: ellipsis`、又不在滚动容器内，就是无提示地藏了内容 |
| 面板头要能换行，标题不能断字 | Pairlist 配置页在 1100px 下标题被压成竖排单字（「配/置/0/个…」）。`.ft-panel-head` 加 `flex-wrap`，`.ft-panel-title` 加 `white-space: nowrap` |
| 多列布局不要写成内联固定轨道 | 该页原是三列内联网格，中间列在 1100px 只剩 230px。抽成 `.ft-panes-3` 并在 1500/1100px 逐级塌陷 |
| 需要用户点的按钮不能用 `borderless` | 「允许桌面通知」是无边框按钮，渲染出来像小标题。它恰恰是那块面板唯一需要用户执行的动作 |
| 覆盖 Semi 必须**实测计算样式**，不能只看写了规则 | 进度条的覆盖写了 `body .semi-progress-track-inner`，但真正生效的是 `.semi-progress-horizontal .semi-progress-track-inner`（两个类）——规则在样式表里、看着没错，实际一直没生效，绿色进度条留了 9 轮才被发现 |
| 覆盖前先查 Semi 的实际选择器链 | 用 `document.styleSheets` 把所有命中该元素的规则打出来，确认赢的那条的类名层数，再照着写 |
| 焦点检查要和「未聚焦」比对 | 只查 `outline-style` 会误报：Semi 的焦点画在边框色上（Select 从透明边框变墨色边框）。`npm run focus` 逐个元素对比聚焦/未聚焦的绘制样式 |


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
