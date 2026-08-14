# Triggered daily by Windows Task Scheduler. Runs one headless Claude Code
# session that follows daily_run/PROMPT.md: picks a theme, discovers/selects
# clips via the rankingagent CLI, writes reactions/title/description, renders
# and uploads the video. See README.md "Dagelijkse automatisering" for setup.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("daily_run_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

$prompt = Get-Content -Raw (Join-Path $PSScriptRoot "PROMPT.md")

# --dangerously-skip-permissions is required for a truly unattended run (no
# one is at the keyboard to approve tool calls). Scope what it can do via
# .claude/settings.json instead of relying on this flag alone — see README.
claude -p $prompt --dangerously-skip-permissions *>&1 | Tee-Object -FilePath $logFile
