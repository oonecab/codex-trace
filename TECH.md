# codex-trace — 技术事实唯一来源

<!-- project-governance:managed:start -->
## 项目目的

只读本地 Codex 执行记录，以会话、轮次和事件时间线查看工作过程。

## 项目分类

- 项目类型：`windows-data-tool`
- 治理级别：`lean`

## 技术栈基线

### 语言

- Python
- JavaScript
- HTML
- CSS

### 框架与核心库

- 尚未填写。

### 运行时与工具链

- Python >=3.10
- 现代浏览器

## 源码边界

- trace_viewer
- tests

## 架构事实

- Python 标准库提供仅监听回环地址的 HTTP 服务；浏览器界面无外部依赖。
- SQLite 以 mode=ro 和 query_only 读取；兼容原始 rollout JSONL。
- 本地日志作为不可信文本展示，不执行命令、不渲染日志中的 HTML。
- 可选依赖 zstandard（或 Python 3.14+ 自带的 compression.zstd）仅用于读取 DeepSeek Harness 的 zstd 压缩会话；缺失时只影响该来源，并在页面提示。

## 项目类型约束

- 显式测试 Windows 路径、编码、文件锁和非 ASCII 文件名。
- 保留源文件，并确保生成物可重复生成。
- 记录 Office 或桌面运行时要求及打包约束。

## 项目专属规则

- 事件必须能回查原始来源；缺失信息明确标记，不推测隐藏思考。
- 时间、耗时、去重和统计口径以 docs/rules/records.md 为权威来源。
- 新日志类型保留可见记录，不静默丢弃。
<!-- project-governance:managed:end -->

## 已确认的技术细节

