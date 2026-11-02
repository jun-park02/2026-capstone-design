#!/bin/bash
# Kubernetes 배포 스크립트

set -e

echo "=== Kubernetes 배포 시작 ==="

# 네임스페이스 생성
echo "1. 네임스페이스 생성..."
kubectl apply -f namespace.yaml

# ConfigMap 생성
echo "2. ConfigMap 생성..."
kubectl apply -f configmap.yaml

# Redis 배포
echo "3. Redis 배포..."
kubectl apply -f redis-deployment.yaml

# Backend 배포
echo "4. Backend 배포..."
kubectl apply -f backend-deployment.yaml

# HPA 생성
echo "5. HPA 생성..."
kubectl apply -f backend-hpa.yaml

# UDP RX 배포
echo "6. UDP RX 배포..."
kubectl apply -f udp-rx-deployment.yaml

# UDP TX 배포
echo "7. UDP TX 배포..."
kubectl apply -f udp-tx-deployment.yaml

echo "=== 배포 완료 ==="
echo ""
echo "상태 확인:"
kubectl get all -n capstone-design
echo ""
echo "HPA 상태:"
kubectl get hpa -n capstone-design

