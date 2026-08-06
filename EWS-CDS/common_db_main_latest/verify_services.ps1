# ============================================================
# Verify all local services are running and accessible
# 
# Usage: powershell -ExecutionPolicy Bypass -File verify_services.ps1
# ============================================================

Write-Host ""
Write-Host "==================================================="
Write-Host " Verifying all local services..."
Write-Host "==================================================="
Write-Host ""

$services = @(
    @{ Name = "Main API"; Port = 7015; Endpoint = "http://localhost:7015/docs" },
    @{ Name = "Data Server"; Port = 7016; Endpoint = "http://localhost:7016/docs" },
    @{ Name = "Ashmit Frontend"; Port = 4990; Endpoint = "http://localhost:4990" },
    @{ Name = "Ward Monitor API"; Port = 7816; Endpoint = "http://localhost:7816/docs" },
    @{ Name = "Ward Monitor Frontend"; Port = 4985; Endpoint = "http://localhost:4985" }
)

$allHealthy = $true

foreach ($service in $services) {
    try {
        $response = Invoke-WebRequest -Uri $service.Endpoint -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host "✓ $($service.Name) (port $($service.Port)): RUNNING"
        } else {
            Write-Host "✗ $($service.Name) (port $($service.Port)): HTTP $($response.StatusCode)"
            $allHealthy = $false
        }
    } catch {
        Write-Host "✗ $($service.Name) (port $($service.Port)): NOT RESPONDING"
        $allHealthy = $false
    }
}

Write-Host ""
if ($allHealthy) {
    Write-Host "✅ All services are healthy!"
    Write-Host ""
    Write-Host "Access points:"
    Write-Host "  • Frontend Login: http://localhost:4990"
    Write-Host "  • Ward Dashboard: http://localhost:4985"
    Write-Host "  • Main API Docs: http://localhost:7015/docs"
    Write-Host "  • Data API Docs: http://localhost:7016/docs"
    Write-Host "  • Ward API Docs: http://localhost:7816/docs"
} else {
    Write-Host "⚠️  Some services are not responding. Check the terminal windows for errors."
    Write-Host ""
    Write-Host "Common issues:"
    Write-Host "  • venv not activated (missing dependencies)"
    Write-Host "  • Port already in use (run stop_local.ps1 first)"
    Write-Host "  • Environment variables (.env.secrets not found)"
}
Write-Host ""
