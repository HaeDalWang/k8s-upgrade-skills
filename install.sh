#!/usr/bin/env bash
# install.sh - K8s Upgrade Skills Global Installer
#
# 두 개의 최상위 스킬을 각 AI 도구의 skills 경로에 설치한다:
#   - k8s-upgrade-skills : K8s/EKS 버전 업그레이드 (루트 라우터 + Terraform-EKS)
#   - helm-k8s-compat    : Helm 차트 ↔ K8s 버전 호환성 사전 점검 (독립 트리거 가능)
#
# Usage:
#   ./install.sh                  # interactive tool selection
#   ./install.sh --tool claude    # install for specific tool
#   ./install.sh --all            # install for all tools
#   ./install.sh --uninstall      # remove from all tools
#   ./install.sh --status         # show install status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 설치 대상 스킬 (최상위 형제 디렉토리)
SKILLS="k8s-upgrade-skills helm-k8s-compat"

# 스킬별 필수 파일 검증 목록
get_required() {
  case "$1" in
    k8s-upgrade-skills) echo "scripts/gate_check.py scripts/phase_gate.py scripts/lib.py scripts/validate_recipe.py" ;;
    helm-k8s-compat)    echo "scripts/helm_compat_check.py scripts/compat_lib.py registry/_schema.md" ;;
    *) echo "" ;;
  esac
}

# 소스 존재 + 필수 파일 검증
for skill in $SKILLS; do
  src="$SCRIPT_DIR/$skill"
  if [[ ! -d "$src" ]]; then
    echo "ERROR: $src not found. Run from repo root." >&2
    exit 1
  fi
  for f in $(get_required "$skill"); do
    if [[ ! -f "$src/$f" ]]; then
      echo "ERROR: Missing required file: $skill/$f" >&2
      exit 1
    fi
  done
done

# Tool -> global skills base path
get_base() {
  case "$1" in
    claude)      echo "$HOME/.claude/skills" ;;
    kiro)        echo "$HOME/.kiro/skills" ;;
    cursor)      echo "$HOME/.cursor/skills" ;;
    antigravity) echo "$HOME/.agent/skills" ;;
    *) echo "Unknown: $1" >&2; return 1 ;;
  esac
}

# 이전 버전이 ~/.claude/agents/ 에 설치했던 파일들.
# 지금은 인라인 모니터로 전환해 sub-agent 정의가 없으므로, 남아 있으면 정리한다.
LEGACY_AGENTS="k8s-drain-monitor.md k8s-service-aware.md"

# 이전 버전 잔여 agent 정의 제거 (호출 금지 문서가 에이전트로 노출되는 것 방지)
clean_legacy_agents() {
  local agent_dir="$HOME/.claude/agents"
  [[ -d "$agent_dir" ]] || return 0
  for f in $LEGACY_AGENTS; do
    if [[ -f "$agent_dir/$f" ]]; then
      rm -f "$agent_dir/$f"
      echo "  [CLEAN] removed legacy agent: ~/.claude/agents/$f"
    fi
  done
}

ALL_TOOLS="claude kiro cursor antigravity"
ACTION="install"
SELECTED=""
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)      SELECTED="$2"; shift 2 ;;
    --all)       SELECTED="$ALL_TOOLS"; shift ;;
    --force)     FORCE=true; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --status)    ACTION="status"; shift ;;
    --help|-h)
      echo "Usage: $0 [--tool TOOL] [--all] [--force] [--uninstall] [--status]"
      echo ""
      echo "Tools: claude, kiro, cursor, antigravity"
      echo "Skills: $SKILLS"
      echo ""
      echo "Options:"
      echo "  --tool TOOL   Install for a specific tool"
      echo "  --all         Install for all tools"
      echo "  --force       Overwrite existing installation (update)"
      echo "  --uninstall   Remove from all tools"
      echo "  --status      Show install status"
      echo ""
      echo "Examples:"
      echo "  $0                      # interactive"
      echo "  $0 --tool claude        # Claude Code only"
      echo "  $0 --all                # all supported tools"
      echo "  $0 --all --force        # update all tools"
      echo "  $0 --uninstall          # remove all"
      echo "  $0 --status             # check status"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Uninstall
