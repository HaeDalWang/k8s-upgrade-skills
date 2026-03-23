#!/usr/bin/env bash
# K8s Upgrade Skills — 설치 스크립트
# 사용법: git clone 후 ./install.sh <대상 프로젝트 경로>
#
# 지원 도구:
#   1) Claude Code    → .claude/skills/
#   2) Kiro           → .kiro/steering/
#   3) Cursor         → .cursor/rules/
#   4) Windsurf       → .windsurf/rules/
#   5) GitHub Copilot → .github/copilot-instructions.md
#   6) Gemini CLI     → GEMINI.md
#   7) OpenCode       → AGENTS.md
#   8) Antigravity    → .gemini/AGENTS.md

set -euo pipefail

# ─────────────────────────────────────────────
# 색상
# ─────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="${SCRIPT_DIR}/.claude/skills/k8s-upgrade-skills"

if [[ ! -d "${SKILL_SRC}" ]]; then
  echo -e "${RED}[ERROR] 스킬 소스를 찾을 수 없습니다: ${SKILL_SRC}${NC}"
  echo "이 스크립트는 레포 루트에서 실행해야 합니다."
  exit 1
fi

TARGET_DIR="${1:-}"

if [[ -z "${TARGET_DIR}" ]]; then
  echo -e "${CYAN}K8s Upgrade Skills 설치 스크립트${NC}"
  echo ""
  echo "사용법: $0 <대상 프로젝트 경로>"
  echo ""
  echo "예시:"
  echo "  $0 /path/to/my-terraform-eks-project"
  echo "  $0 .    # 현재 디렉터리에 설치"
  exit 1
fi

# 절대 경로로 변환
TARGET_DIR="$(cd "${TARGET_DIR}" 2>/dev/null && pwd)" || {
  echo -e "${RED}[ERROR] 대상 경로가 존재하지 않습니다: ${1}${NC}"
  exit 1
}

echo -e "${CYAN}K8s Upgrade Skills 설치${NC}"
echo "대상 프로젝트: ${TARGET_DIR}"
echo ""

# ─────────────────────────────────────────────
# 도구 선택
# ─────────────────────────────────────────────
echo "사용 중인 AI 도구를 선택하세요:"
echo ""
echo "  1) Claude Code"
echo "  2) Kiro"
echo "  3) Cursor"
echo "  4) Windsurf"
echo "  5) GitHub Copilot"
echo "  6) Gemini CLI"
echo "  7) OpenCode"
echo "  8) Antigravity"
echo ""
read -rp "번호 입력 (여러 개는 쉼표로 구분, 예: 1,2,3): " TOOL_INPUT

if [[ -z "${TOOL_INPUT}" ]]; then
  echo -e "${RED}[ERROR] 도구를 선택하지 않았습니다.${NC}"
  exit 1
fi

# ─────────────────────────────────────────────
# 룰 콘텐츠 생성 함수
# SKILL.md를 직접 읽어서 출력 — 스킬 파일이 바뀌면 자동 반영
# ─────────────────────────────────────────────
generate_rule_content() {
  local root_skill="${SKILL_SRC}/SKILL.md"

  if [[ ! -f "${root_skill}" ]]; then
    echo -e "${RED}[ERROR] SKILL.md를 찾을 수 없습니다: ${root_skill}${NC}" >&2
    exit 1
  fi

  # YAML frontmatter(--- ... ---) 제거 후 본문만 출력
  awk '
    BEGIN { in_front=0; done=0 }
    /^---$/ && !done {
      if (!in_front) { in_front=1; next }
      else           { in_front=0; done=1; next }
    }
    !in_front { print }
  ' "${root_skill}"
}

# ─────────────────────────────────────────────
# 설치 함수들
# ─────────────────────────────────────────────
install_claude_code() {
  local dest="${TARGET_DIR}/.claude/skills/k8s-upgrade-skills"
  if [[ -d "${dest}" ]]; then
    echo -e "${YELLOW}  [SKIP] 이미 존재합니다: .claude/skills/k8s-upgrade-skills${NC}"
    return
  fi
  mkdir -p "${TARGET_DIR}/.claude/skills"
  cp -r "${SKILL_SRC}" "${dest}"
  echo -e "${GREEN}  [OK] .claude/skills/k8s-upgrade-skills 설치 완료${NC}"
}

install_kiro() {
  local dest="${TARGET_DIR}/.kiro/steering/k8s-upgrade-skills.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [SKIP] 이미 존재합니다: .kiro/steering/k8s-upgrade-skills.md${NC}"
    return
  fi
  mkdir -p "${TARGET_DIR}/.kiro/steering"
  generate_rule_content > "${dest}"
  echo -e "${GREEN}  [OK] .kiro/steering/k8s-upgrade-skills.md 설치 완료${NC}"
}

install_cursor() {
  local dest="${TARGET_DIR}/.cursor/rules/k8s-upgrade-skills.mdc"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [SKIP] 이미 존재합니다: .cursor/rules/k8s-upgrade-skills.mdc${NC}"
    return
  fi
  mkdir -p "${TARGET_DIR}/.cursor/rules"
  {
    echo "---"
    echo "description: Kubernetes 버전 업그레이드 AI Agent 스킬"
    echo "globs:"
    echo "alwaysApply: true"
    echo "---"
    echo ""
    generate_rule_content
  } > "${dest}"
  echo -e "${GREEN}  [OK] .cursor/rules/k8s-upgrade-skills.mdc 설치 완료${NC}"
}

