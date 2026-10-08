# 验证记录

日期：2026-10-07。范围：本地执行回放工具 `viewer`。

以下自动检查、浏览器检查与文档影响为首版记录；纯规则过程视图的增量验证在文末。

## 自动检查

- `python -m unittest discover -s tests -v`：17 项通过。
- `node --check trace_viewer/static/app.js`：通过。Node 只用于开发时检查语法，运行工具不需要 Node。
- `validate_project.py . --strict`：项目治理校验通过；使用 `lean` / `windows-data-tool`，启用 Codex 和 OpenCode 入口。
- `start.ps1 -NoBrowser`：成功在 `127.0.0.1:8765` 启动，读取本机 Codex 数据目录。
- 原始 `../code/oeb` 仓库 `git status --short` 无输出，未修改原仓库。

测试数据包含中文路径、文本中的 HTML 字符、缺失事件、未知类型、无公开思考摘要、最终答复标记、问答选择包装、重复记录、乱序返回、未完成调用和损坏 JSONL。验证只读连接、HTTP 来源边界及非法路径拒绝。新事件由测试向临时数据库写入，读取器始终只读。

## 浏览器检查

使用 Codex 内置浏览器查看当前真实会话，已验证：

- 项目筛选、会话搜索和无匹配提示。
- 命令类别与关键词组合筛选、异常筛选、恢复全部事件。
- 无摘要思考开关：关闭时收起，打开时计数和事件恢复。
- 连续阅读切换、命令详情及“原始记录”切换；完整测试输出、退出码和耗时可以回查。
- 自动刷新：未手动刷新时，时间和可见事件数随本会话新增记录更新。
- 搜索无匹配事件时只显示空状态；清空搜索后恢复时间线。
- 浏览器控制台没有应用错误或警告。
- 800px 内置浏览器侧栏布局与 1366px 三栏布局：宽屏列宽为 264/692/410px，页面无水平溢出；检查后已恢复默认视口。

本次交付截图位于 `E:/agents/codex/oeb/tmp/codex-trace-preview.jpg`，未放入项目源文件中。

验证未涵盖每一个历史 Codex 版本、云端记录和远程主机记录；读取兼容范围以 [TECH.md](../TECH.md) 为准。没有运行 OEB 评审评分。

## 文档影响

已同步 README 使用说明、TECH 模块边界与初始技术栈记录、`.project-governance.json` 环境设置、`.env.example` 变量名、运行环境文档，以及事件/时间/统计权威规则。真实会话和数据库未复制到项目中，测试使用合成夹具。

## 纯规则过程视图增量验证

日期：2026-10-07。新增操作卡片、按轮次折叠的阶段概览、测试前后记录及交互关系图；不引入模型或第三方依赖。

- `python -m unittest discover -s tests`：43 项通过（0.593 秒）。包括原有 17 项及新增 26 项规则/图测试；API、隐私字段省略与刷新联动测试增加了 `analysis` 断言。
- `node --check trace_viewer/static/app.js`、`node --check trace_viewer/static/process.js`：通过。
- 项目治理严格校验通过。原始 `../code/oeb` 仓库仍无工作区改动。
- 已重新启动本地服务，读取当前真实会话验证。

规则测试涵盖：shell 包装、多条命令、here-string 和打印示例排除、帮助与收集模式、测试汇总与退出码分离、失败报告、跳过信息、ANSI 字符、中文带空格路径、变量/表达式不建立路径、目录改变时不臆测相对路径、Windows 与 POSIX 身份规则、陈述不当作验证结果、隐藏推理省略、未知事件、读写同文件、不同目录同名文件、失败修改、明确代理 ID、稳定图 ID、记录顺序、追加事件不修改已有 ID、同命令匹配的轮次/目录/参数边界、阶段聚合及混合命令统计去重。没有生成因果、支持、反驳或修复边。

浏览器使用本机当前会话验证：

- 默认过程概览、阶段展开、轮次定位、最新轮次及说明/公开摘要展开。
- 测试详情显示 40 项与 42 项历史测试报告，并能通过前后链接互相跳转；中间修改数量有明确依据说明。
- 关系图切换、分页、按文件筛选、文件节点筛选后回到图首、动作节点打开完整命令与输出、原始记录切换，以及键盘选中连线查看依据。
- 文件连线从动作出发并避开结果框，避免视觉上产生结果指向文件的误解。
- 时间线关键词搜索与恢复原记录正常；自动刷新能接入本次工作产生的新条目。
- 1366px 宽屏及带详情的三栏布局无页面横向溢出；600px 窄屏也无页面横向溢出，关系图在自己的容器内横向滚动。临时视口覆盖已恢复。
- 检查时浏览器控制台无应用错误或警告。

