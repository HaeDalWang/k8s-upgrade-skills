# Terraform EKS Upgrade — Reference

---

## Plan Template (계획서)

Generate this document after recipe validation, before Phase 0. Save as `upgrade-plan-{CLUSTER_NAME}-{YYYYMMDD}.md`.

Fill every `{PLACEHOLDER}` from recipe.yaml. Do NOT invent data.

### Korean Template (output_language: ko)

```markdown
# EKS 업그레이드 계획서

> 이 문서를 검토하고 하단의 승인 문구를 입력하면 업그레이드가 시작됩니다.

## 업그레이드 개요

| 항목 | 값 |
|------|-----|
| 클러스터 | {CLUSTER_NAME} |
| 버전 | {CURRENT_VERSION} → {TARGET_VERSION} |
| 환경 | {ENVIRONMENT} / {PLATFORM} / {IaC} |
| 특이사항 | {NOTES 또는 "없음"} |
| 계획서 생성 | {PLAN_GENERATED_AT} |

---

## Phase별 실행 계획

| Phase | 작업 내용 | Gate 조건 | 비고 |
|-------|---------|---------|------|
| Phase 0 | 사전 검증 (17개 규칙) | gate_check.py exit 0 | CRITICAL FAIL 시 즉시 중단 |
| Phase 1 | terraform.tfvars 버전/AMI 업데이트 | 변경값 grep 확인 | LLM이 직접 검증 |
| Phase 2 | Control Plane 업그레이드 | CP status=ACTIVE + 목표 버전 | 비가역적 작업. 소요 시간 편차 큼 (참고값: 8~40분) |
| Phase 3 | Add-on 안정화 검증 | 전체 Add-on ACTIVE | CP 업그레이드 후 자동 재조정 대기 |
| Phase 4 | Data Plane 롤링 업데이트 | 전체 노드 Ready + 목표 버전 | MNG 자동 롤링. Sub-Agent 드레인 감시 병행 |
| Phase 5 | Karpenter 노드 교체 | 전체 NodeClaim 목표 버전 | Karpenter 미사용 시 SKIP |
| Phase 6 | Terraform 전체 동기화 | plan에 예상 외 변경 없음 | 잔여 drift 정리 |
| Phase 7 | 최종 검증 및 보고서 | unhealthy Pod 0개 + Insights PASSING | 완료 보고서 자동 생성 |

---

## 서비스 가용성 모니터링

{SERVICES_TABLE_OR_SKIP_MESSAGE}

<!-- 예시 (services 필드 있을 때):
| 서비스 | 네임스페이스 | 최소 엔드포인트 | 헬스체크 URL | 감시 방식 |
|--------|-----------|--------------|------------|---------|
| my-api | production | 2 | https://api.example.com/health | EndpointSlice + HTTP |
| my-worker | production | 1 | 미설정 | EndpointSlice only (BestEffort) |

services 필드 없을 때:
"서비스 가용성 모니터링 미설정 — Sub-Agent 미투입. EndpointSlice 감시 없음."
-->

---

## 검토 체크리스트

아래 항목을 확인 후 승인하세요.

- [ ] 업그레이드 윈도우가 적절한가 (트래픽 저점 시간대 권장)
- [ ] 현재 진행 중인 배포 또는 작업이 없는가
- [ ] 관련 팀(인프라/개발/운영)에 공지 완료했는가
- [ ] Phase 0 사전 검증 결과를 확인할 준비가 됐는가
- [ ] 업그레이드 중 즉시 대응 가능한 담당자가 대기 중인가

---

## 추가 특이사항

> 이 섹션은 사람이 직접 작성합니다. 없으면 "없음"으로 기재하세요.

{NOTES_FROM_RECIPE_OR_BLANK}

---

## 승인 안내

모든 항목을 검토했다면 아래 정확한 문구를 입력하세요:

**업그레이드 계획서 승인**

> ⚠️ 위 문구 외 다른 입력("진행해줘", "ok", "응" 등)은 승인으로 처리되지 않습니다.
```

### English Template (output_language: en)

