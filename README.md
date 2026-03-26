# K8s Upgrade Skills

Kubernetes 버전 업그레이드를 안전하게 완료할 수 있도록 도와주는 **AI Agent용 Skills**.

AI Agent가 `recipe.md`에 정의된 클러스터 정보를 읽고, 사전 검증 → 업그레이드 실행 → 사후 검증까지 phase-gated 방식으로 자동 수행합니다.

---

> **Disclaimer**: 본 스킬은 Kubernetes 업그레이드 의사결정을 보조하는 AI Agent용 도구입니다. 사전 검증, 실행 계획 수립, 모니터링 등을 자동화하지만, 실제 인프라 변경에 대한 최종 책임은 실행자(사용자)에게 있습니다. 프로덕션 환경에서는 반드시 변경 내용을 검토한 후 진행하세요.

## 기능

- Kubernetes Control Plane / Data Plane 업그레이드 자동 수행 (마이너 버전 +1)
- 16개 사전 검증 규칙으로 업그레이드 전 위험 요소 자동 감지
  - PDB 차단, 단일 레플리카, PV AZ 고정, 로컬 스토리지, 장시간 Job, 토폴로지 제약
  - IaC 상태 드리프트, 노드 이미지 가용성, 오토스케일러 호환성, 리소스 Recreate 감지
- Phase-gated 실행: 각 단계 Gate 미통과 시 즉시 중단 및 사용자 보고
- IaC 변경 사전 검토 후 적용 (예상치 못한 리소스 삭제 시 즉시 중단)
- `recipe.md` 기반 플랫폼/IaC 자동 라우팅 — 환경에 맞는 Sub-Skill 자동 선택

## 해당 스킬에서 검증하지 않는 것 (아직 지원하지 않는 것)

> 각 항목에 대한 상세 설명과 대안은 [QnA.md](QnA.md)를 참고하세요.

- 마이너 버전 2단계 이상 건너뛰기 (예: 1.33 → 1.35 불가, 한 단계씩만)
- 워크로드 Spec에 대한 직접적인 수정 (PDB, replica 수, 노드 프로비저닝 등)
  - CRITICAL 사전 검증 실패 자동 해결 (PDB 수정, 노드 추가 등은 사용자가 직접 수행)
  - PV AZ 자동 재배치 (이미 바인딩된 PV의 AZ 이동은 사용자가 직접 수행)
- 현재 지원하지 않는 플랫폼/IaC 조합 (개발 현황 참조)
- 자동 롤백 (실패 시 사용자에게 보고 후 판단 대기)
- Data Plane의 업그레이드 전략 선택과 Self-managed Node Group 업그레이드 (Managed Node Group만 지원)
  - Data Plane 업그레이드는 IaC의 Rolling Update 메커니즘에 의존합니다 (Skill이 직접 노드를 drain하지 않음)
  - Karpenter Nodepool 등, 생성된 노드가 IaC로 선언되어 있는 경우는 제외
- Fargate 프로파일 업그레이드
- SubAgent를 활용한 업그레이드 프로세스 중 실시간 수정
- Zero-downtime 검증

## 로드맵: 지능형 관측성 및 게이트 강화 (Priority 1)

현재의 Phase-gated 방식을 고도화하여, 인프라 상태(Ready)뿐만 아니라 실제 서비스 가용성(Endpoint)을 기준으로 업그레이드 진행 여부를 결정하는 것을 최우선 목표로 합니다.

### 1. 애플리케이션 가용성 기반 검증 (Service-Aware Gate)
- **현상:** 노드가 `Ready` 상태여도 Ingress/Service/HTTPRoute 등 네트워크 객체의 엔드포인트 전파 지연으로 인해 일시적인 서비스 단절(5xx 에러)이 발생할 수 있음.
- **개선:** recipe.md에 정의된 핵심 서비스(Service, Ingress, HTTPRoute)를 추적하여, 신규 노드 배치 후 엔드포인트(EndpointSlice) 가용 IP가 타겟 수치에 도달하고 실제 헬스체크 응답이 정상인 경우에만 다음 노드로 진행.