if [[ "$ACTION" = "uninstall" ]]; then
  echo ""
  echo "Uninstalling skills..."
  removed=0
  for t in $ALL_TOOLS; do
    base=$(get_base "$t")
    for skill in $SKILLS; do
      dest="$base/$skill"
      if [[ -d "$dest" ]]; then
        rm -rf "$dest"
        echo "  Removed: ${dest/#$HOME/~}"
        removed=$((removed + 1))
      fi
    done
  done
  clean_legacy_agents
  echo ""
  [[ $removed -eq 0 ]] && echo "Nothing to remove." || echo "Removed $removed item(s)."
  exit 0
fi

# Status
if [[ "$ACTION" = "status" ]]; then
  echo ""
  echo "=== install status ==="
  echo ""
  found=0
  for t in $ALL_TOOLS; do
    base=$(get_base "$t")
    echo "  $t -> ${base/#$HOME/~}"
    for skill in $SKILLS; do
      if [[ -d "$base/$skill" ]]; then
        echo "    [OK]   $skill"
        found=$((found + 1))
      else
        echo "    [ ]    $skill"
      fi
    done
  done
  echo ""
  [[ $found -eq 0 ]] && echo "Not installed." || echo "Installed $found skill instance(s)."
  exit 0
fi

# Interactive selection
if [[ -z "$SELECTED" ]]; then
  echo ""
  echo "=== K8s Upgrade Skills Installer ==="
  echo ""
  echo "Skills: $SKILLS"
  echo ""
  echo "Select tool (comma-separated, 'a' for all, 'q' to quit):"
  echo ""
  i=1
  for t in $ALL_TOOLS; do
    base=$(get_base "$t")
    echo "  $i) $t  -> ${base/#$HOME/~}"
    i=$((i + 1))
  done
  echo ""
  printf "Selection: "
  read -r sel

  [[ "$sel" = "q" || "$sel" = "Q" ]] && exit 0

  if [[ "$sel" = "a" || "$sel" = "A" ]]; then
    SELECTED="$ALL_TOOLS"
  else
    SELECTED=""
    IFS=',' read -ra nums <<< "$sel"
    for n in "${nums[@]}"; do
      n=$(echo "$n" | tr -d ' ')
      j=1
      for t in $ALL_TOOLS; do
        [[ "$j" = "$n" ]] && { SELECTED="$SELECTED $t"; break; }
        j=$((j + 1))
      done
    done
  fi
fi

[[ -z "$SELECTED" ]] && { echo "No tools selected."; exit 1; }

# Install
echo ""
echo "Installing skills..."
echo ""
for t in $SELECTED; do
  base=$(get_base "$t")
  mkdir -p "$base"

  for skill in $SKILLS; do
    src="$SCRIPT_DIR/$skill"
    dest="$base/$skill"
    if [[ -d "$dest" ]]; then
      if [[ "$FORCE" = true ]]; then
        rm -rf "$dest"
        echo "  [UPD]  $t/$skill: updating (${dest/#$HOME/~})"
      else
        echo "  [SKIP] $t/$skill: already installed (use --force to update)"
        continue
      fi
    fi
    cp -r "$src" "$dest"
    # 개발 중 생성된 Python 캐시·OS 메타파일은 설치본에 필요 없다
    find "$dest" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$dest" \( -name '*.pyc' -o -name '.DS_Store' \) -delete 2>/dev/null || true
    echo "  [OK]   $t -> ${dest/#$HOME/~}"
  done
done

clean_legacy_agents

echo ""
echo "Done! Skills installed:"
echo "  - k8s-upgrade-skills : \"EKS 클러스터를 업그레이드해줘\""
echo "  - helm-k8s-compat    : \"Helm 차트 호환성 점검해줘\""