```markdown
# EKS Upgrade Plan

> Review this document and type the approval phrase at the bottom to start the upgrade.

## Upgrade Overview

| Field | Value |
|-------|-------|
| Cluster | {CLUSTER_NAME} |
| Version | {CURRENT_VERSION} → {TARGET_VERSION} |
| Environment | {ENVIRONMENT} / {PLATFORM} / {IaC} |
| Notes | {NOTES or "None"} |
| Plan Generated | {PLAN_GENERATED_AT} |

---

## Phase Execution Plan

| Phase | Action | Gate Condition | Notes |
|-------|--------|---------------|-------|
| Phase 0 | Pre-flight validation (17 rules) | gate_check.py exit 0 | CRITICAL FAIL → immediate stop |
| Phase 1 | Update terraform.tfvars version/AMI | grep verification | LLM-verified |
| Phase 2 | Control Plane upgrade | CP status=ACTIVE + target version | Irreversible. Duration varies (ref: 8–40 min) |
| Phase 3 | Add-on stabilization | All add-ons ACTIVE | Wait for reconciliation after CP upgrade |
| Phase 4 | Data Plane rolling update | All nodes Ready + target version | MNG auto-rolling. Sub-Agent drain monitor active |
| Phase 5 | Karpenter node replacement | All NodeClaims at target version | SKIP if Karpenter not used |
| Phase 6 | Full Terraform sync | No unexpected changes in plan | Clean up remaining drift |
| Phase 7 | Final validation + report | 0 unhealthy pods + Insights PASSING | Completion report auto-generated |

---

## Service Availability Monitoring

{SERVICES_TABLE_OR_SKIP_MESSAGE}

---

## Review Checklist

- [ ] Upgrade window is appropriate (low-traffic period recommended)
- [ ] No deployments or operations currently in progress
- [ ] Relevant teams (infra/dev/ops) have been notified
- [ ] Ready to review Phase 0 pre-flight results
- [ ] On-call engineer available during upgrade

---

## Additional Notes

> This section is filled in by a human. Write "None" if not applicable.

{NOTES_FROM_RECIPE_OR_BLANK}

---

## Approval

After reviewing all items, type the following exact phrase:

**upgrade plan approved**

> ⚠️ Any other input ("proceed", "ok", "yes", etc.) will NOT be treated as approval.
```

---

## Report Templates (보고서)

Save the report as `upgrade-report-{CLUSTER_NAME}-{YYYYMMDD}.md`.

Determine the report type from the upgrade outcome, then fill every `{PLACEHOLDER}` from audit.log and recipe.yaml.

**How to extract data from audit.log:**
- Phase start time: line matching `# Started:` after `# --- Phase N` or `audit_init` block
- Phase end time: line matching `# Finished:`
- Phase duration: Finished timestamp − Started timestamp
- Events: all lines matching `{timestamp} | {rule_id} | WARN|FAIL | {detail}`
- Sub-Agent events: lines with rule-id `DRAIN-P*` or `SVC-P*`
- Gate result: line matching `# Gate: BLOCKED|WARN|OPEN`

---

### Type A: Phase 0 FAIL — 사전 검증 실패 보고서

Use when: gate_check.py exits with code 1 or 2 and upgrade did not start.

#### Korean

```markdown
# EKS 업그레이드 사전 검증 실패 보고서

## 결과 요약

| 항목 | 값 |
|------|-----|
| 결과 | ❌ 사전 검증 실패 — 업그레이드 미시작 |
| 클러스터 | {CLUSTER_NAME} |
| 버전 (시도) | {CURRENT_VERSION} → {TARGET_VERSION} |
| 검증 시각 | {PHASE0_START_TIME} |
| Gate 판정 | {BLOCKED 또는 WARN} |

---

## Phase 0 검증 결과

| 규칙 ID | 심각도 | 결과 | 상세 |
|---------|--------|------|------|
{PHASE0_RULES_TABLE}

<!-- audit.log의 모든 FAIL/WARN 항목을 행으로 채우세요 -->

---

## 조치 필요 항목

{CRITICAL_AND_HIGH_ITEMS_LIST}

<!-- CRITICAL: 즉시 해결 필요 / HIGH: 사용자 확인 후 진행 가능 -->

---

## 다음 단계

1. 위 조치 필요 항목을 해결하세요
2. 해결 후 `python3 scripts/gate_check.py ...`를 재실행하여 검증하세요
3. 검증 통과 후 업그레이드를 재시작하세요

자세한 대응 절차: [docs/failure-runbook.md](../../docs/failure-runbook.md)
```

---

### Type B: Phase 1–6 FAIL — 업그레이드 중단 보고서

Use when: upgrade started but stopped at Phase 1–6 due to FAIL.

#### Korean

