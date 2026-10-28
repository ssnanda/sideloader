#!/usr/bin/env bash
# Siftidy-style version workflow: default patch, commit all local edits, and push.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
VERSION_FILE="$ROOT_DIR/VERSION"
APP_NAME='SideLoader'
VERSION_OVERRIDE=''
BUMP_PART=''
NO_BUMP=false
DO_PUSH=true
YES=false

usage() {
  cat <<'USAGE'
SideLoader version bump, commit and optional push.

Usage:
  ./bin/bump-version.sh [--bump patch|minor|major|build] [--yes] [--no-push]
  ./bin/bump-version.sh --version X.Y.Z+B [--yes] [--no-push]
  ./bin/bump-version.sh --no-bump [--yes] [--no-push]

Press Enter for a patch bump. The newer of the local version and published
Git tags is used as the release baseline. Non-ignored project edits are
committed and pushed by default. Use --no-bump to commit without changing
VERSION. Ignored build/ runtime data, Apple credentials and IPAs are excluded.
USAGE
}
validate_version() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]] || {
    echo "Version must be X.Y.Z+B: $1" >&2; exit 1;
  }
}
bump_version() {
  local current="$1" part="$2" semantic build major minor patch
  semantic="${current%+*}"
  build="${current#*+}"
  IFS='.' read -r major minor patch <<< "$semantic"
  case "$part" in
    patch) patch=$((patch + 1)); build=$((build + 1)) ;;
    minor) minor=$((minor + 1)); patch=0; build=$((build + 1)) ;;
    major) major=$((major + 1)); minor=0; patch=0; build=$((build + 1)) ;;
    build) build=$((build + 1)) ;;
    *) echo "Invalid bump type: $part" >&2; exit 1 ;;
  esac
  echo "$major.$minor.$patch+$build"
}
version_gt() {
  local x1 x2 x3 y1 y2 y3
  IFS='.' read -r x1 x2 x3 <<< "$1"
  IFS='.' read -r y1 y2 y3 <<< "$2"
  if (( x1 != y1 )); then (( x1 > y1 )); return; fi
  if (( x2 != y2 )); then (( x2 > y2 )); return; fi
  (( x3 > y3 ))
}
latest_tag() {
  command -v python3 >/dev/null 2>&1 || return 0
  local remote_tags
  if ! remote_tags="$(git ls-remote --tags --refs origin 2>/dev/null)"; then
    echo 'Warning: cannot check GitHub tags; using local version.' >&2
    return 0
  fi
  printf '%s\n' "$remote_tags" | python3 -c '
import re,sys
found=[]
for line in sys.stdin:
    match=re.search(r"refs/tags/v(\d+)\.(\d+)\.(\d+)\s*$",line)
    if match: found.append(tuple(map(int,match.groups())))
if found: print(".".join(map(str,max(found))))
'
}
choose_version() {
  local current="$1" base="$2" choice custom
  while true; do
    cat >&2 <<MENU
Current local version: $current
Published-version baseline: $base

Choose release type:
  1) patch  ($(bump_version "$base" patch))
  2) minor  ($(bump_version "$base" minor))
  3) major  ($(bump_version "$base" major))
  4) build  ($(bump_version "$current" build))
  5) custom version
  6) no bump (keep $current)
MENU
    read -r -p 'Enter choice (1-6, default=1): ' choice || choice=''
    case "${choice:-1}" in
      1|patch|p) bump_version "$base" patch; return ;;
      2|minor|m) bump_version "$base" minor; return ;;
      3|major|M) bump_version "$base" major; return ;;
      4|build|b) bump_version "$current" build; return ;;
      5|custom|c)
        read -r -p 'Enter version X.Y.Z+B: ' custom
        validate_version "$custom"
        echo "$custom"
        return ;;
      6|none|no-bump|n) echo '__NO_BUMP__'; return ;;
      *) echo 'Choose 1-6.' >&2 ;;
    esac
  done
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) [[ $# -ge 2 ]] || exit 2; VERSION_OVERRIDE="$2"; shift 2 ;;
    --bump) [[ $# -ge 2 ]] || exit 2; BUMP_PART="$2"; shift 2 ;;
    --no-bump) NO_BUMP=true; shift ;;
    --no-push) DO_PUSH=false; shift ;;
    -y|--yes) YES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done