- `trace_viewer/store.py`：定位本地数据库，以短连接读取索引、轮次、事件；结构化历史缺失时读取 rollout；按 id 只查询目标会话；缓存最近三条会话（列表请求 2 秒内复用，单个事件详情始终复用缓存，缓存里找不到该事件才重新解析），同一会话并发请求只解析一次；响应附带 `fingerprint`（事件标识、状态、耗时与内容长度的摘要，不含完整内容），前端据此判断是否需要重绘。
- `trace_viewer/source_base.py`：所有来源共用的缓存、按会话加锁、结果组装（分析与 `fingerprint`）和详情查找；来源只需实现 `list_sessions`、`_session`、`_parse`。
- `trace_viewer/agent_logs.py`：Claude Code、pi 共用的会话文件索引（按修改时间缓存元数据，只接受数据目录内的文件）与统一事件构造函数。
- `trace_viewer/dsh_source.py`：DeepSeek Harness（CLI、Web、桌面端共用 `~/.dsh/sessions`）。每个会话目录取最高格式代际的日志（`session.v4.jsonl` 优先于 `session.jsonl`）；日志是追加写入的多帧 zstd，经 `agent_logs.log_lines` 读取，末帧未写完时保留已读部分并提示；流式 `*-chunks` 片段忽略，使用完整的 `assistant/message`、`tool/result`；`spawn_teammate` 与随后的 `team/member` 配对，生成指向子代理会话的链接。
- `trace_viewer/claude_source.py`、`trace_viewer/pi_source.py`：把两种 JSONL 记录映射为 Codex 同款统一事件（映射与口径见 [执行记录规则](docs/rules/records.md)），不读取子目录之外的凭据或配置。
- `trace_viewer/catalog.py`：聚合各来源，按会话 id 前缀（`claude:`、`pi:`；无前缀为 Codex）分发；单个来源失败不影响其他来源。
- `trace_viewer/normalize.py`：统一数据库与 JSONL 事件、关联必要字段、提取可读内容并生成统计；每种事件类型一个处理函数，用 `@handles("类型名")` 注册到 `HANDLERS`，未注册的类型仍以类型名和附带文本保留可见。统计和时间语义统一见 [执行记录规则](docs/rules/records.md)。
- `trace_viewer/analysis.py`：归一化事件进入纯函数规则处理模块，依次生成卡片、关联、稳定 ID 的图结构及轮次汇总；不调用模型，不执行命令，不读取关联路径指向的文件。依据与口径见 [过程整理规则](docs/rules/process.md)。结果进入已有会话缓存，并由 `GET /api/sessions/<id>` 的 `analysis` 字段返回；没有新增写入接口。
- `trace_viewer/__main__.py`：Python `http.server` 提供只读 JSON API 与 `static/` 目录下的静态文件（名称中不含路径分隔符、冒号，且不以点开头），只监听 IPv4 回环。检查 Host、Origin 和 Fetch Metadata；没有命令执行或任意文件读取接口。
- `trace_viewer/static/`：无构建步骤的浏览器界面；日志始终通过 `textContent` 展示，保留原文，不解释其中的 HTML。
- `trace_viewer/static/dropdown.js`：用样式化的下拉菜单替换原生 `<select>` 弹层（原生弹层无法跟随主题）。真实的 `<select>` 保留并隐藏，`.value`、`change` 事件和选项增删照常工作；支持键盘（上下键、回车、Esc、Home/End）、点击外部关闭、空间不足时向上展开。
- `trace_viewer/static/theme.css`：由 `--bg-* / --bd-* / --tx-*` 色阶（g 绿灰、n 中性、w 暖、p 紫、b 蓝；数字是亮度档，末尾 a 表示带透明度）和基础调色板组成，同时给出浅色与深色取值；深色跟随系统，顶栏按钮可手动切换并保存在浏览器本地。
- `trace_viewer/static/style.css`：统一字体、颜色（暖象牙底、衬线标题与数字、陶土色强调 `--green`）、卡片、表单控件、过程概览与关系图样式和详情面板，原始记录以可折叠键值树展示；页面内容最大宽度 1440px，主要正文 15px、轮次标题 16px、代码预览 13px。1280px 以下详情改为覆盖面板，760px 以下侧栏可收起、详情占满窗口；窄屏保持正文字号。
- `trace_viewer/static/process.js`：阶段概览、测试前后记录、原生 SVG 关系图与详情中的识别依据；与 `app.js` 共用事件详情和会话选择。图按轮次分页，避免整段历史同时铺开；刷新保留已展开阶段、关联筛选和所选连线依据。
- 关系图使用 1120 CSS 像素宽度作为 100% 基准，节点正文 14px；SVG 宽高按用户选择的 70%–130% 同比缩放，不再自动拉伸填满宽屏。缩放作用于图内，窄屏通过容器滚动查看；缩放状态在刷新、分页及切换视图时保留，点击百分比复位。
- `start.ps1`：选择 Python 并转交命令行参数。`--open` 在端口成功绑定后打开浏览器。
- 数据源验证基于本机 Codex 0.160.1 的 `state_5.sqlite` 与 `thread_history_1.sqlite`，兼容目前观察到的现代/旧版 rollout。版本号不是兼容承诺，未知类型保留入口，无法解析的记录明确提示。
- 本项目单独放在 `viewer`，没有修改 `../code/oeb`；没有复用 OEB 的模型裁判、评分或英文引用校验。

## 技术栈变更索引（只追加）

“技术栈变更”至少包括语言、运行时、框架、核心库、构建工具、数据库或中间件的新增、移除、替换、主版本升级，以及兼容基线变化。普通补丁升级仅在影响行为、兼容性或安全基线时记录。

| 日期 | 变更前 → 变更后 | 科学/工程理由 | 兼容、迁移与回滚影响 | 问题单 / ADR |
|---|---|---|---|---|
| 2026-10-07 | 空项目 → Python 标准库 + 原生 HTML/CSS/JavaScript | 本机只读工具无需依赖安装、云服务或模型调用 | 独立目录；不迁移、不写入 Codex 源数据库；停止进程即可停止运行 | [首版验证](docs/verification.md) |
| 2026-10-08 | 仅标准库 → 标准库 + 可选依赖 `zstandard`（或 Python 3.14+ 的 `compression.zstd`） | DeepSeek Harness 会话是多帧 zstd 压缩，标准库（3.13 及以下）无法解压；自写解码器成本和风险过高 | 仅影响该来源：未安装时其他来源照常读取，页面提示安装命令；不改变其他行为，回滚只需删除 `dsh_source.py` 并移出 `__main__.py` 的注册 | 无 |

> 详细论证写入问题单或 ADR；本表保存可追踪索引，不得覆盖历史记录。