```markdown
# EKS 업그레이드 중단 보고서

## 결과 요약

| 항목 | 값 |
|------|-----|
| 결과 | ❌ Phase {FAILED_PHASE}에서 중단 |
| 클러스터 | {CLUSTER_NAME} |
| 버전 | {CURRENT_VERSION} → {TARGET_VERSION} (미완료) |
| 시작 | {UPGRADE_START_TIME} |
| 중단 | {UPGRADE_STOP_TIME} |
| 총 경과 | {ELAPSED_TIME} |

> ⚠️ **현재 클러스터 상태**: {MIXED_VERSION_WARNING_OR_CLEAN}
> Phase 2 이후 중단 시 Control Plane과 Data Plane 버전이 다를 수 있습니다.

---

## Phase별 결과

| Phase | 결과 | 소요 시간 | 비고 |
|-------|------|---------|------|
| Phase 0 | {RESULT} | {DURATION} | |
| Phase 1 | {RESULT} | {DURATION} | |
| Phase 2 | {RESULT} | {DURATION} | |
| Phase 3 | {RESULT} | {DURATION} | |
| Phase 4 | {RESULT} | {DURATION} | |
| Phase 5 | {RESULT} | {DURATION} | |
| Phase 6 | {RESULT} | {DURATION} | |

<!-- 미실행 Phase는 "미실행"으로 표기 -->

---

## 중단 원인

**Phase {FAILED_PHASE} 실패 상세:**

{FAILURE_DETAIL_FROM_AUDIT_LOG}

---

## 이벤트 타임라인

| 시각 | 규칙/모니터 | 결과 | 상세 |
|------|-----------|------|------|
{WARN_FAIL_EVENTS_TABLE}

<!-- audit.log에서 WARN/FAIL 항목 전체 추출. Sub-Agent 이벤트(DRAIN-P*, SVC-P*) 포함 -->

---

## 트러블슈팅 내역

{TROUBLESHOOTING_LOG}

<!-- 업그레이드 중 발생한 문제와 취한 조치를 시간순으로 기술 -->

---

## 현재 클러스터 상태

| 항목 | 상태 |
|------|------|
| Control Plane 버전 | {CP_VERSION} |
| Data Plane 버전 | {DP_VERSION_OR_MIXED} |
| 비정상 Pod | {UNHEALTHY_POD_COUNT}개 |

---

## 다음 단계

{NEXT_STEPS_BASED_ON_FAILED_PHASE}

<!-- Phase 2 이후 중단 시: "Control Plane은 이미 업그레이드됨. Data Plane을 수동으로 완료해야 합니다." -->

자세한 대응 절차: [docs/failure-runbook.md](../../docs/failure-runbook.md)
```

---

### Type C: Phase 7 PASS — 업그레이드 완료 보고서

Use when: Phase 7 gate exits with code 0.

#### Korean

```markdown
# EKS 업그레이드 완료 보고서

## 결과 요약

| 항목 | 값 |
|------|-----|
| 결과 | ✅ 업그레이드 성공 |
| 클러스터 | {CLUSTER_NAME} |
| 버전 | {CURRENT_VERSION} → {TARGET_VERSION} |
| 시작 | {UPGRADE_START_TIME} |
| 완료 | {UPGRADE_END_TIME} |
| 총 소요 | {TOTAL_DURATION} |

---

## Phase별 결과

| Phase | 결과 | 소요 시간 | 비고 |
|-------|------|---------|------|
| Phase 0 | ✅ PASS | {DURATION} | {CRITICAL_FAIL}개 CRITICAL, {HIGH_WARN}개 HIGH |
| Phase 1 | ✅ PASS | {DURATION} | tfvars 업데이트 완료 |
| Phase 2 | ✅ PASS | {DURATION} | CP {TARGET_VERSION} ACTIVE |
| Phase 3 | ✅ PASS | {DURATION} | 전체 Add-on ACTIVE |
| Phase 4 | ✅ PASS | {DURATION} | 전체 노드 Ready |
| Phase 5 | {PASS 또는 SKIP} | {DURATION 또는 "-"} | {Karpenter 교체 완료 또는 미사용} |
| Phase 6 | ✅ PASS | {DURATION} | {변경사항 N개 또는 No changes} |
| Phase 7 | ✅ PASS | {DURATION} | 최종 검증 완료 |

---

## 이벤트 타임라인

{EVENTS_TABLE_OR_"이벤트 없음 — 업그레이드가 무난하게 완료됐습니다."}

<!-- audit.log에서 WARN/FAIL 항목 추출. 없으면 위 메시지 사용 -->

| 시각 | 규칙/모니터 | 결과 | 상세 |
|------|-----------|------|------|
{WARN_FAIL_EVENTS_TABLE}

---

## 트러블슈팅 내역

{TROUBLESHOOTING_LOG_OR_"트러블슈팅 없음"}

---

## 최종 클러스터 상태

| 항목 | 상태 |
|------|------|
| Control Plane | {TARGET_VERSION} ACTIVE |
| Managed Node Group | v{TARGET_VERSION}.x |
| Karpenter 노드 | {v{TARGET_VERSION}.x 또는 미사용} |
| 전체 Pod | Running/Completed |
| EKS Insights | 전체 PASSING |

## terraform.tfvars 변경 내용

```
eks_cluster_version             = "{TARGET_VERSION}"
eks_node_ami_alias_al2023       = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
eks_node_ami_alias_bottlerocket = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
```
```

---

### Type D: Phase 7 WARN — 경고 포함 완료 보고서

Use when: Phase 7 gate exits with code 2 AND user explicitly approved continuation.

#### Korean

