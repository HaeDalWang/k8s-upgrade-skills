---
id: INF-004
name: Terraform Recreate 감지
severity: CRITICAL
category: infrastructure
phase: pre-flight
applies_when: 항상
---

# INF-004: Terraform Recreate 감지

## 목적

Terraform plan 결과에서 리소스 recreate(삭제 후 재생성) 마커를 감지하여, 의도치 않은 데이터 플레인 리소스 파괴를 업그레이드 전에 차단한다.

실제 사고 사례: 관리형 노드그룹 이름에 `name_prefix`를 사용하지 않은 상태에서 AL2 → AL2023 AMI 강제 마이그레이션 시 `forces replacement` 발생 → 노드그룹 전체 recreate → 서비스 중단. 이러한 사고를 Phase 0 사전 검증 단계에서 차단하는 것이 목적이다.

## 위험 시나리오

### 시나리오 1: 관리형 노드그룹 이름 변경 → recreate

`node_group_name` 속성은 ForceNew 속성으로, 변경 시 노드그룹 전체가 삭제 후 재생성된다.

```
# terraform plan 출력 예시
-/+ resource "aws_eks_node_group" "managed" {
      ~ node_group_name = "eks-system-20240101" -> "eks-system-20240201" # forces replacement
      # (all other attributes unchanged)
    }

Plan: 1 to add, 0 to change, 1 to destroy.
```

### 시나리오 2: AMI 타입 변경(AL2→AL2023) → launch template recreate

EKS 모듈 업그레이드 시 `ami_type`이 `AL2_x86_64`에서 `AL2023_x86_64_STANDARD`로 변경되면 launch template이 recreate된다.

```
# terraform plan 출력 예시
-/+ resource "aws_launch_template" "managed" {
      ~ image_id = "ami-0abcdef1234567890" -> (known after apply)
        # must be replaced
      ~ name     = "eks-managed-20240101" -> (known after apply)
    }

  # module.eks.aws_eks_node_group.managed will be updated in-place
  ~ resource "aws_eks_node_group" "managed" {
      ~ ami_type = "AL2_x86_64" -> "AL2023_x86_64_STANDARD"
    }

Plan: 1 to add, 1 to change, 1 to destroy.
```

### 시나리오 3: 서브넷 변경 → 노드그룹 recreate

`subnet_ids` 변경은 노드그룹의 ForceNew 속성으로, 노드그룹 전체가 삭제 후 재생성된다.

```
# terraform plan 출력 예시
-/+ resource "aws_eks_node_group" "managed" {
      ~ subnet_ids = [
          - "subnet-0aaa1111",
          + "subnet-0bbb2222",
          - "subnet-0ccc3333",
          + "subnet-0ddd4444",
        ] # forces replacement
    }

Plan: 1 to add, 0 to change, 1 to destroy.
```

## 검증 명령어

### 1. Terraform Plan 실행

```bash
cd "${TF_DIR}" && terraform plan -no-color 2>&1 | tee /tmp/tf-plan-output.txt
# exit code 1이면 즉시 FAIL — 오류 메시지 보고
if [ ${PIPESTATUS[0]} -eq 1 ]; then
  echo "❌ FAIL: terraform plan 실행 오류"
  tail -20 /tmp/tf-plan-output.txt
  exit 1
fi
```

### 2. Recreate 마커 감지

```bash
# 3가지 Recreate 마커 패턴 동시 검색
grep -E 'forces replacement|must be replaced|^\s*-/\+' /tmp/tf-plan-output.txt
```

### 3. 리소스 분류 및 판정