install_windsurf() {
  local dest="${TARGET_DIR}/.windsurf/rules/k8s-upgrade-skills.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [SKIP] 이미 존재합니다: .windsurf/rules/k8s-upgrade-skills.md${NC}"
    return
  fi
  mkdir -p "${TARGET_DIR}/.windsurf/rules"
  generate_rule_content > "${dest}"
  echo -e "${GREEN}  [OK] .windsurf/rules/k8s-upgrade-skills.md 설치 완료${NC}"
}

install_copilot() {
  local dest="${TARGET_DIR}/.github/copilot-instructions.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [WARN] 이미 존재합니다: .github/copilot-instructions.md${NC}"
    echo -e "${YELLOW}         기존 파일 끝에 내용을 추가합니다.${NC}"
    {
      echo ""
      echo "---"
      echo ""
      generate_rule_content
    } >> "${dest}"
  else
    mkdir -p "${TARGET_DIR}/.github"
    generate_rule_content > "${dest}"
  fi
  echo -e "${GREEN}  [OK] .github/copilot-instructions.md 설치 완료${NC}"
}

install_gemini() {
  local dest="${TARGET_DIR}/GEMINI.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [WARN] 이미 존재합니다: GEMINI.md${NC}"
    echo -e "${YELLOW}         기존 파일 끝에 내용을 추가합니다.${NC}"
    {
      echo ""
      echo "---"
      echo ""
      generate_rule_content
    } >> "${dest}"
  else
    generate_rule_content > "${dest}"
  fi
  echo -e "${GREEN}  [OK] GEMINI.md 설치 완료${NC}"
}

install_opencode() {
  local dest="${TARGET_DIR}/AGENTS.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [WARN] 이미 존재합니다: AGENTS.md${NC}"
    echo -e "${YELLOW}         기존 파일 끝에 내용을 추가합니다.${NC}"
    {
      echo ""
      echo "---"
      echo ""
      generate_rule_content
    } >> "${dest}"
  else
    generate_rule_content > "${dest}"
  fi
  echo -e "${GREEN}  [OK] AGENTS.md 설치 완료${NC}"
}

install_antigravity() {
  local dest="${TARGET_DIR}/.gemini/AGENTS.md"
  if [[ -f "${dest}" ]]; then
    echo -e "${YELLOW}  [WARN] 이미 존재합니다: .gemini/AGENTS.md${NC}"
    echo -e "${YELLOW}         기존 파일 끝에 내용을 추가합니다.${NC}"
    {
      echo ""
      echo "---"
      echo ""
      generate_rule_content
    } >> "${dest}"
  else
    mkdir -p "${TARGET_DIR}/.gemini"
    generate_rule_content > "${dest}"
  fi
  echo -e "${GREEN}  [OK] .gemini/AGENTS.md 설치 완료${NC}"
}

# ─────────────────────────────────────────────
# Claude Code 스킬은 모든 도구에서 참조하므로 항상 복사
# ─────────────────────────────────────────────
install_skill_source() {
  local dest="${TARGET_DIR}/.claude/skills/k8s-upgrade-skills"
  if [[ -d "${dest}" ]]; then
    return
  fi
  mkdir -p "${TARGET_DIR}/.claude/skills"
  cp -r "${SKILL_SRC}" "${dest}"
  echo -e "${GREEN}  [OK] .claude/skills/k8s-upgrade-skills 복사 완료 (상세 스킬 참조용)${NC}"
}

# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────
IFS=',' read -ra TOOLS <<< "${TOOL_INPUT}"

HAS_CLAUDE=false
for tool in "${TOOLS[@]}"; do
  tool="$(echo "${tool}" | tr -d ' ')"
  if [[ "${tool}" == "1" ]]; then
    HAS_CLAUDE=true
  fi
done

echo ""

# 상세 스킬 파일은 항상 복사 (Claude Code 선택 안 해도)
install_skill_source

for tool in "${TOOLS[@]}"; do
  tool="$(echo "${tool}" | tr -d ' ')"
  case "${tool}" in
    1)
      echo -e "${CYAN}[Claude Code]${NC}"
      # 이미 install_skill_source에서 복사됨
      echo -e "${GREEN}  [OK] .claude/skills/k8s-upgrade-skills 설치 완료${NC}"
      ;;
    2)
      echo -e "${CYAN}[Kiro]${NC}"
      install_kiro
      ;;
    3)
      echo -e "${CYAN}[Cursor]${NC}"
      install_cursor
      ;;
    4)
      echo -e "${CYAN}[Windsurf]${NC}"
      install_windsurf
      ;;
    5)
      echo -e "${CYAN}[GitHub Copilot]${NC}"
      install_copilot
      ;;
    6)
      echo -e "${CYAN}[Gemini CLI]${NC}"
      install_gemini
      ;;
    7)
      echo -e "${CYAN}[OpenCode]${NC}"
      install_opencode
      ;;
    8)
      echo -e "${CYAN}[Antigravity]${NC}"
      install_antigravity
      ;;
    *)
      echo -e "${RED}[ERROR] 알 수 없는 도구 번호: ${tool}${NC}"
      ;;
  esac
done

echo ""
echo -e "${GREEN}설치 완료!${NC}"
echo ""
echo "다음 단계:"
echo "  1. 대상 프로젝트에 recipe.md를 작성하세요 (recipe.example.yaml 참고)"
echo "  2. AI Agent에게 'EKS 클러스터를 업그레이드해줘' 라고 요청하세요"