### 2. 병렬 Sub-Agent 기반 실시간 드레인(Drain) 모니터링
- **현상:** Terraform 실행 중 특정 Pod가 PDB 위반이나 Graceful Termination 실패로 드레인 프로세스에서 무한 대기하며 타임아웃을 유발함.
- **개선:** IaC 실행과 동시에 Sub-Agent를 병렬 투입하여 `kubectl get events -w` 과 같은 명령어로 드레인 프로세스를 실시간 감시.
  - 드레인 지연/실패 원인(예: PDB 교착 상태, 로컬 스토리지 점유 등)을 즉각 감지하여 사용자에게 보고 및 인터랙티브 대응 가이드 제시.

### 3. 고도화된 폴백(Fallback) 메커니즘
- **현상** 업그레이드 실패 시 원인 파악을 위해 수동으로 로그를 수집해야 하는 번거로움 존재.
- **개선** 검증 게이트 미통과 시 즉시 중단 및 **실패 시점의 클러스터 상태 스냅샷(Events, Pod Status, IaC Plan 결과)**을 자동 저장하여 AI Agent가 즉각적인 근원 분석(RCA) 리포트 제공.

## 개발 현황

| Environment | Platform | IaC | 상태 |
|-------------|----------|-----|------|
| AWS | EKS | Terraform | ✅ v1 — Self 검증 완료 |
| On-Premises | Kubespray | Ansible-playbook | 📋 계획됨 |

## Quick Start

```bash
# 1. 스킬을 설치
git clone https://github.com/HaeDalWang/k8s-upgrade-skills.git
cd k8s-upgrade-skills
./install.sh

# 2. 쿠버네티스를 관리하는 프로젝트 디렉토리의 recipe.md 작성
# 3. AI Agent에게 요청: "클러스터를 업그레이드해줘"
```

### install.sh

`install.sh`는 `k8s-upgrade-skills/` 디렉토리를 각 도구의 전역 스킬 경로에 복사합니다. 도구의 설정 파일(mcp.json 등)은 수정하지 않으며, 기존 설정에 영향을 주지 않습니다.

```bash
./install.sh                  # 인터랙티브 — 도구 선택
./install.sh --tool claude    # 특정 도구만 설치
./install.sh --all            # 모든 도구에 설치
./install.sh --status         # 설치 상태 확인
./install.sh --uninstall      # 전체 제거
```

### 지원 도구

| 도구 | 전역 설치 경로 |
|------|---------------|
| Claude Code | `~/.claude/skills/k8s-upgrade-skills/` |
| Kiro | `~/.kiro/skills/k8s-upgrade-skills/` |
| Cursor | `~/.cursor/skills/k8s-upgrade-skills/` |
| Windsurf | `~/.windsurf/skills/k8s-upgrade-skills/` |
| Gemini CLI | `~/.gemini/skills/k8s-upgrade-skills/` |
| OpenCode | `~/.agents/skills/k8s-upgrade-skills/` |
| Antigravity | `~/.agent/skills/k8s-upgrade-skills/` |
| GitHub Copilot | `~/.github/skills/k8s-upgrade-skills/` |

### recipe.md 작성

Kubernetes를 관리하는 프로젝트 루트에 `recipe.md`를 만들고 클러스터 정보를 채웁니다:

```yaml
environment: aws          # aws | on-prem
platform: eks             # eks | kubespray
iac: terraform            # terraform | none
cluster_name: my-cluster  # 클러스터 식별자
current_version: "1.34"   # 현재 버전 (따옴표 필수)
target_version: "1.35"    # 목표 버전 (따옴표 필수) — 반드시 current_version의 차기 마이너 버전

# 선택 항목
output_language: ko       # ko | en
notes: ""                 # 특이사항
```

> target_version은 current_version 대비 마이너 버전 +1만 허용됩니다. (예: "1.34" → "1.35" ✅, "1.34" → "1.36" ❌)

