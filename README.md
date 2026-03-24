# K8s Upgrade Skills

Kubernetes 버전 업그레이드를 안전하게 완료할 수 있도록 도와주는 **AI Agent용 Skills**.

AI Agent가 `recipe.md`에 정의된 클러스터 정보를 읽고, 사전 검증 → 업그레이드 실행 → 사후 검증까지 phase-gated 방식으로 자동 수행합니다.

## 개발 현황

| Environment | Platform | IaC | 상태 |
|-------------|----------|-----|------|
| AWS | EKS | Terraform | 🔨 개발 중 (v0 — 기본 동작 확인, 개선 진행 중) |
| On-Premises | Kubespray | None | 📋 계획됨 |

## 설치

```bash
git clone https://github.com/<owner>/k8s-upgrade-skills.git
cd k8s-upgrade-skills
./install.sh /path/to/your-terraform-project
```

설치 스크립트가 사용 중인 AI 도구를 물어보고, 해당 도구의 룰/스킬 경로에 자동으로 설치합니다.

### 지원 도구

| # | 도구 | 설치 경로 |
|---|------|----------|
| 1 | Claude Code | `.claude/skills/k8s-upgrade-skills/` |
| 2 | Kiro | `.kiro/steering/k8s-upgrade-skills.md` |
| 3 | Cursor | `.cursor/rules/k8s-upgrade-skills.mdc` |
| 4 | Windsurf | `.windsurf/rules/k8s-upgrade-skills.md` |
| 5 | GitHub Copilot | `.github/copilot-instructions.md` |
| 6 | Gemini CLI | `GEMINI.md` |
| 7 | OpenCode | `AGENTS.md` |
| 8 | Antigravity | `.gemini/AGENTS.md` |

여러 도구를 동시에 사용한다면 쉼표로 구분해서 선택할 수 있습니다 (예: `1,2,3`).

### 설치 후 사용법

1. 대상 프로젝트 루트에 `recipe.md`를 만들고 클러스터 정보를 채웁니다:

```yaml
environment: aws          # aws | on-prem
platform: eks             # eks | kubespray
iac: terraform            # terraform | none
cluster_name: my-cluster  # 클러스터 식별자
current_version: "1.34"   # 현재 버전 (따옴표 필수)
target_version: "1.35"    # 목표 버전 (따옴표 필수)

# 선택 항목
output_language: ko       # ko | en
notes: ""                 # 특이사항
```

더 많은 예제는 `recipe.example.yaml`을 참고하세요.

2. (선택) MCP 서버를 설정하면 Agent가 더 정확한 정보를 활용할 수 있습니다:

| MCP 서버 | 용도 |
|----------|------|
| `awslabs.eks-mcp-server` | EKS Insights, K8s 리소스 조회 |
| `kubernetes-mcp-server` | kubectl 기반 노드/Pod 상태 조회 |

설정 방법은 사용 중인 AI 도구에 따라 다릅니다 (Claude Code: `.mcp.json`, Kiro: `.kiro/settings/mcp.json` 등).
MCP 서버가 없어도 Agent는 AWS CLI / kubectl로 fallback합니다.

3. AI Agent에게 업그레이드를 요청합니다:

```
EKS 클러스터를 업그레이드해줘
```

## 동작 방식

```
recipe.md 작성 → AI Agent가 읽고 검증 → 플랫폼별 Sub-Skill 라우팅 → Phase별 실행
```

1. `recipe.md`에 필수 항목 6개를 채웁니다
2. AI Agent가 recipe를 검증하고, `(environment, platform, iac)` 조합에 맞는 Sub-Skill로 라우팅합니다
3. Sub-Skill이 phase-gated 방식으로 업그레이드를 수행합니다 (각 phase 통과 조건 미충족 시 즉시 중단)

### EKS + Terraform 업그레이드 흐름

