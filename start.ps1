param(
    [int]$Port = 8765,
    [string]$CodexDataDirectory = "",
    [string]$ClaudeDataDirectory = "",
    [string]$PiDataDirectory = "",
    [string]$DshDataDirectory = "",
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$viewerRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $viewerRuntime)) {
    $viewerPythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $viewerPythonCommand) { throw '需要 Python 3.10 或更新版本。' }
    $viewerRuntime = $viewerPythonCommand.Source
}
$viewerArguments = @('-m', 'trace_viewer', '--port', $Port)
if ($CodexDataDirectory) { $viewerArguments += @('--codex-home', $CodexDataDirectory) }
if ($ClaudeDataDirectory) { $viewerArguments += @('--claude-home', $ClaudeDataDirectory) }
if ($PiDataDirectory) { $viewerArguments += @('--pi-home', $PiDataDirectory) }
if ($DshDataDirectory) { $viewerArguments += @('--dsh-home', $DshDataDirectory) }
if (-not $NoBrowser) { $viewerArguments += '--open' }
Push-Location $PSScriptRoot
try {
    & $viewerRuntime @viewerArguments
} finally {
    Pop-Location
}
