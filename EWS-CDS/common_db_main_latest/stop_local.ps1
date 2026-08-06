# ============================================================
# Stop all local services spawned by start_local.ps1
# 
# Usage: powershell -ExecutionPolicy Bypass -File stop_local.ps1
# ============================================================

Write-Host ""
Write-Host "==================================================="
Write-Host " Stopping all local services..."
Write-Host "==================================================="
Write-Host ""

# Kill all Python processes running uvicorn
Write-Host "[1/2] Stopping Python services (uvicorn)..."
$pythonProcesses = Get-Process | Where-Object { $_.ProcessName -eq "python" }
if ($pythonProcesses) {
    $pythonProcesses | Stop-Process -Force
    Write-Host "       Stopped Python processes ✓"
} else {
    Write-Host "       No Python processes found"
}

# Kill all npm dev processes
Write-Host "[2/2] Stopping Node.js services (npm)..."
$nodeProcesses = Get-Process | Where-Object { $_.ProcessName -eq "node" }
if ($nodeProcesses) {
    $nodeProcesses | Stop-Process -Force
    Write-Host "       Stopped Node.js processes ✓"
} else {
    Write-Host "       No Node.js processes found"
}

Write-Host ""
Write-Host "✅ All services stopped"
Write-Host ""
Write-Host "To start again, run:"
Write-Host "   powershell -ExecutionPolicy Bypass -File start_local.ps1"
Write-Host ""
