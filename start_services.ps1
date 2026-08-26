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

$gpuLive = $false
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8001/live" -TimeoutSec 2 -ErrorAction Stop
    if ($resp.status -eq "alive") {
        Write-Host "      GPU Service da chay; dang kiem tra readiness..." -ForegroundColor Green
        $gpuLive = $true
    }
} catch {}

$gpuStartedHere = $false
$gpuJob = $null

if (-not $gpuLive) {
    Write-Host "      Dang khoi dong GPU Microservice (tai model vao VRAM)..." -ForegroundColor Yellow
    $gpuJob = Start-Process `
        -FilePath $VenvPython `
        -ArgumentList "core/server/gpu_service.py" `
        -WorkingDirectory $ScriptDir `
        -PassThru `
        -WindowStyle Normal

    $gpuStartedHere = $true

    Write-Host "      GPU Service PID: $($gpuJob.Id) | port 8001" -ForegroundColor Green
    Write-Host "      (Cho den khi cua so GPU Service hien 'Aura GPU Service san sang')" -ForegroundColor DarkYellow
}

    # Chờ GPU service sẵn sàng (có thể mất 30-60s do load model)
$gpuReady = $false
$maxWait = 90
$waited = 0
while ($waited -le $maxWait) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8001/ready" -TimeoutSec 1 -ErrorAction Stop
        if (($resp.status -eq "ready") -and ($resp.ready -eq $true)) {
            Write-Host "      GPU Service san sang sau $waited giay!" -ForegroundColor Green
            $gpuReady = $true
            break
        }
    } catch {}

    # Fail fast only for the child process started by this script. When the
    # service was already live, $gpuStartedHere stays false and $gpuJob is not
    # dereferenced.
    if ($gpuStartedHere -and ($null -ne $gpuJob) -and $gpuJob.HasExited) {
        Write-Host "      [ERROR] GPU Service ket thuc truoc khi san sang. Kiem tra log khoi dong GPU Service, sua loi, roi chay lai." -ForegroundColor Red
        exit 1
    }

    if ($waited -lt $maxWait) {
        Start-Sleep -Seconds 2
        $waited += 2
    } else {
        break
    }
}

if (-not $gpuReady) {
    Write-Host "      [ERROR] GPU Service khong san sang sau ${maxWait}s." -ForegroundColor Red
    exit 1
}

# ─── Summary ──────────────────────────────────────────────────
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Tat ca Services da chay!" -ForegroundColor Green
Write-Host "  ChromaDB  : http://127.0.0.1:8000" -ForegroundColor White
Write-Host "  GPU Svc   : http://127.0.0.1:8001/ready" -ForegroundColor White
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tiep theo: chay 'python main.py' bang Python 3.14" -ForegroundColor Yellow
Write-Host ""
