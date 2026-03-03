# Kubernetes 업그레이드 — 요구사항 (Recipe)

AI가 맨 처음 읽는 요구사항표. 아래 필수 항목을 채우면 자동으로 검증 → 라우팅 → 실행된다.

## 필수 항목 (6개)

| 항목 | 설명 | 허용 값 / 예시 |
|------|------|----------------|
| `environment` | 인프라 유형 | `aws` \| `on-prem` |
| `platform` | 구체 플랫폼 | `eks` \| `kubespray` |
| `iac` | IaC 도구 | `terraform` \| `none` |
| `cluster_name` | 클러스터 식별자 (kubectl/aws 대상) | `my-eks-prod` |
| `current_version` | 현재 K8s 버전 (따옴표 필수) | `"1.34"` |
| `target_version` | 업그레이드할 버전 (따옴표 필수) | `"1.35"` |

## 선택 항목

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `output_language` | `ko` | 최종 보고서 언어. `ko` = 한국어, `en` = English |
| `notes` | (비움) | 특이사항, 제약조건, 추가 지시사항 |

## 규칙

- 필수 항목이 **하나라도** 비어 있으면 업그레이드 절차를 시작하지 않는다.
- `terraform_path`, `kubespray_path` 등 경로는 AI가 프로젝트 구조에서 자동 탐색한다.
- 마이너 버전은 **1단계씩만** 업그레이드 가능 (1.34 → 1.36 직접 불가).

## 작성 (아래 블록 채우기)

```yaml
environment: aws    # aws | on-prem
platform: eks    # eks | kubespray
iac: terraform               # terraform | none
cluster_name: upgrade-test      # 클러스터 식별자
current_version: "1.33"
target_version: "1.34"

# 선택 항목
output_language: ko   # ko | en
notes: "karpenter와 managed nodegroup 같이 사용 중"             # 특이사항 기입
```
