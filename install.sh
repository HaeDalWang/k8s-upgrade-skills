#!/usr/bin/env bash
# install.sh - K8s Upgrade Skills Global Installer
#
# Usage:
#   ./install.sh                  # interactive tool selection
#   ./install.sh --tool claude    # install for specific tool
#   ./install.sh --all            # install for all tools
#   ./install.sh --uninstall      # remove from all tools
#   ./install.sh --status         # show install status
set -euo pipefail

SKILL_NAME="k8s-upgrade-skills"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/$SKILL_NAME"

if [[ ! -d "$SKILL_SRC" ]]; then
  echo "ERROR: $SKILL_SRC not found. Run from repo root." >&2
  exit 1
fi

# Tool -> global install path
get_path() {
  case "$1" in
    claude)      echo "$HOME/.claude/skills/$SKILL_NAME" ;;
    kiro)        echo "$HOME/.kiro/skills/$SKILL_NAME" ;;
    cursor)      echo "$HOME/.cursor/skills/$SKILL_NAME" ;;
    windsurf)    echo "$HOME/.windsurf/skills/$SKILL_NAME" ;;
    gemini)      echo "$HOME/.gemini/skills/$SKILL_NAME" ;;
    opencode)    echo "$HOME/.agents/skills/$SKILL_NAME" ;;
    antigravity) echo "$HOME/.agent/skills/$SKILL_NAME" ;;
    copilot)     echo "$HOME/.github/skills/$SKILL_NAME" ;;
    *) echo "Unknown: $1" >&2; return 1 ;;
  esac
}

ALL_TOOLS="claude kiro cursor windsurf gemini opencode antigravity copilot"
ACTION="install"
SELECTED=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)      SELECTED="$2"; shift 2 ;;
    --all)       SELECTED="$ALL_TOOLS"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --status)    ACTION="status"; shift ;;
    --help|-h)
      echo "Usage: $0 [--tool TOOL] [--all] [--uninstall] [--status]"
      echo ""
      echo "Tools: claude, kiro, cursor, windsurf, gemini, opencode, antigravity, copilot"
      echo ""
      echo "Examples:"
      echo "  $0                  # interactive"
      echo "  $0 --tool claude    # Claude Code only"
      echo "  $0 --all            # all tools"
      echo "  $0 --uninstall      # remove all"
      echo "  $0 --status         # check status"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Uninstall
if [[ "$ACTION" = "uninstall" ]]; then
  echo ""
  echo "Uninstalling $SKILL_NAME..."
  removed=0
  for t in $ALL_TOOLS; do
    dest=$(get_path "$t")
    if [[ -d "$dest" ]]; then
      rm -rf "$dest"
      echo "  Removed: ${dest/#$HOME/~}"
      removed=$((removed + 1))
    fi
  done
  echo ""
  [[ $removed -eq 0 ]] && echo "Nothing to remove." || echo "Removed from $removed location(s)."
  exit 0
fi

# Status
if [[ "$ACTION" = "status" ]]; then
  echo ""
  echo "=== $SKILL_NAME install status ==="
  echo ""
  found=0
  for t in $ALL_TOOLS; do
    dest=$(get_path "$t")
    if [[ -d "$dest" ]]; then
      echo "  [OK]   $t -> ${dest/#$HOME/~}"
      found=$((found + 1))
    else
      echo "  [ ]    $t"
    fi
  done
  echo ""
  [[ $found -eq 0 ]] && echo "Not installed." || echo "Installed in $found location(s)."
  exit 0
fi

# Interactive selection
if [[ -z "$SELECTED" ]]; then
  echo ""
  echo "=== K8s Upgrade Skills Installer ==="
  echo ""
  echo "Select tool (comma-separated, 'a' for all, 'q' to quit):"
  echo ""
  i=1
  for t in $ALL_TOOLS; do
    dest=$(get_path "$t")
    echo "  $i) $t  -> ${dest/#$HOME/~}"
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
echo "Installing $SKILL_NAME..."
echo ""
for t in $SELECTED; do
  dest=$(get_path "$t")
  if [[ -d "$dest" ]]; then
    echo "  [SKIP] $t: already installed (${dest/#$HOME/~})"
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  cp -r "$SKILL_SRC" "$dest"
  echo "  [OK]   $t -> ${dest/#$HOME/~}"
done

echo ""
echo "Done! Create recipe.md in your EKS project, then ask your AI agent:"
echo '  "EKS 클러스터를 업그레이드해줘"'