关系图验证截图：`E:/agents/codex/oeb/tmp/codex-trace-rules-graph.jpg`。截图包含用户本地记录，仅保存在项目外的本机临时目录。

文档影响：已更新 README 使用说明、TECH 模块与 API 边界、文档索引，并新增 `docs/rules/process.md` 作为识别/测试/关联/汇总权威规则。技术栈、环境变量、端口和部署方式均未改变，故不修改 `.project-governance.json` 和环境文档。验证范围仍不涵盖完整 shell 语法、所有测试框架及未来 Codex 日志格式。

## 全局视觉与阅读体验调整

日期：2026-10-07。范围：共用页面、侧栏、统计卡片、过程概览、时间线、关系图和详情面板的字体、颜色、留白、控件及响应式布局；增加图内缩放，不改变记录处理和统计规则。

- `python -m unittest discover -s tests -v`：43 项通过（0.595 秒）。
- `node --check trace_viewer/static/app.js`、`node --check trace_viewer/static/process.js`：通过。
- `validate_project.py . --strict`：通过；原始 `../code/oeb` 仓库 `git status --short` 无输出。
- 浏览器在 1920×960 下检查三个主视图：概览标题 16px、摘要与时间线正文 15px、代码预览 13px。关系图 SVG 实际宽度与 viewBox 同为 1120，节点正文 14px，不随宽屏放大。
- 检查阶段展开、概览到关系图跳转、时间线打开详情、内容与原始记录切换。宽屏详情宽度 480px，长代码与路径换行，详情内容没有水平溢出。
- 验证关系图 110% 为 1232px；缩小至 70%、放大至 130% 时对应按钮禁用；点击百分比恢复 100%，手动刷新保留缩放比例和所选轮次。
- 800×900 检查时间线筛选区、事件和侧栏；390×844 检查概览阶段、关系图及全屏详情。页面无横向溢出，关系图在内部独立滚动；窄屏控件换行，正文未缩小。检查后恢复默认视口。
- 检查时浏览器控制台无应用错误或警告。真实会话自动刷新继续接入新增条目。

截图保存在本机项目外目录：

- `E:/agents/codex/oeb/tmp/codex-trace-redesign-overview.jpg`
- `E:/agents/codex/oeb/tmp/codex-trace-redesign-timeline.jpg`
- `E:/agents/codex/oeb/tmp/codex-trace-redesign-graph.jpg`

文档影响：同步 README 的图内缩放说明与 TECH 的显示尺寸、字号及响应式边界；记录处理规则、技术栈、环境变量和端口未变，不修改对应规则或环境文档。本次通过实际浏览器检查视觉与交互，没有新增复述 CSS 实现的单元测试。

## 首次 GitHub 提交准备

日期：2026-10-07。仓库：`https://github.com/oonecab/codex-trace`。

- 以独立项目目录作为 Git 根目录，项目标识统一为 `codex-trace`，README 增加克隆与启动说明。
- `.gitignore` 增加虚拟环境、本地临时目录、Codex 数据目录、SQLite / 数据库副本、JSONL 和运行日志规则；使用 `git check-ignore` 核对这些路径会被排除。
- 核对待提交的 26 个文件，均为源码、测试、静态资源或项目文档；不包含实际会话、数据库、界面截图、论文及参考仓库。常见令牌、私钥和带凭据 URL 的模式扫描未发现命中。
- `python -m unittest discover -s tests -v`：43 项通过（0.602 秒）；两个前端脚本的 Node 语法检查通过；项目治理严格校验通过。
- 仅调整名称、说明与忽略规则，运行方式、记录解析和统计规则不变，因此不新增运行逻辑测试或修改业务规则文档。

## 质量改进（2026-10-08）

以下为同日多轮改进的最终状态；中途新增过 `polish.css`、`process.css`，已合并进 `style.css`，不再存在。

