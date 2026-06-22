# K8s Upgrade Skills 개선 계획 — 프로덕션 적용 전

> **작성일**: 2026-06-20
> **근거**: 2026-06-19 ezl-dev / ezl-mgm 클러스터 4회 업그레이드 실측 기록 (`upgrade-archives/`)
> **목표**: 실제 프로덕션(실트래픽) 클러스터 적용 전, 4회 실행에서 드러난 구조적 마찰·오탐·미내재화 트러블을 스킬에 반영하고, dev/mgm에서 검증되지 못한 잠재 위험을 사전 차단한다.

---

## 1. 배경

2026-06-19 다음 4건을 모두 **최종 성공**시켰다.

| # | 클러스터 | 버전 | 소요 | 결과 |
|---|---------|------|------|------|
| 1 | ezl-dev | 1.33→1.34 | 28분 | ✅ Phase 7 1차 FAIL → 수동 복구 |
| 2 | ezl-dev | 1.34→1.35 | 19분 | ✅ Phase 0 1차 BLOCKED → 재실행 |
| 3 | ezl-mgm | 1.33→1.34 | 24분 | ✅ |
| 4 | ezl-mgm | 1.34→1.35 | 18분 | ✅ |

문제는 **게이트가 막은 것이 대부분 진짜 위험이 아니라 오탐·과도상태·미내재화 트러블**이었고, LLM이 그때그때 즉흥 대응(폴링, rollout restart, 재실행)으로 우회했다는 점이다. dev/mgm은 Karpenter 전용·무트래픽이라 우회가 허용됐지만, **프로덕션은 실트래픽·MNG 가능성·PDB 실차단** 환경이므로 같은 즉흥 대응이 다운타임으로 직결될 수 있다.

또한 **두 핵심 안전장치(drain-monitor, service-aware sub-agent)가 4회 모두 실전 가동되지 못했다.** 정작 프로덕션에서 가장 필요한 기능이 한 번도 검증되지 않은 상태다.

---

## 2. 한눈에 보기

| ID | 영역 | 문제 | 우선순위 | 영향 |
|----|------|------|:--------:|------|
| P0-1 | Sub-Agent | drain-monitor / service-aware 4회 모두 미가동 (권한 + 실행모델 불일치) | **P0** | prod 안전망 부재 |
| P0-2 | 게이트 오탐 | INF-001 terraform plan 4회 전부 오탐 FAIL | **P0** | 게이트 신뢰도 붕괴 |
| P0-3 | 반복 트러블 | Fargate kubelet 잔류 처리 절차 부재 (Phase 7 FAIL) | **P0** | 매번 수동 개입 |
| P1-1 | 반복 트러블 | terraform apply 409 시나리오 미내재화 | P1 | Phase 2 즉흥 대응 |
| P1-2 | 게이트 오탐 | Phase 0 연속 업그레이드 과도상태 BLOCKED | P1 | 불필요한 중단 |
| P1-3 | 게이트 동작 | Phase 3 Add-on UPDATING 자동 폴링 부재 | P1 | 수동 재실행 2~3회 |
| P1-4 | 인증/MFA | gate/terraform 인증 이원화 + 장시간 MFA 만료 | P1 | 폴링 실패·혼란 |
| P2-1 | 로그 품질 | audit.log 헤더 오염 (`Upgrade:  → X`) | P2 | 보고서 추출 혼란 |
| P2-2 | 잠재 위험 | MNG 롤링 경로 prod 미검증 | **P0(검증)** | 실전 첫 가동 위험 |
| P2-3 | 잠재 위험 | service-aware / 실트래픽 다운타임 미검증 | **P0(검증)** | 무중단 보장 불가 |
| P2-4 | 잠재 위험 | 단일 레플리카·PDB 실차단·CAP 사각지대 | P1 | 다운타임 위험 |

---

## 3. P0 — 프로덕션 적용 전 반드시 해결

