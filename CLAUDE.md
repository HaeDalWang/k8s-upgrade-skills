# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# 테스트 전체 실행
python3 -m pytest tests/

# 단일 테스트 클래스 실행
python3 -m pytest tests/test_gate_check.py::TestCom002MalformedVersion -v

# 단일 테스트 함수 실행
python3 -m pytest tests/test_phase_gate.py::TestClassifyPods::test_running_not_ready_blocking -v

# 스크립트 직접 실행 (개발 중 검증)
python3 k8s-upgrade-skills/scripts/gate_check.py \
  --cluster-name my-cluster \
  --current-version 1.33 \
  --target-version 1.34 \
  --tf-dir /path/to/terraform \
  --audit-log audit.log

python3 k8s-upgrade-skills/scripts/phase_gate.py phase4 \
  --cluster-name my-cluster \
  --target-version 1.34 \
  --audit-log audit.log

# 스킬 설치
./install.sh --tool claude
./install.sh --status
```

## 아키텍처

### 핵심 설계 원칙

**LLM bypass 불가 Gate**: 모든 Phase 경계는 Python 스크립트의 exit code로만 판단한다. LLM은 exit code를 재해석하거나 우회할 수 없다.

- `exit 0` = PASS (진행)
- `exit 1` = FAIL (즉시 중단)
- `exit 2` = WARN (사용자 확인 필요)
- `exit 127` = CLI 도구 미존재

**audit.log 신뢰 모델**: 스크립트만 쓰고, LLM은 읽기만 한다. append 모드로 기록되어 각 Phase 기록이 누적된다.

### 파일 구조

```
k8s-upgrade-skills/          ← AI Agent가 읽는 스킬 디렉토리 (install.sh로 전역 설치됨)
├── SKILL.md                 ← 루트 라우터: recipe 검증 + (environment, platform, iac) 기반 Sub-Skill 분기
├── scripts/
│   ├── lib.py               ← 공통 헬퍼: GateResult, audit_flush, kubectl_json, record, _parse_cpu/_parse_mem
│   ├── gate_check.py        ← Phase 0: 17개 사전 검증 규칙 (COM/WLS/CAP/INF)
│   ├── phase_gate.py        ← Phase 2~7: 각 Phase Gate 함수 (phase2~phase7 서브커맨드)
│   └── validate_recipe.py   ← recipe.yaml 스키마 검증
└── aws/terraform-eks/
    ├── SKILL.md             ← Phase 0~7 실행 절차 (EKS + Terraform 전용)
    └── reference.md         ← 완료 보고서 템플릿, 중단 조건 목록

tests/
├── test_gate_check.py       ← gate_check.py 단위 테스트
└── test_phase_gate.py       ← phase_gate.py 단위 테스트

docs/
├── required-permissions.md  ← IAM/RBAC 최소 권한 (Phase별 분리)
└── failure-runbook.md       ← 실패 시나리오별 대응 절차
```

### 스크립트 간 의존 관계

```
gate_check.py  ──imports──▶  lib.py
phase_gate.py  ──imports──▶  lib.py
```

`lib.py`의 핵심 함수:
- `kubectl_json(resource, all_ns, timeout)` → `Optional[dict]`: 실패 시 `None` 반환 (빈 dict `{}`와 구분)
- `audit_flush(path)`: `_gate.audit_lines`를 append 모드로 파일에 기록
- `record(rule_id, severity, status, message)`: 글로벌 `_gate` 상태에 결과 누적
- `reset_gate()`: 테스트 간 글로벌 상태 초기화 (테스트 fixture에서 `autouse=True`)

### Pod 분류 로직 (classify_pods)

`phase_gate.py`의 `classify_pods()`는 비정상 Pod를 세 가지로 분류한다:
- **TRANSIENT**: 생성 후 3분 미만 — 대기
- **BLOCKING**: 생성 후 5분 초과 — 즉시 중단
- **STALE**: Succeeded/Unknown/Failed — LLM이 삭제 후 재실행

Running 상태여도 `containerStatuses[].ready == false`인 경우 동일한 시간 기준으로 분류한다.

### 테스트 패턴

- `kubectl_json` 실패 케이스는 `None` 반환으로 mock → 호출 함수가 `if data is None:` 체크 후 FAIL 기록하는지 검증
- multi-phase 순차 테스트: `audit_flush`를 여러 번 호출한 뒤 파일 내용에 모든 Phase 기록이 누적되는지 확인
- `reset_gate()` fixture는 `autouse=True`로 모든 테스트에 자동 적용

### Python 버전 제약

Python 3.9+ 지원. `dict | None` 타입 힌트 사용 불가 → `Optional[dict]` 사용 (`from typing import Optional`).