### MCP 서버 (선택)
플랫폼 및 IaC 종류에 따라 MCP를 추가하면 더 정확한 검증이 가능합니다

| MCP 서버 | 용도 |
|----------|------|
| `awslabs.eks-mcp-server` | EKS Insights, K8s 리소스 조회 |
| `kubernetes-mcp-server` | kubectl 기반 노드/Pod 상태 조회 |

MCP 서버가 없어도 Agent는 AWS CLI / kubectl 등 일반적인 Command로 fallback합니다.

## 업그레이드 워크플로우

```mermaid
graph TD
    A[recipe.md 읽기 및 검증] --> B[Phase 0: 사전 검증 — 16개 규칙]
    B -- "Gate: CRITICAL 0개" --> C[Phase 1: IaC 변수 업데이트]
    B -- "CRITICAL 실패" --> STOP[즉시 중단 — 사용자 해결 후 재실행]
    C -- "Gate: 버전/AMI 값 반영 확인" --> D[Phase 2: Control Plane 업그레이드]
    D -- "Gate: CP status=ACTIVE, 목표 버전 도달" --> E[Phase 3: Add-on 검증]
    E -- "Gate: 모든 Add-on ACTIVE" --> F[Phase 4: Data Plane 업그레이드]
    F -- "Gate: 전체 노드 Ready, 목표 버전" --> G[Phase 5: 오토스케일러 노드 교체]
    G -- "Gate: Drift 교체 완료, 전 노드 Ready" --> H[Phase 6: IaC 전체 동기화]
    H -- "Gate: plan에 예상치 못한 변경 없음" --> I[Phase 7: 최종 검증 및 보고서]
    I -- "Gate: unhealthy Pod 0개" --> J[완료]

    style STOP fill:#f44,color:#fff
    style J fill:#4a4,color:#fff
```

## 사전 검증 규칙 (16개)
플랫폼 및 IaC에 상관 없이 아래 항목을 확인합니다

| 카테고리 | 규칙 수 | 핵심 검증 내용 |
|----------|---------|---------------|
| common | 3개 | 클러스터 상태, 버전 호환성, Add-on 준비 |
| workload-safety | 6개 | PDB 차단, 단일 레플리카 중단, PV AZ 고정, 로컬 스토리지 유실, Job 중단, 토폴로지 위반 |
| capacity | 3개 | 노드 용량 여유, 리소스 압박 Pod, Rolling Update surge 용량 |
| infrastructure | 4개 | IaC 상태 드리프트, 노드 이미지 가용성, 오토스케일러 호환성, Recreate 감지 |

심각도: `CRITICAL`(즉시 중단) > `HIGH`(사용자 확인) > `MEDIUM`(보고만) > `LOW`(참고)

## 프로젝트 구조

```
├── k8s-upgrade-skills/                 # AI Agent 스킬 정의 (핵심)
│   ├── SKILL.md                        #   루트 라우터 — recipe 검증 + Sub-Skill 분기
│   └── aws/terraform-eks/              #   EKS + Terraform 업그레이드 스킬
│       ├── SKILL.md                    #     Phase 0~7 실행 절차
│       ├── reference.md               #     보고서 템플릿, 중단 조건
│       └── rules/                     #     사전 검증 규칙 시스템 (16개)
│           ├── rule-index.md          #       규칙 색인 + 실행 순서
│           ├── common/                #       공통 규칙 (3개)
│           ├── workload-safety/       #       워크로드 안전성 규칙 (6개)
│           ├── capacity/              #       용량 검증 규칙 (3개)
│           └── infrastructure/        #       인프라 검증 규칙 (4개)
├── example/terraform-eks/              # EKS + Karpenter 참조 Terraform 코드
│   ├── recipe.md                      #   업그레이드 요구사항 예제
│   └── terraform/                     #   eks.tf, network.tf, yamls/ 등
├── install.sh                          # 전역 설치 스크립트
└── README.md
```