### P0-1. Sub-Agent 실전 가동 구조 복구

**문제**
- `aws/terraform-eks/SKILL.md`는 Phase 2/4/5에서 `k8s-drain-monitor`를 `⛔ HARD GATE`로 강제한다 (SKILL.md:204-216, 315-343, 470-497).
- 실제로는 4회 모두 미가동:
  - 1회차(dev 1.33→1.34, 로그 1066~1163): sub-agent를 띄웠으나 그 에이전트의 `audit_event.py`(python3) 실행이 **별도 권한 프롬프트를 요구 → 거부 → 포기 → 메인 인라인 처리**.
  - 2~4회차: 아예 미투입 ("Sub-Agent 미투입, EndpointSlice 감시 없음").

**근본 원인 (2가지)**
1. **권한 분리**: sub-agent의 Bash(`python3 audit_event.py`)가 메인 세션의 사전 허용 목록을 상속하지 못해 매번 프롬프트가 뜬다.
2. **실행 모델 불일치 (더 근본적)**: `k8s-drain-monitor.md`의 감시 명령은 `kubectl get events -A --watch`(무한 블로킹)다 (k8s-drain-monitor.md:35-55). 그런데 Claude Code의 Agent는 **동기 호출 → 결과 반환** 모델이다. "메인이 terraform apply를 도는 동안 sub-agent가 실시간 감시"라는 시나리오 자체가 현재 Agent 실행 모델과 맞지 않는다. sub-agent를 띄우면 메인이 블로킹되거나, sub-agent가 즉시 종료된다.

**변경안 (택1 또는 혼합 — 검증 필요)**
- **(A) 인라인 백그라운드 폴링 방식으로 공식화** ⭐ 권장
  - sub-agent 패턴을 버리고, 메인 에이전트가 `run_in_background: true`로 감시 루프를 띄우는 방식을 SKILL.md의 정식 절차로 만든다. 1회차에서 실제로 작동한 방식이다 (로그 1163, 1174).
  - `audit_event.py` 호출 권한을 install 단계에서 `settings.json` allowlist에 추가하도록 `install.sh` 보강.
  - watch 대신 30~60초 간격 폴링 스크립트(`drain_watch.py` 신규)로 events/PDB/NodeClaim을 스냅샷 비교 → 변화만 audit 기록.
- **(B) sub-agent 모델 유지하되 "단발 스냅샷" 호출로 변경**
  - sub-agent가 무한 watch 대신 "현재 시점 Warning/PDB 스냅샷 1회 수집 후 반환"하도록 재정의. 메인이 폴링 주기마다 호출.
- 어느 쪽이든 **drain 이벤트가 실제로 audit.log에 남는지**를 prod 적용 전 dev에서 1회 실증해야 한다.

**검증**: dev 클러스터에서 일부러 PDB=0 워크로드를 만들고 Karpenter drift를 유발 → `DRAIN-P5` 이벤트가 audit.log에 기록되는지 확인.

---

### P0-2. INF-001 terraform plan 오탐 제거

**문제**: `gate_check.py`의 `run_terraform_plan`(gate_check.py:871-882)이 4회 전부 오탐 FAIL.

**근본 원인 (3가지)**
1. **`-var-file` 누락**: `terraform plan -detailed-exitcode -no-color`만 실행 (gate_check.py:875). 실제 운영은 workspace별 `--var-file="$(terraform workspace show).tfvars"`가 필수 (recipe context, 로그 57-64). 변수 누락으로 plan 오류 → exit 1.
2. **인증 불일치**: gate_check은 `AWS_PROFILE=ezl-dev`로 실행됐으나 terraform backend는 `aws-runas ezl-switch`(assume role + MFA)가 필요 → backend init/plan 인증 실패 → exit 1.
3. **drift = 무조건 FAIL 설계**: `check_inf001`(gate_check.py:888-902)은 exit 2(정상적 변경 감지)도 FAIL 처리. prod는 상시 미세 drift가 있으므로 구조적으로 항상 FAIL.

