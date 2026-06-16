<#
.SYNOPSIS
  Tails the SentCom backend log on the DGX Spark and filters for v19.34.320 daily-bar gate fires.

.DESCRIPTION
  SSH into spark-1a60@192.168.50.2 and stream-grep /tmp/backend.log for
  the v320 daily-bar premarket gate lines (BLOCK fires + OBSERVE-mode fires).
  Per AGENTS.md §15: Spark on 192.168.50.2, repo at /home/spark-1a60/Trading-and-Analysis-Platform.

.PARAMETER Filter
  Override the grep pattern. Default catches both "v19.34.320" tags and any "OBSERVE" line.

.PARAMETER Lines
  Bootstrap context lines to show before live tail. Default 200.

.EXAMPLE
  .\tail-v320-gate.ps1                          # observe + block fires
  .\tail-v320-gate.ps1 -Filter "v19.34.320"     # only v320 lines
  .\tail-v320-gate.ps1 -Filter "rejection|v19.34"  # any rejection or v19.34 patch line

.NOTES
  Ctrl-C exits cleanly. If SSH keys aren't set up you'll be prompted for the spark-1a60 password.
#>
[CmdletBinding()]
param(
    [string]$Filter = '(v19\.34\.320|OBSERVE)',
    [int]$Lines = 200,
    [string]$SparkHost = '192.168.50.2',
    [string]$SparkUser = 'spark-1a60',
    [string]$LogPath = '/tmp/backend.log'
)

$ErrorActionPreference = 'Stop'

function Write-Header($text, $color = 'Cyan') {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor $color
    Write-Host "  $text" -ForegroundColor $color
    Write-Host ('=' * 78) -ForegroundColor $color
}

Write-Header "v19.34.320 daily-bar gate tail  ($SparkUser@$SparkHost)"
Write-Host "  log:    $LogPath" -ForegroundColor Gray
Write-Host "  filter: $Filter" -ForegroundColor Gray
Write-Host "  bootstrap context: last $Lines lines" -ForegroundColor Gray
Write-Host ''

# 1. Connectivity probe (AGENTS.md §15 step 1)
Write-Host '[1/3] pinging Spark...' -NoNewline
$ping = Test-Connection -ComputerName $SparkHost -Count 1 -Quiet -ErrorAction SilentlyContinue
if (-not $ping) {
    Write-Host ' FAIL' -ForegroundColor Red
    Write-Error "Cannot reach $SparkHost on the 10 GbE LAN (192.168.50.0/24). Check cable + DGX power."
    exit 1
}
Write-Host ' OK' -ForegroundColor Green

# 2. SSH availability
Write-Host '[2/3] checking ssh client...' -NoNewline
$sshExe = (Get-Command ssh -ErrorAction SilentlyContinue).Source
if (-not $sshExe) {
    Write-Host ' MISSING' -ForegroundColor Red
    Write-Error 'OpenSSH client not installed. Settings -> Optional Features -> Add a feature -> OpenSSH Client.'
    exit 1
}
Write-Host " OK ($sshExe)" -ForegroundColor Green

# 3. Build remote command — use grep --line-buffered so tail-f isn't blocked
$remoteCmd = "tail -n $Lines -F $LogPath | grep --line-buffered -E '$Filter'"

Write-Host '[3/3] connecting + streaming...' -ForegroundColor Yellow
Write-Host '       (Ctrl-C to exit)' -ForegroundColor Gray
Write-Host ''

# Run SSH foreground; -t allocates a TTY so Ctrl-C propagates and grep flushes promptly
try {
    & ssh -tt "$SparkUser@$SparkHost" $remoteCmd
}
catch {
    Write-Host ''
    Write-Host "ssh exited: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ''
    Write-Header 'session ended' 'DarkGray'
}