```bash
python3 -c "
import sys, re

plan_output = open('/tmp/tf-plan-output.txt').read()

# Recreate 마커가 포함된 리소스 주소 추출
resource_pattern = re.compile(
    r'[-/+~]\s+resource\s+\"(\w+)\"\s+\"(\w+)\"'
)
marker_pattern = re.compile(
    r'(forces replacement|must be replaced)'
)
replace_pattern = re.compile(
    r'^\s*-/\+\s+resource\s+\"(\w+)\"\s+\"(\w+)\"',
    re.MULTILINE
)

DATA_PLANE_RESOURCES = {
    'aws_eks_node_group',
    'aws_launch_template',
    'aws_autoscaling_group',
}

recreate_resources = []

# -/+ 접두사로 시작하는 리소스 추출
for match in replace_pattern.finditer(plan_output):
    rtype, rname = match.group(1), match.group(2)
    recreate_resources.append((rtype, rname, '-/+'))

# forces replacement / must be replaced 마커가 있는 블록에서 리소스 추출
blocks = re.split(r'(?=[-~+]\s+resource\s+\")', plan_output)
for block in blocks:
    if marker_pattern.search(block):
        rmatch = resource_pattern.search(block)
        if rmatch:
            rtype, rname = rmatch.group(1), rmatch.group(2)
            marker = marker_pattern.search(block).group(1)
            if (rtype, rname, marker) not in recreate_resources:
                recreate_resources.append((rtype, rname, marker))

if not recreate_resources:
    print('✅ PASS: Recreate 마커 없음')
    sys.exit(0)

data_plane_hits = []
other_hits = []
for rtype, rname, marker in recreate_resources:
    addr = f'{rtype}.{rname}'
    if rtype in DATA_PLANE_RESOURCES:
        data_plane_hits.append((addr, marker))
    else:
        other_hits.append((addr, marker))

if data_plane_hits:
    print('❌ FAIL (CRITICAL): Data Plane 리소스 recreate 감지')
    for addr, marker in data_plane_hits:
        print(f'  - {addr} [{marker}]')
    sys.exit(1)

if other_hits:
    print('⚠️ WARN: 비-Data Plane 리소스 recreate 감지')
    for addr, marker in other_hits:
        print(f'  - {addr} [{marker}]')
    sys.exit(0)
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| Recreate 마커 없음 | ✅ PASS | 진행 |
| Data Plane 리소스 recreate 감지 | ❌ FAIL (CRITICAL) | STOP — recreate 원인 해소 후 재시도 |
| 비-Data Plane 리소스 recreate 감지 | ⚠️ WARN | 보고 — recreate 내용 확인 후 사용자 승인 시 진행 |
| terraform plan exit code 1 (오류) | ❌ FAIL | STOP — Terraform 오류 해결 필요 |

## 조치 방안

### 1. `lifecycle { ignore_changes }` 적용

특정 속성 변경이 recreate를 유발하지만 실제로는 무시해도 되는 경우:

```hcl
resource "aws_eks_node_group" "managed" {
  # ...
  lifecycle {
    ignore_changes = [node_group_name]
  }
}
```

### 2. `name_prefix` 사용

노드그룹 이름을 고정하지 않고 prefix 기반으로 생성하여 이름 변경에 의한 recreate 방지:

```hcl
resource "aws_eks_node_group" "managed" {
  node_group_name_prefix = "eks-system-"
  # node_group_name 대신 prefix 사용 → 이름 변경 시 recreate 방지
}
```

### 3. `create_before_destroy` 전략

불가피하게 recreate가 필요한 경우, 새 리소스를 먼저 생성한 후 기존 리소스를 삭제하여 서비스 중단 최소화:

```hcl
resource "aws_eks_node_group" "managed" {
  # ...
  lifecycle {
    create_before_destroy = true
  }
}
```

### 4. AMI 타입 변경 시 단계적 마이그레이션

AL2 → AL2023 전환 시 한 번에 변경하지 않고, 새 노드그룹을 추가한 후 기존 노드그룹을 drain하는 Blue-Green 방식 권장:

```bash
# 1. 새 AL2023 노드그룹 추가 (terraform apply)
# 2. 기존 AL2 노드그룹 drain
kubectl drain --ignore-daemonsets --delete-emptydir-data <node-name>
# 3. 기존 AL2 노드그룹 제거 (terraform apply)
```