**변경안**
- INF-001을 **선택적/정보성**으로 격하하거나, terraform 실행 컨텍스트(profile, var-file, init 여부)를 recipe에서 받아 정확히 재현.
- `run_terraform_plan`에 `--var-file`, 인증 wrapper(`auth_prefix`)를 파라미터로 주입.
- drift 감지는 "destroy/recreate 포함 시에만 WARN", "비파괴 변경은 INFO"로 세분화. 단순 drift 존재를 HIGH FAIL로 올리지 않는다.
- 동일 문제가 **Phase 6**(`gate_phase6`, phase_gate.py:597-693)에도 있음 — `terraform plan -out`을 var-file·인증 없이 실행. dev 1.33→1.34에서 PHASE6-TFSYNC FAIL 발생 (audit-dev-1.33.log:71). 같이 수정.

**검증**: dev에서 INF-001/Phase6가 실제 운영 인증·var-file로 PASS(또는 의미 있는 WARN)를 내는지 확인.

---

### P0-3. Fargate kubelet 잔류 처리 내재화

**문제**
- CP 업그레이드 후 Fargate 노드는 Pod 재시작 전까지 구버전 kubelet 유지. `karpenter`/`coredns` deployment가 Fargate 프로파일에 떠 있어 `rollout restart` 필요.
- `gate_phase4`(phase_gate.py:416-441)는 모든 노드를 `version_pattern.match`로 검사 → Fargate 구버전이면 무조건 FAIL. **해결법 안내는 스크립트·SKILL.md 어디에도 없음.**
- 결과: dev 1.33→1.34 Phase 7이 Fargate v1.33.11 잔류로 FAIL (audit-dev-1.33.log:111, 125-127) → 수동 `kubectl rollout restart` 후 2차 PASS. 이후 회차는 LLM이 "학습 컨텍스트"로 들고 다니며 선제 재시작 (로그 2139, report-dev-1.34:79-81).

**변경안**
- SKILL.md Phase 3 직후(또는 Phase 7 직전)에 **"Fargate 프로파일 워크로드 rollout restart" 정식 단계** 추가:
  - Fargate 프로파일 자동 탐색 (`aws eks list-fargate-profiles` → 해당 namespace/deployment)
  - CP보다 낮은 kubelet 버전 Fargate 노드가 있으면 해당 deployment `rollout restart` 안내.
- `gate_phase4`/`gate_phase7`가 Fargate 노드 잔류를 FAIL로 잡을 때, **메시지에 구체적 조치 명령**(어느 deployment를 restart할지)을 포함.
- reference.md에 Fargate 처리 패턴을 영구 기록(현재는 보고서의 "누적 학습"으로만 존재).

**검증**: dev에서 Phase 7 직전 단계가 Fargate 노드를 자동 감지하고 restart 명령을 제시하는지 확인.

---

### P0-검증. 프로덕션 미검증 경로 사전 실증 (P2-2, P2-3)

dev/mgm에서 **한 번도 실행되지 않은 경로**가 prod에서 첫 가동되는 위험:

- **MNG 롤링 (Phase 4-A/B 전체)**: dev/mgm은 Karpenter 전용으로 CAP-003·Phase4가 "MNG 없음/SKIP" (audit 전부 "MNG 없음"). prod에 MNG가 있으면 AMI alias 업데이트 → MNG 롤링 → drain monitor 경로가 **실전 처음** 돈다. SKILL.md Phase 4-A(SKILL.md:309-464)는 코드 리뷰만 됐을 뿐 실측 0회.
- **service-aware sub-agent**: recipe에 `services` 필드가 없어 4회 모두 미실행. prod 실트래픽에선 EndpointSlice 감시가 무중단의 핵심인데 **검증 0회**.

**조치**
- prod 적용 전, recipe에 `services` 필드를 채우고 dev에서 service-aware 경로를 1회 드라이런.
- prod에 MNG가 있는지 먼저 확인. 있으면 별도 MNG 롤링 리허설 계획 수립.

