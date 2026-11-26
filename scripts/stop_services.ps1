# Stop DSHQuant local services by listening port (deck :8787 / HARNESS :3080).
# Called by "停止.cmd"; or run directly:
#   powershell -ExecutionPolicy Bypass -File scripts\stop_services.ps1
# NOTE: keep this file ASCII-only — Windows PowerShell 5.1 reads it as ANSI without a BOM,
# so non-ASCII bytes corrupt the script.
$ErrorActionPreference = "SilentlyContinue"
$ports = @(8787, 3080)
$targets = Get-NetTCPConnection -State Listen | Where-Object { $ports -contains $_.LocalPort }
if (-not $targets) {
    Write-Host "No process is listening on 8787 / 3080 (already stopped)."
    return
}
foreach ($c in $targets) {
    $proc = Get-Process -Id $c.OwningProcess
    Write-Host ("Stop {0} (PID {1}, port {2})" -f $proc.ProcessName, $c.OwningProcess, $c.LocalPort)
    Stop-Process -Id $c.OwningProcess -Force
}
Write-Host "Stopped."