```markdown
# EKS 업그레이드 완료 보고서 (경고 포함)

## 결과 요약

| 항목 | 값 |
|------|-----|
| 결과 | ⚠️ 경고 포함 완료 — 사용자 승인 후 완료 처리 |
| 클러스터 | {CLUSTER_NAME} |
| 버전 | {CURRENT_VERSION} → {TARGET_VERSION} |
| 시작 | {UPGRADE_START_TIME} |
| 완료 | {UPGRADE_END_TIME} |
| 총 소요 | {TOTAL_DURATION} |

> ⚠️ 이 보고서는 경고 상태에서 사용자가 명시적으로 승인하여 완료 처리된 업그레이드입니다.
> 아래 경고 항목을 반드시 후속 조치하세요.

---

## Phase별 결과

<!-- Type C와 동일한 구조, WARN이 발생한 Phase에 ⚠️ 표시 -->

{PHASE_RESULTS_TABLE}

---

## 경고 항목 (후속 조치 필요)

{WARN_ITEMS_LIST}

<!-- 업그레이드 완료 후 반드시 해결해야 할 항목 목록 -->

---

## 이벤트 타임라인

| 시각 | 규칙/모니터 | 결과 | 상세 |
|------|-----------|------|------|
{WARN_FAIL_EVENTS_TABLE}

---

## 트러블슈팅 내역

{TROUBLESHOOTING_LOG}

---

## 최종 클러스터 상태

{FINAL_CLUSTER_STATE_TABLE}

---

## 후속 조치 항목

{POST_UPGRADE_ACTION_ITEMS}
```

---

## Abort Conditions

If ANY of the following conditions is met, **STOP immediately** and report to the user:

### Phase 0 (Pre-flight) — gate_check.py 검증

`gate_check.py`가 exit code로 Gate를 판단한다. FAIL 시 출력 메시지에 조치 방안 힌트가 포함된다.

| Rule ID | Condition | Severity |
|---|---|---|
| COM-001 | EKS Insights `ERROR` / 노드 NotReady / 리소스 압박 | CRITICAL |
| COM-002 | 버전 건너뛰기 / kubelet skew > 2 | CRITICAL |
| COM-003 | Add-on DEGRADED / CREATE_FAILED | HIGH |
| WLS-001 | PDB `disruptionsAllowed == 0` — drain 차단 | CRITICAL |
| WLS-002 | 단일 레플리카 + PDB(minAvailable=1) — drain 불가 | HIGH |
| WLS-003 | PV AZ에 노드 1개만 — drain 시 재스케줄 불가 | CRITICAL |
| WLS-006 | Required affinity + 매칭 노드 부족 | HIGH |
| CAP-001 | 전체 노드 CPU/MEM > 90% — Pod Pending 확정 | HIGH |
| INF-001 | Terraform plan에 예상 외 destroy 포함 | HIGH |
| INF-002 | SSM AMI 조회 결과 비어있음 | CRITICAL |

### Phase 2~7 (실행 중) — phase_gate.py 검증

`phase_gate.py`가 exit code로 Gate를 판단한다 (0=PASS, 1=FAIL, 2=WARN).

| Phase | Exit Code | Condition | Action |
|---|---|---|---|
| Phase 2 | 1 | CP status ≠ ACTIVE 또는 version ≠ TARGET | 즉시 중단, audit.log 보고 |
| Phase 3 | 1 | Add-on 비정상 또는 kube-system Pod 비정상 | 즉시 중단, audit.log 보고 |
| Phase 4 | 1 | 노드 버전 불일치, FailedEvict, 또는 BLOCKING Pod | 즉시 중단, audit.log 보고 |
| Phase 4 | 2 | STALE 또는 TRANSIENT Pod 존재 | STALE Pod 삭제 후 재실행 |
| Phase 5 | 1 | Karpenter 노드 버전 불일치 또는 NotReady | 즉시 중단, audit.log 보고 |
| Phase 6 | 1 | Terraform recreate 감지 또는 plan 실패 | 즉시 중단, 사용자에게 보고 |
| Phase 7 | 1 | 하위 검증 실패 또는 Insight 비정상 | 즉시 중단, 완료 보고서 발행 금지 |
| Phase 7 | 2 | STALE/TRANSIENT Pod 존재 | STALE Pod 삭제 후 재실행, 사용자 승인 시에만 완료 |

### On Abort

1. Report the exact error, affected resource, and phase where failure occurred.
2. Do NOT attempt automatic rollback — EKS control plane upgrades are irreversible.
3. Suggest the user investigate the root cause before retrying.
4. If the failure is in Data Plane (Phase 4+) and Control Plane is already upgraded, the cluster is in a mixed-version state. Guide the user to complete the Data Plane upgrade manually if needed.
5. Generate the appropriate failure report (Type A or Type B) immediately upon abort.
