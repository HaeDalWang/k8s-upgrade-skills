---
# ── 필수 필드 ──────────────────────────────────────────────
environment: aws          # aws | on-prem
platform: eks             # eks | kubespray
iac: terraform            # terraform | none
cluster_name: upgrade-skill
current_version: "1.34"   # 따옴표 필수. 현재 클러스터 버전
target_version: "1.35"    # 따옴표 필수. current_version의 차기 마이너 버전만 허용 (+1)

# ── 선택 필드 ──────────────────────────────────────────────
output_language: ko       # ko | en (기본: ko) — 계획서·보고서 출력 언어

# ── 서비스 가용성 모니터링 (선택) ──────────────────────────
# 없으면 Service-Aware Sub-Agent가 투입되지 않습니다.
# 노드 교체 중 서비스 엔드포인트 수와 HTTP 헬스체크를 실시간 감시합니다.
#
# min_endpoints: 정상으로 간주할 최소 ready 엔드포인트 수
# health_check_url: 외부에서 접근 가능한 헬스체크 URL (없으면 EndpointSlice만 확인)
#   → health_check_url 없이는 ALB/Ingress 전파 지연으로 인한 일시적 5xx를 감지할 수 없습니다.
#   → 진정한 무중단을 원한다면 health_check_url 설정을 강력 권장합니다.
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: "https://api.example.com/health"  # 외부 접근 가능 URL
  - name: my-worker
    namespace: production
    min_endpoints: 1
    # health_check_url 없음 → BestEffort 모드 (EndpointSlice만 확인)
---

<!--
  recipe.md — EKS 업그레이드 요구사항 파일
  
  이 파일을 EKS 프로젝트 루트에 배치하세요.
  AI Agent가 이 파일을 읽고 업그레이드를 진행합니다.
  
  검증: python3 k8s-upgrade-skills/scripts/validate_recipe.py recipe.md
  
  ─────────────────────────────────────────────────────────────
  파일 구조
  ─────────────────────────────────────────────────────────────
  
  이 파일은 두 부분으로 구성됩니다:
  
  1. frontmatter (--- 사이): 스크립트가 검증하는 구조화 필드
     - 버전 건너뛰기 방지, 플랫폼 라우팅 등 안전 검증에 사용
     - 반드시 정해진 형식을 지켜야 합니다
  
  2. body (--- 아래 이 섹션): LLM이 읽는 자유 형식 컨텍스트
     - 현재 상황, 제약사항, 특이사항을 자유롭게 서술
     - 포맷 제약 없음 — 마크다운, 불릿, 자유 문장 모두 가능
     - AI Agent가 이 내용을 해석해 업그레이드 계획서에 반영합니다
  
  ─────────────────────────────────────────────────────────────
  컨텍스트 작성 예시
  ─────────────────────────────────────────────────────────────
  
  - "my-api ↔ payment-service 간 간헐적 통신 실패 발생 중 (원인 조사 중)"
  - "유지보수 윈도우: 새벽 02:00~04:00 KST"
  - "zero downtime 필수 — 서비스 중단 허용 불가"
  - "PDB 임시 완화 가능 (팀장 승인 완료)"
  - "Karpenter spot 비율 높음 — 노드 교체 시 지연 가능성 있음"
  
  특이사항이 없으면 아래 내용을 비워두거나 삭제해도 됩니다.
-->

## 업그레이드 컨텍스트

### 현재 상황
- 특이사항 없음

### 제약 및 요구사항
- zero downtime 필수 — 서비스 중단 허용 불가

### 기타
- (없음)
