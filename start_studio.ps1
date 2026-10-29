param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先按 README 创建 .venv 并安装项目依赖。'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $taskPython -m src.cli serve --port $Port
} finally {
    Pop-Location
}
