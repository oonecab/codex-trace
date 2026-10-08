# 本地运行环境

- Python 3.10 或更新版本，仅使用标准库，无需安装第三方包。唯一的可选依赖是 `zstandard`（`python -m pip install zstandard`，须装进实际运行服务的那个 Python）：只用于读取 DeepSeek Harness 的 zstd 压缩会话，Python 3.14 以上自带解码器可不装；缺失时其他来源不受影响，页面提示安装。
- 现代浏览器；页面不使用外部字体、CDN 或模型服务。
- 默认监听 `http://127.0.0.1:8765`，只绑定回环接口。通过 `--port` 或 `start.ps1 -Port` 修改端口。
- `CODEX_HOME` 是可选的非秘密目录设置；也可以传 `--codex-home` 或 `start.ps1 -CodexDataDirectory`。
- `CLAUDE_CONFIG_DIR`（默认 `~/.claude`）和 `PI_CODING_AGENT_DIR`（默认 `~/.pi/agent`）同为可选的非秘密目录设置；也可以传 `--claude-home`、`--pi-home`，或 `start.ps1 -ClaudeDataDirectory`、`-PiDataDirectory`。`DSH_HOME`（默认 `~/.dsh`）对应 DeepSeek Harness，也可传 `--dsh-home` 或 `start.ps1 -DshDataDirectory`，只读取其中的 `sessions/`。只读取其中的 `projects/` 与 `sessions/` 子目录，不读取同目录下的凭据或配置文件。`--only codex|claude|pi|dsh`（可重复）限定读取的来源。
- `.env.example` 仅列出变量名作为参考，程序不自动加载 `.env`。需要时在 PowerShell 中设置 `$env:CODEX_HOME` 等变量。
- Windows 启动脚本优先使用 Codex 自带 Python，缺失时使用 PATH 中的 Python。
- `start.ps1` 默认使用 `--open` 在服务绑定端口后打开浏览器；传 `-NoBrowser` 可关闭此行为。
- 关闭启动终端或按 Ctrl+C 结束服务；浏览器标签页不负责管理进程。
- 当前只支持本地有持久化记录的会话。云端或远程主机的记录必须先在该主机运行读取器，当前工具不会自动取回这些记录。
