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

# Agent install path (claude only for now)
get_agent_path() {
  case "$1" in
    claude) echo "$HOME/.claude/agents" ;;
    *) echo "" ;;
  esac
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
    echo "  [OK]   $t -> ${dest/#$HOME/~}"

    # Install agent definitions (claude only, skill이 agents/를 가질 때만)
    agent_dest=$(get_agent_path "$t")
    agent_src="$src/agents"
    if [[ -n "$agent_dest" && -d "$agent_src" ]]; then
      mkdir -p "$agent_dest"
      for agent_file in "$agent_src"/*.md; do
        [[ -f "$agent_file" ]] || continue
        cp "$agent_file" "$agent_dest/"
        echo "  [OK]   $t agent: ${agent_dest/#$HOME/~}/$(basename "$agent_file")"
      done
    fi
  done
done

echo ""
echo "Done! Skills installed:"
echo "  - k8s-upgrade-skills : \"EKS 클러스터를 업그레이드해줘\""
echo "  - helm-k8s-compat    : \"Helm 차트 호환성 점검해줘\""
