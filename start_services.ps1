# start_services.ps1
# =============================================
# Script khởi động các Services cho Aura
# Chạy script này TRƯỚC KHI chạy main.py
# =============================================
#
# Kiến trúc:
#   .venv_aura (Python 3.12):
#     - Service 1: ChromaDB Server   → port 8000  (Vector DB)
#     - Service 2: GPU Microservice  → port 8001  (Torch/AI Models)
#   Python 3.14 (main):
#     - main.py → kết nối tới cả 2 services trên

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvPython = Join-Path $ScriptDir ".venv_aura\Scripts\python.exe"
$VenvChroma = Join-Path $ScriptDir ".venv_aura\Scripts\chroma.exe"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  AURA - Khoi dong Services" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Kiểm tra .venv_aura
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Khong tim thay .venv_aura. Hay chay 'python bootstrap.py' de tao moi." -ForegroundColor Red
    exit 1
}

# Kiem tra python co the khoi dong duoc khong (phong truong hop venv hong, tro vao root cu)
try {
    $null = & $VenvPython --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Venv hỏng" }
} catch {
    Write-Host "[ERROR] Moi truong .venv_aura da bi hong (Python link chet)." -ForegroundColor Red
    Write-Host "Vui long chay: python bootstrap.py --force" -ForegroundColor Yellow
    exit 1
}

# ─── Service 1: ChromaDB Server (port 8000) ───────────────────
Write-Host "[1/2] Kiem tra ChromaDB tai port 8000..." -ForegroundColor Yellow

$chromaRunning = $false
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v2/heartbeat" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "      ChromaDB da chay san sang!" -ForegroundColor Green
    $chromaRunning = $true
} catch {}

if (-not $chromaRunning) {
    Write-Host "      Dang khoi dong ChromaDB Server..." -ForegroundColor Yellow
    $chromaJob = Start-Process `
        -FilePath $VenvChroma `
        -ArgumentList "run --host 127.0.0.1 --port 8000 --path outputs/chroma_db" `
        -WorkingDirectory $ScriptDir `
        -PassThru `
        -WindowStyle Minimized
    Write-Host "      ChromaDB PID: $($chromaJob.Id) | port 8000" -ForegroundColor Green

    # Chờ ChromaDB sẵn sàng
    $maxWait = 15
    $waited = 0
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 1
        $waited++
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v2/heartbeat" -TimeoutSec 1 -ErrorAction Stop
            Write-Host "      ChromaDB san sang sau $waited giay!" -ForegroundColor Green
            break
        } catch {}
    }
    if ($waited -ge $maxWait) {
        Write-Host "      [WARN] ChromaDB chua san sang sau ${maxWait}s. Tiep tuc..." -ForegroundColor DarkYellow
    }
}

# ─── Service 2: GPU Microservice (port 8001) ──────────────────
Write-Host "[2/2] Kiem tra GPU Microservice tai port 8001..." -ForegroundColor Yellow

$gpuRunning = $false
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8001/health" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "      GPU Service da chay san sang!" -ForegroundColor Green
    $gpuRunning = $true
} catch {}

if (-not $gpuRunning) {
    Write-Host "      Dang khoi dong GPU Microservice (tai model vao VRAM)..." -ForegroundColor Yellow
    $gpuJob = Start-Process `
        -FilePath $VenvPython `
        -ArgumentList "core/server/gpu_service.py" `
        -WorkingDirectory $ScriptDir `
        -PassThru `
        -WindowStyle Normal

    Write-Host "      GPU Service PID: $($gpuJob.Id) | port 8001" -ForegroundColor Green
    Write-Host "      (Cho den khi cua so GPU Service hien 'Aura GPU Service san sang')" -ForegroundColor DarkYellow

    # Chờ GPU service sẵn sàng (có thể mất 30-60s do load model)
    $maxWait = 90
    $waited = 0
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 2
        $waited += 2
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8001/health" -TimeoutSec 1 -ErrorAction Stop
            Write-Host "      GPU Service san sang sau $waited giay! GPU: $($resp.gpu_name)" -ForegroundColor Green
            break
        } catch {}
    }
    if ($waited -ge $maxWait) {
        Write-Host "      [WARN] GPU Service chua san sang sau ${maxWait}s." -ForegroundColor DarkYellow
    }
}

# ─── Summary ──────────────────────────────────────────────────
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Tat ca Services da chay!" -ForegroundColor Green
Write-Host "  ChromaDB  : http://127.0.0.1:8000" -ForegroundColor White
Write-Host "  GPU Svc   : http://127.0.0.1:8001/health" -ForegroundColor White
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tiep theo: chay 'python main.py' bang Python 3.14" -ForegroundColor Yellow
Write-Host ""
