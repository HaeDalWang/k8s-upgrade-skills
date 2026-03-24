# EKS + Terraform 예제

EKS 클러스터 + Karpenter + Add-on 구성 참조 Terraform 코드.
K8s 업그레이드 스킬의 Phase 0~7 검증 대상으로 사용한다.

## 구조

```
├── recipe.md                # 업그레이드 요구사항 (AI Agent가 읽는 파일)
└── terraform/
    ├── eks.tf               # EKS 클러스터, Karpenter, Add-on, StorageClass
    ├── workload.tf          # 검증용 워크로드 (Valkey, 트래픽 생성기, Deprecated API)
    ├── network.tf           # VPC, 서브넷
    ├── variables.tf         # 입력 변수
    ├── terraform.tfvars     # 변수 값
    └── yamls/               # 업그레이드 위험 시나리오 샘플 (6개)
```

## 사용법

```bash
# 1. Terraform 배포
cd terraform
terraform init
terraform plan
terraform apply

# 2. 위험 시나리오 배포 (선택)
kubectl apply -f yamls/

# 3. AI Agent에게 업그레이드 요청
#    recipe.md의 current_version / target_version 확인 후:
#    "EKS 클러스터를 업그레이드해줘"

# 4. 시나리오 정리
kubectl delete namespace upgrade-risk-demo
```

## recipe.md

```yaml
environment: aws
platform: eks
iac: terraform
cluster_name: my-eks-prod
current_version: "1.33"
target_version: "1.34"
```

`current_version`과 `target_version`을 실제 클러스터에 맞게 수정 후 사용.
