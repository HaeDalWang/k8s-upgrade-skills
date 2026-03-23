---
id: COM-003
name: Add-on 호환성 사전 검증
severity: HIGH
category: common
phase: pre-flight
applies_when: 항상
---

# COM-003: Add-on 호환성 사전 검증

## 목적

EKS Add-on이 대상 버전과 호환되는지 사전에 확인한다. 호환되지 않는 Add-on이 있으면 업그레이드 후 DEGRADED 상태에 빠질 수 있다. 또한 `most_recent = true`로 설정된 Add-on은 Terraform apply 시 자동으로 최신 호환 버전으로 업데이트되지만, 고정 버전을 사용하는 경우 수동 업데이트가 필요하다.

## 검증 항목

### 1. 현재 Add-on 상태 및 버전

```bash
aws eks list-addons --cluster-name ${CLUSTER_NAME} --query 'addons[]' --output text \
  | tr '\t' '\n' | while read addon; do
    aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name "$addon" \
      --query '{name:addon.addonName, version:addon.addonVersion, status:addon.status}' --output json
  done
```

### 2. 대상 버전 호환 Add-on 버전 조회

```bash
# 각 Add-on의 TARGET_VERSION 호환 버전 확인
for addon in $(aws eks list-addons --cluster-name ${CLUSTER_NAME} --query 'addons[]' --output text | tr '\t' '\n'); do
  echo "=== $addon ==="
  aws eks describe-addon-versions \
    --addon-name "$addon" \
    --kubernetes-version "${TARGET_VERSION}" \
    --query 'addons[0].addonVersions[0].{version:addonVersion, defaultVersion:compatibilities[0].defaultVersion}' \
    --output json 2>/dev/null || echo "TARGET_VERSION 호환 버전 없음"
done
```

### 3. Terraform Add-on 설정 확인

```bash
# most_recent = true 여부 확인
grep -A5 'most_recent' "${TF_DIR}"/*.tf | head -30

# 고정 버전 사용 여부 확인
grep -E 'addon_version|version.*=.*v[0-9]' "${TF_DIR}"/*.tf | head -20
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 모든 Add-on ACTIVE, TARGET_VERSION 호환 버전 존재 | ✅ PASS | 진행 |
| Add-on DEGRADED/CREATE_FAILED | ❌ FAIL | STOP — Add-on 복구 후 재시도 |
| TARGET_VERSION 호환 버전 없음 | ⚠️ WARN | 보고 — 해당 Add-on 업데이트 계획 필요 |
| 고정 버전 사용 + 호환성 미확인 | ⚠️ WARN | 보고 — Terraform 변수 업데이트 필요 가능성 |

## 조치 방안

```bash
# Add-on 복구
aws eks update-addon --cluster-name ${CLUSTER_NAME} \
  --addon-name <ADDON_NAME> \
  --resolve-conflicts OVERWRITE

# 호환 버전으로 업데이트 (Terraform 사용 시 apply로 자동 처리)
# most_recent = true 설정이면 terraform apply 시 자동 업데이트
```