- **性能**：`HistoryStore` 按 id 直接查询会话；点击事件详情始终复用缓存（此前超过 2 秒会重新解析整条会话）；同一会话并发请求只解析一次；`fingerprint` 只摘要事件标识、状态与内容长度。在本机约 2000 个事件的会话上，整次解析由约 0.40 秒降至约 0.25 秒，详情读取约 0.4 秒降至接近 0，单会话查询约 0.8 毫秒。时间线类别计数改为一次遍历。
- **命名**：事件的 `phase`（是否最终答复）改名为 `answerPhase`，与卡片的 `phase`（读取、修改、测试等阶段）不再同名；`normalize.LABELS` / `analysis.LABELS` 分别改为 `EVENT_LABELS` / `CARD_LABELS`。`analysis.py` 抽出 `summarize_turn`；`normalize()` 的 if 链拆为每种事件类型一个处理函数，经 `@handles` 注册（行为不变，原有测试全部通过，另加注册与未知类型保留的测试）。
- **样式**：`style.css` + `process.css` + `polish.css` 合并为一个 `style.css`（391 条规则合并为 303 条，同选择器的重复规则折叠，被覆盖的响应式声明移除），颜色色阶与深色取值放在 `theme.css`。合并后在 1500 / 1100 / 800 / 600 像素宽度的浅色与 1500 像素深色下，对同一条真实会话的过程概览、时间线、原始记录、关系图截图逐像素对比，残留差异为 1–2 像素的文字位置与边框色，没有布局差异。
- **前端**：JS 用 Prettier（`.prettierrc.json`）格式化；顶栏新增浅色 / 深色切换；原始记录改为可折叠键值树（仍以 textContent 渲染，“复制”复制完整 JSON）；视觉改为暖象牙底、衬线标题数字、陶土色强调，页头与指标栏紧凑化。
- **测试**：新增 `tests/test_static.py`（页面引用的静态文件均可访问且非法名称 404、脚本使用的元素 id 都存在于 HTML、CSS 变量均有定义、每个浅色色阶都有深色取值、`node --check`）。`python -m unittest discover -s tests -v`：49 项通过。
- 文档影响：已同步 `TECH.md`（存储缓存与指纹、静态文件服务规则、`theme.css` / `style.css` 说明）与 `docs/rules/records.md`（刷新口径）。无环境变量、端口、依赖变化，`.project-governance.json` 无需更新。

## 接入 Claude Code 与 pi agent（2026-10-08）

- 新增 `source_base.py`（共用缓存、加锁、结果组装）、`agent_logs.py`、`claude_source.py`、`pi_source.py`、`catalog.py`；`HistoryStore` 改为继承共用基类，Codex 行为不变。命令行新增 `--claude-home`、`--pi-home`、`--only`；`start.ps1` 新增 `-ClaudeDataDirectory`、`-PiDataDirectory`；侧栏新增来源筛选与来源标注。
- `python -m unittest discover -s tests -v`：59 项通过。新增 `tests/test_sources.py`（10 项）覆盖：只列出会话文件（项目目录之外、数据目录根部的 `.jsonl` 与凭据文件不读取）、事件映射与调用返回配对、不推断退出码、签名与加密内容不泄露、子代理内部记录 / 重复 uuid / 本地命令回显 / 损坏行跳过并提示、pi 当前分支选择、`call|1` 这类含竖线的事件 id、前缀路由、HTTP 与私有路径不外露。
- 真实数据检查（本机，只读）：1161 个 Codex、29 个 Claude Code、10 个 pi 会话合并列表约 0.18 秒；逐个加载 Claude Code / pi 会话无异常，最大一条约 800 个事件加载 0.04–0.12 秒。用 Chrome 查看了 Claude Code 与 pi 会话的过程概览、时间线、详情与关系图。
- 过程中发现并修复：命令分析不把 `&&` 当语句分隔，`git ls-files | head && cat README*` 会把 `&&`、`echo`、`git` 当成被读取的文件；重定向参数（`2>/dev/null`）也被当成文件。已改为按 `&&`、`||` 分句并忽略重定向参数（Codex 会话同样受益）。
- 未覆盖：DeepSeek Harness（zstd 压缩，需要可选依赖或 Python 3.14）；Claude Code 的独立子代理文件；Claude Code / pi 的会话在日志之外的状态（如运行中的真实进程）。
- 文档影响：已同步 README、TECH.md、`docs/rules/records.md`（新增“其他来源”口径）、`docs/environments.md`、`.env.example`、`.project-governance.json`（环境变量与服务）。未新增依赖或端口。

## 接入 DeepSeek Harness（2026-10-08）

