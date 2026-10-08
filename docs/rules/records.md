# 执行记录与统计口径

本文件是读取、归一化、排序、时间和统计规则的权威来源。

基于这些事件生成的过程卡片、测试汇总、图关联及轮次概览，另见 [过程整理规则](process.md)。本文件的顶部会话统计保持原口径，不被规则分类替代。

- 数据位置：显式 `--codex-home` 优先于 `CODEX_HOME`，最后使用当前用户的 `~/.codex`。
- 索引读取最新数字版本的 `state_*.sqlite`。执行事件优先读取 `thread_history_*.sqlite` 的 `thread_items`，轮次读取 `thread_turns`。所有数据库连接使用 URI `mode=ro` 和 `query_only=ON`。
- 没有结构化条目时回退到对应的 rollout；没有数据库时扫描 `sessions` 和 `archived_sessions`。不读取指定 Codex 数据目录之外的 rollout。
- 数据库事件以 `rollout_ordinal` 排序。现代 rollout 使用 `event_msg/item_completed`，以 `(turn_id,item_id)` 去重，不把 `response_item` 的同一内容再计一次。旧格式按 `call_id` 配对调用及结果，保留没有返回的调用。
- 每轮首个用户请求作为轮次标题；同轮追加请求保留在时间线中。
- App 的问答选择包装转换为“问题 + 选择”，原始字段保留在详情；`final` 和 `final_answer` 都标为最终答复。
- 思考内容只展示公开的 `summary` / `summary_text`。不解密或展示私有推理正文；没有摘要时显示事件位置与已记录的时间，不生成内容。
- 不执行日志中的代码，不把日志当 HTML 渲染，不根据自然语言断言业务成功。退出码非零、明确失败状态或 MCP `isError` 计入异常。非零退出不一定代表任务失败，例如搜索无匹配。
- 工具调用数为已记录的 commandExecution、fileChange、webSearch、mcpToolCall、collabAgentToolCall、imageView、imageGeneration、sleep 条目数；子代理活动通知不重复计入。此数不声称覆盖进程内每个内部调用。
- 修改文件数按 `fileChange.changes.path` 的不同原始路径去重；不同路径拼法不会自动视为同一文件。
- 轮次数由持久化的 turn 分组决定；没有 turn 的旧记录使用一个明确的 legacy 分组。
- 时间输入兼容 Unix 秒、Unix 毫秒及带时区 ISO 字符串，输出为 Unix 毫秒。浏览器使用本机时区显示。不得将会话空闲间隔解释为思考耗时。
- 事件耗时优先使用源 `durationMs`，否则使用有记录的完成时间减开始时间；缺失时留空。概览色段编码事件顺序，不编码持续时长。已结束轮次用时累加已记录的轮次耗时，不把运行中的时间补成已完成数据。
- 时间线预览最多 700 字符，标题最多 160 字符；时间线搜索明确针对预览和标题。选中事件时载入完整文字，原始条目省略加密推理及大型内嵌二进制。
- 命令和 MCP 工具预览优先显示返回结果，尚无结果时显示输入；MCP 服务名保留在详情中。文件事件预览显示修改路径。
- 默认显示最多 250 个事件，可继续加载或跳到最新。概览超过 800 个事件时合并为至多 800 个可定位色段。筛选只改变展示，不改变会话统计。
- 默认收起没有公开摘要的思考；勾选“含无摘要思考”恢复。概览仍保留其位置，点击色段会恢复显示并打开详情。类别计数按当前可见性计算，顶部统计保持全会话口径。
- 自动刷新每 5 秒读取当前会话（响应的 `fingerprint` 未变化时不重绘），30 秒刷新会话索引；浏览器隐藏或用户关闭自动刷新时暂停。服务端最近三个会话有 2 秒短缓存；手动刷新绕过缓存。SQLite 投影写入可能稍晚于 Codex 实际动作。
- 记录缺失、损坏行、未知事件类型要保留诊断或显示“其他事件”，不能伪造完整执行过程。

回归验证见 `tests/test_history.py`：中文路径、异常区分、只读连接、原文保留、思考摘要边界、现代去重、旧格式调用关联、异步刷新与 HTTP 来源限制。

## 其他来源（Claude Code、pi agent）

