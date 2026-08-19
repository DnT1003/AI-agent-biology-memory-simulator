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

function Invoke-CheckedSecretNative {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $false)][string]$Description = "Secret operation"
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Secret command failed ($LASTEXITCODE): $Description"
    }
}

function New-AuraAuthToken {
    $bytes = New-Object byte[] 32
    $rng = $null
    try {
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
    }
    finally {
        if ($null -ne $rng) {
            $rng.Dispose()
        }
    }
    $base64 = [Convert]::ToBase64String($bytes)
    return $base64.Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

function Test-AuraValidAuthToken {
    param(
        [Parameter(Mandatory = $false)][string]$Base64Value
    )
    if ([string]::IsNullOrWhiteSpace($Base64Value)) {
        return $false
    }
    try {
        $bytes = [Convert]::FromBase64String($Base64Value.Trim())
        foreach ($b in $bytes) {
            if ($b -gt 127) {
                return $false
            }
        }
        $decoded = [System.Text.Encoding]::ASCII.GetString($bytes)
        if ($decoded.Length -lt 32 -or $decoded.Length -gt 256) {
            return $false
        }
        return ($decoded -cmatch '^[a-zA-Z0-9_\-\.~+/=]{32,256}$')
    }
    catch {
        return $false
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
$existingSecretRaw = kubectl get secret aura-secrets -n aura -o json --ignore-not-found 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to query secret aura-secrets ($LASTEXITCODE)"
}
$existingSecretJson = if ($existingSecretRaw) { ($existingSecretRaw -join "`n").Trim() } else { "" }
if (-not $existingSecretJson) {
    $API_KEY = Read-Host "Nhap Gemini API Key"
    $dashboardToken = New-AuraAuthToken
    $gpuToken = New-AuraAuthToken
    Invoke-CheckedSecretNative kubectl @(
        "create", "secret", "generic", "aura-secrets",
        "--from-literal=API_KEY=$API_KEY",
        "--from-literal=AURA_DASHBOARD_AUTH_TOKEN=$dashboardToken",
        "--from-literal=AURA_GPU_SERVICE_AUTH_TOKEN=$gpuToken",
        "--namespace=aura"
    ) "create aura-secrets"
} else {
    $secretObj = $existingSecretJson | ConvertFrom-Json
    $dataObj = if ($secretObj -and $secretObj.data) { $secretObj.data } else { $null }
    $patchData = @{}
    $tokenKeys = @("AURA_DASHBOARD_AUTH_TOKEN", "AURA_GPU_SERVICE_AUTH_TOKEN")
    foreach ($tokenKey in $tokenKeys) {
        $existingVal = if ($dataObj -and $dataObj.PSObject.Properties[$tokenKey]) {
            [string]$dataObj.PSObject.Properties[$tokenKey].Value
        } else {
            $null
        }
        if (-not (Test-AuraValidAuthToken $existingVal)) {
            $newToken = New-AuraAuthToken
            $patchData[$tokenKey] = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($newToken))
        }
    }
    if ($patchData.Count -gt 0) {
        $patchJson = @{ data = $patchData } | ConvertTo-Json -Compress
        Invoke-CheckedSecretNative kubectl @(
            "patch", "secret", "aura-secrets",
            "-n", "aura",
            "-p", $patchJson
        ) "patch aura-secrets"
    }
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
Write-Host "`nDe lay Dashboard Auth Token truy cap web:" -ForegroundColor Cyan
Write-Host "  [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String((kubectl get secret aura-secrets -n aura -o jsonpath='{.data.AURA_DASHBOARD_AUTH_TOKEN}')))" -ForegroundColor Yellow

# Kiem tra toan bo
Invoke-CheckedNative kubectl @("get", "pods", "-n", "aura")
