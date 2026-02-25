# Kubernetes 업그레이드 스킬 — 사전정보 (Recipe)

스킬 실행 전 이 파일을 채운 뒤, 환경에 맞는 하위 스킬(aws/terraform-eks 또는 on-prem/kubespray)만 사용한다.

## 필수 항목

| 항목 | 설명 | 예시 |
|------|------|------|
| `environment` | 인프라 유형 | `aws` \| `on-prem` |
| `platform` | 구체 플랫폼 | `eks` \| `kubespray` \| `k3s` (추가 가능) |
| `iac` | 인프라 as Code | `terraform` \| `helm` \| `none` |
| `cluster_name` | 클러스터 식별자 | `my-eks-prod` |
| `current_version` | 현재 K8s 버전 | `1.34` |
| `target_version` | 목표 버전 | `1.35` |

## 조건부/선택 항목

| 항목 | 설명 | 예시 | 비고 |
|------|------|------|------|
| `terraform_path` | Terraform 루트 (IaC=terraform일 때) | `./infra/eks` | terraform 사용 시 필수 |
| `node_type` | 노드 구성 | `managed_node_group` \| `karpenter` \| `kubespray` \| `혼합` | 선택 |

## 작성 예시 (AWS EKS + Terraform)

```yaml
environment: aws
platform: eks
iac: terraform
cluster_name: my-eks-prod
current_version: "1.34"
target_version: "1.35"
terraform_path: ./infra/eks
node_type: 혼합
```

## 작성 예시 (온프레미스 Kubespray)

```yaml
environment: on-prem
platform: kubespray
iac: none
cluster_name: onprem-prod
current_version: "1.34"
target_version: "1.35"
node_type: kubespray
```

---

**가이드라인**: 필수 항목이 비어 있으면 스킬이 업그레이드 절차를 시작하지 않는다. 먼저 이 파일을 채운 뒤 스킬을 실행할 것.
