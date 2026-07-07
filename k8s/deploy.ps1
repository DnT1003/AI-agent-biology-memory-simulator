# ================================================================
# DEPLOY SCRIPT - Chay theo thu tu dung
# Usage: .\k8s\deploy.ps1
# Yeu cau: kubectl, Docker Desktop voi K8s enabled
# ================================================================

Write-Host "=== AURA AI - K8s Deploy ===" -ForegroundColor Cyan

# ---- BUOC 0: Tat mang host de chay WSL2 path ----
# ---- BUOC 0: Tao thu muc tren Windows (Docker Desktop WSL2 mount C:\ = /mnt/c/) ----
# Windows: C:\aura\* ←→ WSL2/K8s node: /mnt/c/aura/*
$AURA_ROOT = "C:\aura"
if (-not (Test-Path $AURA_ROOT)) {
    New-Item -ItemType Directory -Path `
        "$AURA_ROOT\outputs", `
        "$AURA_ROOT\chroma_db", `
        "$AURA_ROOT\slm" -Force | Out-Null
    Write-Host "[OK] Tao thu muc: $AURA_ROOT\{outputs, chroma_db, slm}" -ForegroundColor Green
    Write-Host "     -> Trong K8s node: /mnt/c/aura/{outputs, chroma_db, slm}" -ForegroundColor Gray
}

# ---- BUOC 1: Build Docker images ----
Write-Host "`n[1/7] Build Docker images..." -ForegroundColor Yellow
Set-Location $PSScriptRoot\..

docker build -f Dockerfile.brain    -t aura/brain:latest .
docker build -f Dockerfile.gpu      -t aura/gpuservice:latest .
docker build -f Dockerfile.dashboard -t aura/dashboard:latest .
# ChromaDB dung official image, khong can build
Write-Host "[OK] Build xong" -ForegroundColor Green

# ---- BUOC 2: Namespace ----
Write-Host "`n[2/7] Tao namespace..." -ForegroundColor Yellow
kubectl apply -f k8s/namespace.yaml

# ---- BUOC 3: GPU Time-Slicing ----
Write-Host "`n[3/7] Cau hinh NVIDIA GPU time-slicing..." -ForegroundColor Yellow
kubectl apply -f k8s/gpu-timeslicing.yaml
Write-Host "[INFO] Restart nvidia-device-plugin neu co..." -ForegroundColor Gray
kubectl rollout restart daemonset/nvidia-device-plugin-daemonset -n kube-system 2>$null

# ---- BUOC 4: Secrets + ConfigMap ----
Write-Host "`n[4/7] Secrets & ConfigMap..." -ForegroundColor Yellow
# Nhac user nhap API key neu chua co
if (-not (kubectl get secret aura-secrets -n aura 2>$null)) {
    $API_KEY = Read-Host "Nhap Gemini API Key"
    kubectl create secret generic aura-secrets `
        --from-literal=API_KEY=$API_KEY `
        --namespace=aura
}
kubectl apply -f k8s/configmap.yaml

# ---- BUOC 5: Storage ----
Write-Host "`n[5/7] PersistentVolumes & PVCs..." -ForegroundColor Yellow
kubectl apply -f k8s/storage-pvc.yaml

# ---- BUOC 6: Services (theo thu tu phu thuoc) ----
Write-Host "`n[6/7] Deploy services..." -ForegroundColor Yellow

# ChromaDB truoc
kubectl apply -f k8s/chroma-deployment.yaml
Write-Host "  Cho ChromaDB san sang..."
kubectl wait --for=condition=available deployment/aura-chromadb -n aura --timeout=120s

# GPU (Gemma 4 E4B chay trong aura-gpu container hoac aura-brain truc tiep)
kubectl apply -f k8s/gpu-deployment.yaml
Write-Host "  [INFO] Gemma 4 E4B se duoc load tu PVC gemma-pvc khi Brain khoi dong"
kubectl wait --for=condition=available deployment/aura-gpu-deploy -n aura --timeout=120s

# Brain sau khi Chroma OK (initContainer da xu ly)
kubectl apply -f k8s/brain-deployment.yaml

# Dashboard cuoi
kubectl apply -f k8s/dashboard-deployment.yaml

# ---- BUOC 7: Ingress ----
Write-Host "`n[7/7] Ingress..." -ForegroundColor Yellow
# Cai nginx ingress controller neu chua co
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml 2>$null
kubectl apply -f k8s/ingress.yaml

Write-Host "`n=== DEPLOY XONG ===" -ForegroundColor Green
Write-Host "Them vao C:\Windows\System32\drivers\etc\hosts:" -ForegroundColor Cyan
Write-Host "  127.0.0.1  aura.local"
Write-Host "Sau do truy cap: http://aura.local" -ForegroundColor Cyan

# Kiem tra toan bo
kubectl get pods -n aura
