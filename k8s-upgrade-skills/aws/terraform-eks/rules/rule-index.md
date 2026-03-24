# 규칙 색인 및 실행 순서 (Rule Index)

Phase 0에서 아래 순서대로 모든 규칙을 실행한다.
`applies_when`이 조건부인 규칙은 조건 충족 시에만 실행한다.

## 실행 순서

### 1단계: 공통 검증 (Common)

| 순서 | ID | 규칙 | 심각도 | 적용 조건 |
|------|-----|------|--------|-----------|
| 1 | COM-001 | [클러스터 기본 상태](common/cluster-health.md) | CRITICAL | 항상 |
| 2 | COM-002 | [버전 호환성](common/version-compatibility.md) | CRITICAL | 항상 |
| 3 | COM-003 | [Add-on 호환성](common/addon-readiness.md) | HIGH | 항상 |

### 2단계: 워크로드 안전성 (Workload Safety)

| 순서 | ID | 규칙 | 심각도 | 적용 조건 |
|------|-----|------|--------|-----------|
| 4 | WLS-001 | [PDB 차단 가능성](workload-safety/pdb-audit.md) | CRITICAL | 항상 |
| 5 | WLS-002 | [단일 레플리카 위험](workload-safety/single-replica-risk.md) | HIGH | 항상 |
| 6 | WLS-003 | [PV 존 어피니티](workload-safety/pv-zone-affinity.md) | CRITICAL | PV 사용 워크로드 존재 시 |
| 7 | WLS-004 | [로컬 스토리지 Pod](workload-safety/local-storage-pods.md) | MEDIUM | 항상 |
| 8 | WLS-005 | [장시간 Job/CronJob](workload-safety/long-running-jobs.md) | MEDIUM | 활성 Job 존재 시 |
| 9 | WLS-006 | [토폴로지 제약 위반](workload-safety/topology-constraints.md) | HIGH | TSC/Affinity 사용 워크로드 존재 시 |

### 3단계: 용량 검증 (Capacity)

| 순서 | ID | 규칙 | 심각도 | 적용 조건 |
|------|-----|------|--------|-----------|
| 10 | CAP-001 | [노드 용량 여유분](capacity/node-capacity-headroom.md) | HIGH | 항상 |
| 11 | CAP-002 | [리소스 압박 Pod](capacity/pod-resource-pressure.md) | MEDIUM | 항상 |
| 12 | CAP-003 | [Surge 용량](capacity/surge-capacity.md) | HIGH | MNG rolling update 시 |

### 4단계: 인프라 검증 (Infrastructure)

| 순서 | ID | 규칙 | 심각도 | 적용 조건 |
|------|-----|------|--------|-----------|
| 13 | INF-001 | [Terraform 상태 드리프트](infrastructure/terraform-state-drift.md) | HIGH | 항상 |
| 14 | INF-002 | [AMI 가용성](infrastructure/ami-availability.md) | CRITICAL | 항상 |
| 15 | INF-003 | [Karpenter 호환성](infrastructure/karpenter-compatibility.md) | HIGH | Karpenter 사용 시 |
| 16 | INF-004 | [Terraform Recreate 감지](infrastructure/terraform-recreate-detection.md) | CRITICAL | 항상 |

## 결과 보고 형식

모든 규칙 실행 후 아래 형식으로 요약 보고한다:

```
사전 검증 결과 — {CLUSTER_NAME} ({CURRENT_VERSION} → {TARGET_VERSION})

┌─────────┬──────────────────────────┬──────────┬──────────┐
│   ID    │          규칙            │  심각도  │   결과   │
├─────────┼──────────────────────────┼──────────┼──────────┤
│ COM-001 │ 클러스터 기본 상태       │ CRITICAL │ ✅ PASS  │
│ COM-002 │ 버전 호환성              │ CRITICAL │ ✅ PASS  │
│ COM-003 │ Add-on 호환성            │ HIGH     │ ✅ PASS  │
│ WLS-001 │ PDB 차단 가능성          │ CRITICAL │ ✅ PASS  │
│ WLS-002 │ 단일 레플리카 위험       │ HIGH     │ ⚠️ WARN  │
│ ...     │ ...                      │ ...      │ ...      │
└─────────┴──────────────────────────┴──────────┴──────────┘

CRITICAL 실패: 0개 | HIGH 경고: 1개 | MEDIUM 참고: 0개
→ 진행 가능 (HIGH 경고 항목 사용자 확인 필요)
```

## 판정 기준

| 조건 | 판정 |
|------|------|
| CRITICAL 실패 1개 이상 | ❌ 업그레이드 불가 — 해결 후 재실행 |
| HIGH 실패 1개 이상, CRITICAL 없음 | ⚠️ 사용자 확인 필요 — 승인 시 진행 |
| MEDIUM/LOW만 | ✅ 자동 진행 (보고만) |
| 전부 PASS | ✅ 즉시 진행 |
