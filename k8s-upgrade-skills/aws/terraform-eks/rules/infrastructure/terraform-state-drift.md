---
id: INF-001
name: Terraform 상태 드리프트 검증
severity: HIGH
category: infrastructure
phase: pre-flight
applies_when: 항상
---

# INF-001: Terraform 상태 드리프트 검증

## 목적

Terraform 외부에서 수동으로 변경된 리소스가 있으면 `terraform apply` 시 예상치 못한 변경이 발생할 수 있다. 업그레이드 전에 현재 상태와 Terraform 상태가 일치하는지 확인한다.

## 검증 명령어

### 1. 업그레이드 변경 전 현재 상태 plan

```bash
# 아직 tfvars를 수정하기 전에 실행 — 현재 상태에서 drift 확인
cd "${TF_DIR}" && terraform plan -detailed-exitcode 2>&1 | tail -20
# exit code: 0=no changes, 1=error, 2=changes detected
```

### 2. Drift 내용 분석

```bash
# drift가 있으면 상세 내용 확인
cd "${TF_DIR}" && terraform plan -no-color 2>&1 | grep -E '^\s*(~|+|-|<=)' | head -30
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| exit code 0 (no changes) | ✅ PASS | 진행 |
| exit code 2 + 비파괴적 변경만 | ⚠️ WARN | 보고 — drift 내용 확인 후 사용자 승인 시 진행 |
| exit code 2 + destroy/recreate 포함 | ❌ FAIL | STOP — drift 해소 후 재시도 |
| exit code 1 (error) | ❌ FAIL | STOP — Terraform 오류 해결 필요 |

## 조치 방안

```bash
# 비파괴적 drift 해소
cd "${TF_DIR}" && terraform apply -auto-approve

# 또는 Terraform state에 현재 상태 반영
terraform import <RESOURCE_ADDRESS> <RESOURCE_ID>

# 또는 state에서 제거 후 재생성
terraform state rm <RESOURCE_ADDRESS>
```