```
Phase 0: 사전 검증 (규칙 기반) → 15개 규칙 순차 실행 (rules/ 참조)
  ├── common/          클러스터 상태, 버전 호환성, Add-on 준비
  ├── workload-safety/ PDB, 단일 레플리카, PV AZ, 로컬 스토리지, Job, 토폴로지
  ├── capacity/        노드 여유분, 리소스 압박, surge 용량
  └── infrastructure/  Terraform drift, AMI 가용성, Karpenter 호환성
Phase 1: tfvars 업데이트   → 버전 및 AMI alias 변경
Phase 2: Control Plane    → terraform apply -target=module.eks
Phase 3: Add-on 검증      → vpc-cni, coredns 등 상태 확인
Phase 4: Data Plane       → Managed Node Group Rolling Update
Phase 5: Karpenter 노드   → Drift Detection 기반 자동 교체
Phase 6: 전체 Terraform   → Full plan & apply
Phase 7: 최종 검증        → 클러스터 전체 상태 확인
```

## 사전 검증 규칙 시스템

| 카테고리 | 규칙 수 | 핵심 검증 내용 |
|----------|---------|---------------|
| common | 3개 | 클러스터 상태, 버전 호환성, Add-on 준비 |
| workload-safety | 6개 | PDB 차단, 단일 레플리카 중단, PV AZ 고정, 로컬 스토리지 유실, Job 중단, 토폴로지 위반 |
| capacity | 3개 | 노드 용량 여유, 리소스 압박 Pod, Rolling Update surge 용량 |
| infrastructure | 3개 | Terraform 드리프트, AMI 가용성, Karpenter 호환성 |

심각도: `CRITICAL`(즉시 중단) > `HIGH`(사용자 확인) > `MEDIUM`(보고만) > `LOW`(참고)

## 안전 규칙

- 마이너 버전 +1 단계씩만 업그레이드 (1.34 → 1.36 직접 불가)
- Control Plane 먼저, Data Plane은 항상 이후에 진행
- `terraform plan` 없이 `apply` 하지 않음
- PDB `disruptionsAllowed == 0`이면 강제 drain 하지 않고 사용자에게 보고
- 예상치 못한 리소스 삭제가 plan에 나타나면 즉시 중단
- 실패 시 자동 롤백 시도 없이 사용자에게 보고 후 판단 대기
- 단일 레플리카 워크로드 사전 감지 — drain 시 서비스 중단 위험 사전 보고
- PV AZ 어피니티 교차 분석 — drain 후 재스케줄 불가 위험 사전 차단
- 토폴로지 제약 위반 예측 — DoNotSchedule TSC + 노드 부족 시 Pending 방지

## 프로젝트 구조

```
├── k8s-upgrade-skills/                 # AI Agent 스킬 정의 (핵심)
│   ├── SKILL.md                        #   루트 라우터 — recipe 검증 + Sub-Skill 분기
│   └── aws/terraform-eks/              #   EKS + Terraform 업그레이드 스킬
│       ├── SKILL.md                    #     Phase 0~7 실행 절차
│       ├── reference.md               #     보고서 템플릿, 중단 조건
│       └── rules/                     #     사전 검증 규칙 시스템
│           ├── rule-index.md          #       규칙 색인 + 실행 순서
│           ├── common/                #       공통 규칙 (3개)
│           ├── workload-safety/       #       워크로드 안전성 규칙 (6개)
│           ├── capacity/              #       용량 검증 규칙 (3개)
│           └── infrastructure/        #       인프라 검증 규칙 (3개)
├── example/                            # 플랫폼별 참조 인프라
│   ├── terraform-eks/                  #   EKS + Karpenter Terraform 예제
│   │   └── terraform/
│   │       ├── eks.tf                  #     EKS 클러스터, Karpenter, Add-on
│   │       ├── workload.tf            #     검증용 워크로드 (Valkey, 트래픽 생성기, Deprecated API)
│   │       ├── yamls/                 #     업그레이드 위험 시나리오 샘플 (6개)
│   │       └── ...                    #     network.tf, variables.tf 등
│   └── kubespray-onprem/              #   온프레미스 Kubespray 예제 (예정)
├── recipe.example.yaml                 # 업그레이드 요구사항 예제
└── install.sh                          # 설치 스크립트 (8개 AI 도구 지원)
```
