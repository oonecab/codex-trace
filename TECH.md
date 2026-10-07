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

- `trace_viewer/store.py`：定位本地数据库，以短连接读取索引、轮次、事件；结构化历史缺失时读取 rollout；缓存最近三条会话。
- `trace_viewer/normalize.py`：统一数据库与 JSONL 事件、关联必要字段、提取可读内容并生成统计。统计和时间语义统一见 [执行记录规则](docs/rules/records.md)。
- `trace_viewer/analysis.py`：归一化事件进入纯函数规则处理模块，依次生成卡片、关联、稳定 ID 的图结构及轮次汇总；不调用模型，不执行命令，不读取关联路径指向的文件。依据与口径见 [过程整理规则](docs/rules/process.md)。结果进入已有会话缓存，并由 `GET /api/sessions/<id>` 的 `analysis` 字段返回；没有新增写入接口。
- `trace_viewer/__main__.py`：Python `http.server` 提供只读 JSON API 与固定静态资源，只监听 IPv4 回环。检查 Host、Origin 和 Fetch Metadata；没有命令执行或任意文件读取接口。
- `trace_viewer/static/`：无构建步骤的浏览器界面；日志始终通过 `textContent` 展示，保留原文，不解释其中的 HTML。
- `trace_viewer/static/style.css`：统一字体、颜色、卡片、表单控件和详情面板；页面内容最大宽度 1440px，主要正文 15px、轮次标题 16px、代码预览 13px。1280px 以下详情改为覆盖面板，760px 以下侧栏可收起、详情占满窗口；窄屏保持正文字号。
- `trace_viewer/static/process.js` / `process.css`：阶段概览、测试前后记录、原生 SVG 关系图与详情中的识别依据；与 `app.js` 共用事件详情和会话选择。图按轮次分页，避免整段历史同时铺开；刷新保留已展开阶段、关联筛选和所选连线依据。
- 关系图使用 1120 CSS 像素宽度作为 100% 基准，节点正文 14px；SVG 宽高按用户选择的 70%–130% 同比缩放，不再自动拉伸填满宽屏。缩放作用于图内，窄屏通过容器滚动查看；缩放状态在刷新、分页及切换视图时保留，点击百分比复位。
- `start.ps1`：选择 Python 并转交命令行参数。`--open` 在端口成功绑定后打开浏览器。
- 数据源验证基于本机 Codex 0.160.1 的 `state_5.sqlite` 与 `thread_history_1.sqlite`，兼容目前观察到的现代/旧版 rollout。版本号不是兼容承诺，未知类型保留入口，无法解析的记录明确提示。
- 本项目单独放在 `viewer`，没有修改 `../code/oeb`；没有复用 OEB 的模型裁判、评分或英文引用校验。

## 技术栈变更索引（只追加）

“技术栈变更”至少包括语言、运行时、框架、核心库、构建工具、数据库或中间件的新增、移除、替换、主版本升级，以及兼容基线变化。普通补丁升级仅在影响行为、兼容性或安全基线时记录。

| 日期 | 变更前 → 变更后 | 科学/工程理由 | 兼容、迁移与回滚影响 | 问题单 / ADR |
|---|---|---|---|---|
| 2026-10-07 | 空项目 → Python 标准库 + 原生 HTML/CSS/JavaScript | 本机只读工具无需依赖安装、云服务或模型调用 | 独立目录；不迁移、不写入 Codex 源数据库；停止进程即可停止运行 | [首版验证](docs/verification.md) |

> 详细论证写入问题单或 ADR；本表保存可追踪索引，不得覆盖历史记录。
