# EKS + Terraform 예제

K8s Upgrade Skills를 테스트하기 위한 EKS 참조 인프라입니다.
EKS 클러스터 + Managed Node Group + Karpenter + Add-on 구성이 포함되어 있고, 업그레이드 시 발생할 수 있는 위험 시나리오 샘플도 함께 제공합니다.

## 사전 준비

- AWS CLI 설정 완료 (`aws sts get-caller-identity` 확인)
- Terraform >= 1.13.0
- kubectl

## Quick Start

```bash
# 1. 인프라 배포
cd terraform
terraform init
terraform plan
terraform apply

# 2. kubeconfig 설정
aws eks update-kubeconfig --name <cluster_name> --region ap-northeast-2

# 3. (선택) 위험 시나리오 배포 — Phase 0 사전 검증 테스트용
kubectl apply -f yamls/

# 4. recipe.md의 current_version / target_version 확인 후
#    AI Agent에게 요청: "EKS 클러스터를 업그레이드해줘"
```

## 구조

```
├── recipe.md                # 업그레이드 요구사항 (AI Agent가 읽는 파일)
└── terraform/
    ├── eks.tf               # EKS 클러스터, Karpenter, Add-on, StorageClass
    ├── network.tf           # VPC, 서브넷
    ├── variables.tf         # 입력 변수
    ├── terraform.tfvars     # 변수 값 (버전, AMI alias 등)
    └── yamls/               # 업그레이드 위험 시나리오 샘플
        ├── 00-namespace.yaml
        ├── workload-valkey.yaml            # Valkey StatefulSet + PVC
        ├── workload-traffic-generator.yaml # 업그레이드 중 downtime 측정
        ├── scenario-pdb-blocking.yaml      # PDB disruptionsAllowed=0
        ├── scenario-single-replica.yaml    # 단일 레플리카 Deployment
        ├── scenario-pv-zone-affinity.yaml  # PV AZ 고정 StatefulSet
        ├── scenario-local-storage.yaml     # hostPath/emptyDir 사용
        ├── scenario-long-running-job.yaml  # 장시간 Job/CronJob
        ├── scenario-topology-spread.yaml   # DoNotSchedule TSC
        └── scenario-resource-pressure.yaml # 리소스 압박 Pod
```

## recipe.md

```yaml
environment: aws
platform: eks
iac: terraform
cluster_name: upgrade-skill     # terraform.tfvars의 cluster_name과 일치
current_version: "1.33"         # 현재 클러스터 버전
target_version: "1.34"          # 반드시 current_version의 차기 마이너 버전
output_language: ko
```

`current_version`과 `target_version`을 실제 클러스터에 맞게 수정 후 사용하세요.

## 위험 시나리오 (yamls/)

Phase 0 사전 검증이 실제로 위험을 감지하는지 테스트하기 위한 샘플입니다.

| 시나리오 | 파일 | 감지 규칙 | 예상 결과 |
|----------|------|-----------|-----------|
| PDB 차단 | `scenario-pdb-blocking.yaml` | WLS-001 | CRITICAL |
| 단일 레플리카 | `scenario-single-replica.yaml` | WLS-002 | WARN |
| PV AZ 고정 | `scenario-pv-zone-affinity.yaml` | WLS-003 | CRITICAL |
| 로컬 스토리지 | `scenario-local-storage.yaml` | WLS-004 | WARN |
| 장시간 Job | `scenario-long-running-job.yaml` | WLS-005 | WARN |
| 토폴로지 제약 | `scenario-topology-spread.yaml` | WLS-006 | WARN |
| 리소스 압박 | `scenario-resource-pressure.yaml` | CAP-002 | WARN |

## 정리

```bash
# 위험 시나리오만 정리
kubectl delete namespace workload
kubectl delete namespace upgrade-risk-demo

# 전체 인프라 삭제
cd terraform
terraform destroy
```