- 新增 `dsh_source.py`；`agent_logs.log_lines` 支持多帧 zstd（可选依赖 `zstandard`，或 Python 3.14+ 的 `compression.zstd`）。`--dsh-home`、`DSH_HOME`、`start.ps1 -DshDataDirectory`，`--only dsh`。轮次状态标签新增“出错结束”（`failed`），两处重复的状态映射合并为 `ProcessViews.statusLabel`。
- `python -m unittest discover -s tests -v`：63 项通过（未安装 `zstandard` 时 1 项跳过，安装后 63 项全过；两种环境都跑过）。新增测试覆盖：同目录只取最高代际日志、流式碎片忽略、系统通知类 `user/message` 不算请求、`spawn_teammate` 与 `team/member` 配对出子代理链接、`isError` 计入异常、缺少解码器时只提示不报错、末帧被截断时保留已读部分并提示。
- 真实数据（本机，只读）：22 个日志文件共约 36 MB 解压后约 0.3 秒；列出 16 个有用户消息的会话（仅含会话头的 5 个空会话不列出），逐个加载无异常，最大约 600 个事件 0.12 秒。用 Chrome 查看了会话的过程概览、时间线和详情。
- 本机 Codex 自带的 Python 是 3.12.14 且没有 `zstandard`：用它启动时 DeepSeek Harness 缺席，其余来源照常，页面顶部提示安装命令（含该解释器的完整路径）。验证用的 `zstandard` 装在项目之外的临时目录，只通过 `PYTHONPATH` 临时使用，没有改动任何 Python 环境。
- 未覆盖：Python 3.14 的 `compression.zstd` 路径（本机没有 3.14，代码按文档编写，未实测）；DeepSeek Harness 之外的旧格式代际之间的迁移关系。
- 文档影响：已同步 TECH.md（模块说明与技术栈变更索引：新增可选依赖）、records.md、环境文档、`.env.example`、`.project-governance.json`、README。

## 下拉菜单与来源提示（2026-10-08）

- 新增 `dropdown.js` 与 `style.css` 中的 `.dd-*` 样式：来源、项目、轮次、关联对象等下拉框改用主题一致的弹层（圆角、细线边框、柔和阴影、已选项打勾、键盘可操作），浅色与深色下都用截图检查过。移除了原生 `<select>` 的旧样式。
- 修复：会话列表的来源级警告（例如缺少 `zstandard`）原先会被随后的会话刷新清掉，用户几乎看不到；现在与当前会话的提示合并显示，持续存在。来源筛选按 Codex、Claude Code、pi、DeepSeek Harness 的固定顺序排列。
- 本机 Codex 自带的 Python（3.12.14）用 `pip install --user zstandard` 装入了用户目录（不改动 Codex 运行时目录）；重启服务后 DeepSeek Harness 的 16 个会话出现在列表中，按来源筛选可用。
- `python -m unittest discover -s tests -v`：63 项通过。

## 项目筛选随来源联动（2026-10-08）

- 侧栏的项目下拉原先总是列出全部来源的项目。现在只列出当前来源（并遵循“含归档”）下有会话的项目，鼠标停在选项上显示完整路径和会话数；切换来源或“含归档”后，若已选项目不在新范围内会自动回到“所有项目”。
- 用 Chrome 对本机数据逐个来源检查：DeepSeek Harness 7 个项目 / 16 个会话，pi 4 / 10，Claude Code 4 / 29，Codex 29 / 1154，全部来源 38 个项目 / 1209 个会话；先选 Codex 的 `crM-exP`（384 个会话）再切到 pi，项目回到“所有项目”，会话为 10 个。
- 测试仍为 63 项通过；此项为前端交互，按项目现有做法用浏览器检查，没有新增自动化用例。

## 设计复核与提交范围（2026-10-08）

- 复核时运行现有测试：63 项通过，无跳过。使用合成日志检查了过程概览展开、时间线详情、原始 JSON、关系图轮次选择与节点回查。
- 补充边界检查复现了尚未修复的问题：新增来源的长输出在分析前截断，可能漏掉尾部测试失败报告；Claude Code / pi 以文件 60 秒未更新推断轮次结束，未返回的工具也可能被归入已结束轮次；更新时间等字段未变时，等长内容变化不会改变刷新指纹，前端可能保留旧展示；DeepSeek Harness 的用户消息索引依赖字段在行首的位置，且非对象 JSON 行会使会话解析失败。
- 页面另有待改进交互：关系图选择轮次后，下拉菜单仍保持展开。现有测试通过不代表上述边界已经得到覆盖。
- 本次按用户要求提交当前重构、页面与来源接入改动；以上问题保留待修复，没有在本次提交中改变相关运行逻辑。
- 文档影响：将 `.project-governance.json` 已有的可选解压依赖说明同步到 `TECH.md` 受管区块，并记录本次复核结论。`ex.pkl` 与 `$null` 为未纳入提交的本地文件。
- 提交前检查：同步说明并统一 `TECH.md` 换行后，项目治理严格校验通过；`git diff --check` 通过。