COUNT=0
[[ -n "$VERSION_OVERRIDE" ]] && COUNT=$((COUNT + 1))
[[ -n "$BUMP_PART" ]] && COUNT=$((COUNT + 1))
[[ "$NO_BUMP" == true ]] && COUNT=$((COUNT + 1))
(( COUNT <= 1 )) || { echo 'Choose only one of --version, --bump, --no-bump.' >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo 'Clone from GitHub first.' >&2; exit 1; }
BRANCH="$(git symbolic-ref --quiet --short HEAD)" || { echo 'Cannot bump detached HEAD.' >&2; exit 1; }
[[ -f "$VERSION_FILE" ]] || { echo 'VERSION is missing.' >&2; exit 1; }
CURRENT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
validate_version "$CURRENT_VERSION"
LATEST="$(latest_tag)"
BASE="$CURRENT_VERSION"
if [[ -n "$LATEST" ]] && version_gt "$LATEST" "${CURRENT_VERSION%+*}"; then
  BASE="$LATEST+${CURRENT_VERSION#*+}"
fi
echo "Latest GitHub release tag: ${LATEST:-unknown}" >&2

if [[ "$NO_BUMP" == true ]]; then
  NEXT_VERSION="$CURRENT_VERSION"
elif [[ -n "$VERSION_OVERRIDE" ]]; then
  NEXT_VERSION="$VERSION_OVERRIDE"
elif [[ -n "$BUMP_PART" ]]; then
  if [[ "$BUMP_PART" == build ]]; then
    NEXT_VERSION="$(bump_version "$CURRENT_VERSION" build)"
  else
    NEXT_VERSION="$(bump_version "$BASE" "$BUMP_PART")"
  fi
else
  NEXT_VERSION="$(choose_version "$CURRENT_VERSION" "$BASE")"
  if [[ "$NEXT_VERSION" == '__NO_BUMP__' ]]; then
    NO_BUMP=true
    NEXT_VERSION="$CURRENT_VERSION"
  fi
fi
validate_version "$NEXT_VERSION"
if [[ "$NO_BUMP" != true && "$CURRENT_VERSION" == "$NEXT_VERSION" ]]; then
  echo "Version already equals $NEXT_VERSION." >&2; exit 1
fi
if [[ "$NO_BUMP" != true && -n "$LATEST" ]] && ! version_gt "${NEXT_VERSION%+*}" "$LATEST"; then
  echo "Note: v${NEXT_VERSION%+*} is not newer than v$LATEST; no new release expected." >&2
fi
if [[ "$DO_PUSH" == true ]]; then
  ACTION='commit all local changes and push'
else
  ACTION='commit all local changes locally (no push)'
fi
if [[ "$YES" != true ]]; then
  if [[ -n "$(git status --short)" ]]; then
    echo 'Other local changes that will be included:'
    git status --short
  fi
  if [[ "$NO_BUMP" == true ]]; then
    PROMPT="Keep version $CURRENT_VERSION and $ACTION?"
  else
    PROMPT="Bump to $NEXT_VERSION and $ACTION?"
  fi
  read -r -p "$PROMPT [Y/n] " CONFIRM || CONFIRM=''
  case "${CONFIRM:-y}" in y|Y|yes|YES) ;; *) echo 'Cancelled.'; exit 0 ;; esac
fi

if [[ "$NO_BUMP" != true ]]; then
  printf '%s\n' "$NEXT_VERSION" > "$VERSION_FILE"
fi
git add -A
if git diff --cached --quiet; then
  echo 'Nothing changed; no commit created.' >&2
  exit 0
fi
if [[ "$NO_BUMP" == true ]]; then
  git commit -m "Update $APP_NAME $CURRENT_VERSION [skip ci]"
  echo "Version unchanged: $CURRENT_VERSION"
else
  git commit -m "Release $APP_NAME $NEXT_VERSION [skip ci]"
  echo "Version: $CURRENT_VERSION -> $NEXT_VERSION"
fi
if [[ "$DO_PUSH" == true ]]; then
  "$ROOT_DIR/bin/pull-latest.sh"
  git push origin "$BRANCH"
  echo "Pushed version to origin/$BRANCH. Run ./bin/build-docker.sh to rebuild locally."
fi