---

## 4. P1 — 적용 전 권장 (안정성·신뢰도)

### P1-1. terraform apply 409 ResourceInUseException 내재화
- **문제**: Phase 2 apply가 UpdateClusterVersion 전송 직후 EKS가 선행 업데이트 시작 → 재시도 시 409 (로그 1288, report-dev-1.33:46). SKILL.md에 시나리오·대응 절차 없음. LLM이 매번 즉흥 폴링.
- **변경안**: SKILL.md Phase 2에 "409 = 정상 진행 신호" 분기 추가 — apply가 409로 죽으면 폴링으로 ACTIVE+target_version 확인 후 state sync. (현재는 컨텍스트 조정사항으로만 회차 간 전파됨, 로그 2137.)

### P1-2. Phase 0 연속 업그레이드 과도상태 처리
- **문제**: dev 1.34→1.35에서 직전 1.34 완료 직후 바로 1.35 시작 → Karpenter 노드 재배치 중 NotReady/PDB=0 일시 발생 → `COM-001`/`WLS-001` CRITICAL → BLOCKED (로그 2189, 2220-2248). 수분 후 자연 해소, 재실행 통과.
- **변경안**: gate_check 또는 SKILL.md에 **"직전 업그레이드 후 안정화 대기"** 가이드. COM-001/WLS-001 CRITICAL 시 "과도상태 가능성 — N분 후 1회 재시도" 힌트 제공(자동 우회 아님, 안내만).

### P1-3. Phase 3 Add-on UPDATING 자동 폴링
- **문제**: `gate_phase3`(phase_gate.py:144-159)는 Add-on UPDATING이면 즉시 WARN("완료 후 재실행하세요"). 자동 대기 없음 → vpc-cni→coredns→kube-proxy 순차 업데이트마다 수동 재실행 2~3회 (audit-mgm-1.34.log:46-59, report-mgm-1.34:23).
- **변경안**: SKILL.md Phase 3에 "UPDATING이면 30초 간격 N회 자동 폴링 후 게이트 재실행" 절차 명시. 게이트 자체는 단발 판정 유지(결정성 보존), 폴링은 SKILL.md 절차로.

### P1-4. 인증/MFA 구조 정리
- **문제**: gate/kubectl(`AWS_PROFILE`) vs terraform(`aws-runas` 대화형 MFA) 이원화 (로그 341-460). 장시간 폴링 중 MFA 세션(1h) 만료 (report-dev-1.34:50, 88).
- **변경안**:
  - recipe schema에 인증 컨텍스트 필드 추가(`auth_prefix`, `tf_var_file`, `kube_profile`) → LLM 즉석 탐색 제거.
  - SKILL.md에 "업그레이드 시작 전 MFA 세션 캐시 갱신" 사전 단계 + "장시간 작업 중 세션 만료 시 재인증" 안내.

---

## 5. P2 — 품질 개선

### P2-1. audit.log 헤더 오염
- **문제**: `gate_phase2/3/4/5/7`이 `audit_init(cluster, "", version)`로 current_version을 비워 넘김(phase_gate.py:73, 110, 381, 530, 724) → `Upgrade:  → 1.34`, sub-gate는 `Cluster: `까지 빈 채로 반복 기록 (audit-dev-1.33.log:33,44,56,67,94).
- **변경안**: phase 게이트에도 current_version을 전달하거나, 헤더에서 빈 값일 때 `(unknown)` 또는 생략 처리. 보고서 자동 생성(SKILL.md:579 타임스탬프 추출)의 안정성 확보.