- 数据位置：Claude Code 读取 `~/.claude/projects/<目录编码>/<会话 id>.jsonl`（`CLAUDE_CONFIG_DIR` 或 `--claude-home` 优先）；pi agent 读取 `~/.pi/agent/sessions/--<目录编码>--/<时间>_<会话 id>.jsonl`（`PI_CODING_AGENT_DIR` 或 `--pi-home` 优先）。只扫描这两个子目录下一层的 `.jsonl`，解析后位于该子目录之外的文件（例如链接）不读取；同目录下的凭据、配置文件不读取。
- 会话 id 加来源前缀（`claude:`、`pi:`），Codex 会话 id 保持不变；侧栏可按来源筛选。会话更新时间取文件修改时间，标题 Claude Code 取 `ai-title`、pi 取首条用户请求，缺失时取首条用户请求前 60 字符。
- 轮次：每条真实用户消息开启一轮（Claude Code 同 `promptId` 的消息合并）。工具返回、框架注入的提醒（`system-reminder`）、本地命令的回显输出（`local-command-*`、`bash-stdout`）、`isMeta` 记录不算用户请求；斜杠命令显示为 `/命令 参数`。日志没有轮次状态：最近一轮在文件 60 秒内仍被修改时标为进行中，其余标为已结束。
- 事件映射到与 Codex 相同的统一事件：`Bash`/`PowerShell`/`bash` → 命令；`Read`/`Grep`/`Glob`/`find`/`ls` → 带读取、搜索、列出动作的命令；`Edit`/`MultiEdit`/`Write`/`NotebookEdit`/`edit`/`write` → 文件修改；`WebSearch`/`WebFetch` → 网页；`Task`/`Agent`/`subagent` → 子代理调用；其余工具（含 `mcp__服务__工具`）→ 工具调用。工具调用与返回按调用 id 配对；没有返回的调用保持“进行中”，不补全。
- 不推断日志没有的事实：Claude Code 与 pi 不记录退出码，只有返回文本以 `Exit code N` 开头时才记录退出码；`is_error` / `isError` 计入异常，等同 Codex 的明确失败状态。
- 最终答复：Claude Code 为 `stop_reason == end_turn` 的文本，pi 为文本签名里的 `final_answer` 或 `stopReason == stop`。
- 思考：只显示日志中的 `thinking` 文本；为空时按“没有可展示的摘要”处理。`signature`、`thinkingSignature`、`textSignature` 不进入原始记录。
- 跳过并提示：Claude Code 的子代理内部记录（`isSidechain`）、重复 `uuid`、无法解析的行；pi 不在当前分支（最后一条记录沿 `parentId` 回溯）上的记录。
- 原始记录页显示统一后的条目，并附 `sourceRecord`（原始调用块，超过 4000 字符的字符串截断）与 `sourceResult`。Write/Edit 的差异文本最多 20000 字符，超出部分截断并注明原文长度。
- 命令分析把 `&&`、`||` 视为语句分隔，重定向参数（如 `2>/dev/null`）不当作文件。

## DeepSeek Harness

- 数据位置：`~/.dsh/sessions/--<目录编码>--/<会话目录>/`（`DSH_HOME` 或 `--dsh-home` 优先）；CLI、Web、桌面端共用该目录。每个会话目录只读取最高格式代际的日志：`session.vN.jsonl[.zstd]`，N 最大者优先，`session.jsonl[.zstd]` 视为第 0 代。
- 日志是追加写入的多帧 zstd。需要可选依赖 `zstandard`（或 Python 3.14+）；缺失时该来源的会话不列出，页面提示安装命令，其他来源不受影响。末帧未写完时保留已读部分并提示“记录末尾尚未写完”。
- 会话 id 前缀 `dsh:`，取日志头的 `id`；标题取最后一条 `session/title`，子代理会话（有 `subagent/descriptor`）显示为“子代理：任务描述”。
- 轮次取 `turn/start` 的编号；`turn/end` 的 `completed`、`aborted`、`error` 分别对应已结束、已中断、出错结束；没有 `turn/end` 的最后一轮仅在文件 60 秒内仍被修改时标为进行中，否则标为“状态未记录”，不推断。
- 事件取完整的 `user/message`、`assistant/message`（`reasoning`、`text`、`tool-call` 块）和 `tool/result`；流式 `*-chunks`、`assistant/chunk`、`assistant/attempt`、系统与开发者消息、审批、团队任务等框架记录不作为执行事件。没有 `tool-call` 的助手文本视为该步的答复并标为最终答复。
- 工具映射：`pwsh`/`bash` → 命令；`read`、`grep`、`glob`、`str_replace_editor view` → 读取、搜索、列出；`edit`、`write`、`str_replace_editor create/str_replace/insert` → 文件修改；`web_search` → 网页；`read_image` → 图像；`spawn_teammate` → 子代理调用（与随后 `team/member` 事件按名称配对，链接到子代理会话）；其余工具 → 工具调用。`isError` 计入异常。

回归验证见 `tests/test_sources.py`：会话列表、事件映射与配对、噪音跳过、分支选择、签名不泄露、前缀路由、HTTP 与路径边界。
