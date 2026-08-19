# ================================================================
# DEPLOY SCRIPT - Chay theo thu tu dung
# Usage: .\k8s\deploy.ps1
# Yeu cau: kubectl, Docker Desktop voi K8s enabled
# ================================================================

Write-Host "=== AURA AI - K8s Deploy ===" -ForegroundColor Cyan
$ErrorActionPreference = "Stop"

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

# ---- BUOC 0: Tat mang host de chay WSL2 path ----
# ---- BUOC 0: Tao thu muc tren Windows (Docker Desktop WSL2 mount C:\ = /mnt/c/) ----
# Windows: C:\aura\* ←→ WSL2/K8s node: /mnt/c/aura/*
$AURA_ROOT = "C:\aura"
New-Item -ItemType Directory -Path `
    "$AURA_ROOT\outputs", `
    "$AURA_ROOT\chroma_db", `
    "$AURA_ROOT\slm" -Force | Out-Null
Write-Host "[OK] Bao dam thu muc: $AURA_ROOT\{outputs, chroma_db, slm}" -ForegroundColor Green
Write-Host "     -> Trong K8s node: /mnt/c/aura/{outputs, chroma_db, slm}" -ForegroundColor Gray

# ---- BUOC 1: Build Docker images ----
Write-Host "`n[1/7] Build Docker images..." -ForegroundColor Yellow
Set-Location $PSScriptRoot\..

Invoke-CheckedNative docker @("build", "-f", "Dockerfile.brain", "-t", "aura/brain:latest", ".")
Invoke-CheckedNative docker @("build", "-f", "Dockerfile.gpu", "-t", "aura/gpuservice:latest", ".")
Invoke-CheckedNative docker @("build", "-f", "Dockerfile.dashboard", "-t", "aura/dashboard:latest", ".")
Invoke-CheckedNative docker @("build", "-f", "Dockerfile.chroma", "-t", "aura/chromadb:latest", ".")
Write-Host "[OK] Build xong" -ForegroundColor Green

# ---- BUOC 2: Namespace ----
Write-Host "`n[2/7] Tao namespace..." -ForegroundColor Yellow
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/namespace.yaml")

# ---- BUOC 3: GPU Time-Slicing ----
Write-Host "`n[3/7] Cau hinh NVIDIA GPU time-slicing..." -ForegroundColor Yellow
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/gpu-timeslicing.yaml")
Write-Host "[INFO] Restart nvidia-device-plugin neu co..." -ForegroundColor Gray
kubectl rollout restart daemonset/nvidia-device-plugin-daemonset -n kube-system 2>$null

# ---- BUOC 4: Secrets + ConfigMap ----
Write-Host "`n[4/7] Secrets & ConfigMap..." -ForegroundColor Yellow
# Nhac user nhap API key neu chua co
if (-not (kubectl get secret aura-secrets -n aura 2>$null)) {
    $API_KEY = Read-Host "Nhap Gemini API Key"
    Invoke-CheckedNative kubectl @(
        "create", "secret", "generic", "aura-secrets",
        "--from-literal=API_KEY=$API_KEY", "--namespace=aura"
    )
}
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/configmap.yaml")

# ---- BUOC 5: Storage ----
Write-Host "`n[5/7] PersistentVolumes & PVCs..." -ForegroundColor Yellow
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/storage-pvc.yaml")

# ---- BUOC 6: Services (theo thu tu phu thuoc) ----
Write-Host "`n[6/7] Deploy services..." -ForegroundColor Yellow

# ChromaDB truoc
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/chroma-deployment.yaml")
Write-Host "  Cho ChromaDB san sang..."
Invoke-CheckedNative kubectl @("wait", "--for=condition=available", "deployment/aura-chromadb", "-n", "aura", "--timeout=120s")

# GPU service currently owns native perception and optional SLM inference.
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/gpu-deployment.yaml")
Invoke-CheckedNative kubectl @("wait", "--for=condition=available", "deployment/aura-gpu-deploy", "-n", "aura", "--timeout=360s")

# Brain sau khi Chroma OK (initContainer da xu ly)
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/brain-deployment.yaml")

# Dashboard cuoi
Invoke-CheckedNative kubectl @("apply", "-f", "k8s/dashboard-deployment.yaml")

# ---- BUOC 7: Ingress ----
Write-Host "`n[7/7] Ingress..." -ForegroundColor Yellow
if ($env:AURA_ENABLE_UNSAFE_INGRESS -eq "true") {
    Write-Warning "Ingress has no authentication/TLS and is intended only for an isolated local machine."
    Invoke-CheckedNative kubectl @("apply", "-f", "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml")
    Invoke-CheckedNative kubectl @("apply", "-f", "k8s/ingress.yaml")
} else {
    Write-Host "[SAFE DEFAULT] Khong expose Ingress. Dung kubectl port-forward service/aura-dashboard-svc 8050:80 -n aura" -ForegroundColor Yellow
}

Write-Host "`n=== DEPLOY XONG ===" -ForegroundColor Green
Write-Host "Them vao C:\Windows\System32\drivers\etc\hosts:" -ForegroundColor Cyan
Write-Host "  127.0.0.1  aura.local"
Write-Host "Chi truy cap http://aura.local neu da explicit bat AURA_ENABLE_UNSAFE_INGRESS=true." -ForegroundColor Cyan

# Kiem tra toan bo
Invoke-CheckedNative kubectl @("get", "pods", "-n", "aura")