### P2-4. 단일 레플리카 · PDB · CAP 사각지대 (prod 가중)
- 단일 레플리카: dev 21개 / mgm 12개 (WLS-002 HIGH). prod도 유사하면 실트래픽 다운타임 → prod recipe에 핵심 서비스 `replicas>=2` 선반영 권고를 계획에 명시.
- PDB 실차단: dev/mgm은 PDB가 실제로 안 막았으나 prod는 막을 수 있음 → FailedEvict 시 무한 대기 대비 (drain monitor 가동이 전제).
- CAP-001 requests 사각지대: requests 미설정 컨테이너 42~46개로 사용률 과소추정 (gate_check.py:711-715). prod에서 실제 노드 포화 시 drain Pending 위험.

---

## 6. 실행 로드맵

```
[마일스톤 A] 게이트 신뢰도 — prod 적용 차단 해제용
  P0-2 INF-001/Phase6 오탐 제거
  P2-1 audit 헤더 정리 (작은 변경, 같이)
  → dev에서 Phase 0 재실행하여 오탐 0건 확인

[마일스톤 B] 반복 트러블 내재화
  P0-3 Fargate rollout restart 정식 단계
  P1-1 409 대응 분기
  P1-3 Phase 3 UPDATING 폴링
  → SKILL.md 절차 보강 + reference.md 영구 기록

[마일스톤 C] Sub-Agent 실전화 (가장 무거움)
  P0-1 drain-monitor 실행 모델 재설계 (인라인 백그라운드 폴링)
  install.sh allowlist 보강
  → dev에서 drain 이벤트 audit 기록 실증

[마일스톤 D] 프로덕션 리허설
  P0-검증 service-aware dev 드라이런
  P1-4 인증/MFA 사전 단계
  prod MNG 유무 확인 → 있으면 MNG 롤링 리허설
  P2-4 prod recipe 사전 점검 (replicas, PDB)
```

---

## 7. 결정 사항 (2026-06-20 합의)

1. **Sub-Agent 방향** → **(A) 인라인 백그라운드 폴링으로 확정.** 근거: ① 4회 중 유일하게 실증된 방식(로그 1163~1217), ② Claude Code Agent는 단방향 호출-반환 모델이라 "감시 중 즉시 STOP 신호"가 구조적으로 불가, ③ 드레인 감시의 본질은 스트림이 아닌 주기적 스냅샷, ④ 메인 세션 권한 일관성, ⑤ 컨텍스트 비용 절감. 구현 시 `drain_watch.py` 전용 스크립트로 스냅샷 비교+audit 기록을 결정적으로 수행하고, 메인이 `run_in_background`로 띄운다.
2. **INF-001 처리 강도** → **정보성(INFO)으로 격하 확정.** 게이트 PASS/WARN/FAIL 판정에서 분리하고 drift는 참고 정보로만 제공. Phase 6도 동일 방침.
3. **recipe schema 확장** → **`auth_prefix`, `tf_var_file`, `services` 3개 전부 추가 확정.** LLM 즉석 탐색 제거 + service-aware 활성화.
4. **검증 환경** → **별도 테스트 클러스터를 새로 만들어 진행 (다음 차수).** 사용자가 직접 클러스터를 구성해 마일스톤 실증을 수행.

---

## 부록: 근거 파일 인덱스

| 트러블 | 1차 근거 |
|--------|---------|
| Sub-agent 권한 거부 | `2026_06_19_로그.md` 1066-1163 |
| terraform 409 | 로그 1288-1296 |
| Fargate 잔류 FAIL | `audit-ezl-dev-1.33-to-1.34.log` 111, 125-127 / 로그 1865-1904 |
| Phase 0 과도상태 BLOCKED | 로그 2189-2248 |
| MFA 만료 | 로그 341-460 / `report-ezl-dev-1.34-to-1.35` 50, 88 |
| Add-on 순차 UPDATING | `audit-ezl-mgm-1.34-to-1.35.log` 46-59 |
| INF-001 오탐 | 4개 audit 로그 전부 `INF-001 | FAIL` |
| MNG 미검증 | 4개 audit 로그 전부 `CAP-003 | PASS | MNG 없음` |
</content>
</invoke>
