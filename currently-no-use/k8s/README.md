# Kubernetes 배포 가이드

이 디렉토리에는 Kubernetes 매니페스트 파일들이 포함되어 있습니다.

## 파일 구조

- `namespace.yaml`: 네임스페이스 생성
- `configmap.yaml`: 환경 변수 설정
- `redis-deployment.yaml`: Redis 배포 및 서비스
- `backend-deployment.yaml`: FastAPI 백엔드 배포 및 서비스
- `backend-hpa.yaml`: Horizontal Pod Autoscaler (CPU 기반 오토스케일링)
- `udp-rx-deployment.yaml`: UDP 수신 서비스
- `udp-tx-deployment.yaml`: UDP 송신 서비스 (테스트용)
- `ingress.yaml`: Ingress 설정 (선택사항)

## 사전 요구사항

1. Kubernetes 클러스터 (v1.24+)
2. Metrics Server 설치 (HPA 동작을 위해 필요)
3. Docker 이미지 빌드 및 레지스트리 푸시

## 배포 순서

### 1. Metrics Server 설치 (HPA를 위해 필요)

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### 2. Docker 이미지 빌드 및 푸시

```bash
# Backend 이미지 빌드
cd backend
docker build -t your-registry/backend:latest .
docker push your-registry/backend:latest

# UDP RX 이미지 빌드
cd ../udp
docker build -t your-registry/udp-rx:latest -f Dockerfile .
docker push your-registry/udp-rx:latest

# UDP TX 이미지 빌드
docker build -t your-registry/udp-tx:latest -f Dockerfile .
docker push your-registry/udp-tx:latest
```

### 3. 이미지 이름 수정

`backend-deployment.yaml`, `udp-rx-deployment.yaml`, `udp-tx-deployment.yaml` 파일에서 이미지 이름을 실제 레지스트리 주소로 변경하세요.

### 4. 배포

```bash
# 네임스페이스 생성
kubectl apply -f namespace.yaml

# ConfigMap 생성
kubectl apply -f configmap.yaml

# Redis 배포
kubectl apply -f redis-deployment.yaml

# Backend 배포
kubectl apply -f backend-deployment.yaml

# HPA 생성
kubectl apply -f backend-hpa.yaml

# UDP 서비스 배포
kubectl apply -f udp-rx-deployment.yaml
kubectl apply -f udp-tx-deployment.yaml

# Ingress 배포 (선택사항)
kubectl apply -f ingress.yaml
```

## HPA (Horizontal Pod Autoscaler) 설정

### 현재 설정

- **최소 Replica**: 2개
- **최대 Replica**: 10개
- **스케일 아웃 조건**: CPU 사용률 70% 초과
- **스케일 다운**: 안정화 시간 60초

### HPA 상태 확인

```bash
# HPA 상태 확인
kubectl get hpa -n capstone-design

# 상세 정보
kubectl describe hpa backend-hpa -n capstone-design
```

### HPA 설정 변경

`backend-hpa.yaml` 파일을 수정하여:
- `averageUtilization`: CPU 임계값 변경
- `minReplicas`: 최소 pod 수 변경
- `maxReplicas`: 최대 pod 수 변경

## 로컬 테스트 (Minikube/Kind)

로컬에서 테스트할 경우 이미지를 빌드하고 로드:

```bash
# Minikube 사용 시
minikube image load backend:latest
minikube image load udp-rx:latest
minikube image load udp-tx:latest

# 또는 imagePullPolicy를 Never로 변경
```

## 포트 포워딩 (로컬 접근)

```bash
# Backend 서비스 포트 포워딩
kubectl port-forward -n capstone-design service/backend-service 8000:8000

# Redis 포트 포워딩
kubectl port-forward -n capstone-design service/redis-service 6379:6379
```

## 모니터링

```bash
# Pod 상태 확인
kubectl get pods -n capstone-design

# Pod 로그 확인
kubectl logs -f deployment/backend -n capstone-design

# 리소스 사용량 확인
kubectl top pods -n capstone-design
```

## 트러블슈팅

### HPA가 동작하지 않는 경우

1. Metrics Server 설치 확인:
   ```bash
   kubectl get deployment metrics-server -n kube-system
   ```

2. Pod에 리소스 요청이 설정되어 있는지 확인:
   ```bash
   kubectl describe deployment backend -n capstone-design
   ```

3. CPU 메트릭 확인:
   ```bash
   kubectl top pods -n capstone-design
   ```

### 이미지 Pull 실패

- 이미지가 레지스트리에 푸시되었는지 확인
- `imagePullPolicy`를 `IfNotPresent` 또는 `Never`로 변경 (로컬 테스트 시)

