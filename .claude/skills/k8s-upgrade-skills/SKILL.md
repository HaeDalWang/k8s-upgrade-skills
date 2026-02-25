---
name: k8s-version-upgrade
description: 온프레미스·AWS 등 다중 인프라에서 Kubernetes 버전을 무중단(Zero-Downtime)으로 업그레이드할 때 사용. 'K8s 업그레이드', 'EKS/온프레미스 버전 올리기', '쿠버네티스 버전 업그레이드', '무중단 업그레이드' 요청 시 실행. recipe.md 사전정보 기반으로 플랫폼·IaC별 하위 스킬로 라우팅하며, 모든 Phase에서 실패 방지 검증을 포함.
---

# Kubernetes 버전 업그레이드 스킬 (루트)

다중 인프라(우선 AWS, 온프레미스)에서 쿠버네티스 버전을 **무중단·워크로드 보호** 원칙으로 업그레이드한다.
사전정보는 [recipe.md](recipe.md)에 반드시 기입하고, 환경에 맞는 **단일** 하위 스킬만 실행한다.

---

## 1. 사전정보 의무

- 스킬 사용 시 **항상** 레포 루트의 [recipe.md](recipe.md)를 먼저 읽는다.
- 필수 항목(`environment`, `platform`, `iac`, `cluster_name`, `current_version`, `target_version`)이 비어 있으면 사용자에게 채우도록 요청하고, 채워진 후에만 업그레이드 절차로 진입한다.
- **가이드라인**: 스킬 실행 전 recipe.md를 채우고, 환경에 맞는 하위 스킬(aws/terraform-eks 또는 on-prem/kubespray)만 사용할 것.

---

## 2. 라우팅 규칙

recipe.md의 `environment`, `platform`, `iac` 값에 따라 아래 한 가지 경로만 선택한다.

| 조건 | 하위 스킬 |
|------|-----------|
| `environment=aws` AND `platform=eks` AND `iac=terraform` | [aws/terraform-eks/SKILL.md](aws/terraform-eks/SKILL.md) |
| `environment=on-prem` AND `platform=kubespray` | [on-prem/kubespray/SKILL.md](on-prem/kubespray/SKILL.md) |

- 그 외 조합은 "해당하는 하위 스킬이 없음"으로 안내하고, recipe 수정(또는 지원 플랫폼 추가)을 제안한다.
- 선택된 하위 스킬의 내용만 실행한다. 다른 플랫폼 절차를 섞지 않는다.
- (Deprecated: 이전 경로 `terraform-eks-version-upgrade/`는 사용하지 않는다. EKS+Terraform은 `aws/terraform-eks/`만 사용.)

---

## 3. MCP (기본 사용)

스킬 사용 시 프로젝트 루트의 [.mcp.json](.mcp.json)에 정의된 MCP를 **기본으로 사용**한다.

- **awslabs.eks-mcp-server**: EKS 클러스터 Insights, 리소스 조회 (get_eks_insights, list_k8s_resources 등)
- **terraform** (hashicorp/terraform-mcp-server): Terraform plan/apply
- **kubernetes** (kubernetes-mcp-server): 노드·Pod 상태 등 클러스터 조회

이 스킬을 사용할 때는 .mcp.json에 정의된 MCP가 활성화되어 있어야 한다.

---

## 4. 공통 안전 원칙

- **버전 스킵 금지**: 마이너 버전은 1단계씩만 허용 (예: 1.33 → 1.35 직접 업그레이드 불가).
- **Control Plane 선행**: Control Plane(또는 첫 control-plane 노드) 업그레이드 후 Data Plane.
- **Phase 게이트**: 모든 Phase 경계에서 "검증 통과 후에만 다음 단계"를 적용; 실패 시 즉시 중단하고 사용자에게 보고.

---

## 5. 실행 흐름

1. [recipe.md](recipe.md) 읽기 → 필수 항목 검증
2. 라우팅 규칙으로 단일 하위 스킬 선택
3. 해당 하위 스킬의 Phase 0부터 순서대로 실행 (각 Phase 검증 통과 후에만 다음 Phase 진행)
