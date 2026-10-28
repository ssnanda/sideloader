#!/usr/bin/env bash
# SideLoader updater: report local vs GitHub versions before and after synchronizing.
# Preserve local commits/edits by default and NEVER push automatically.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL='https://github.com/ssnanda/sideloader.git'
EXPECTED_REPO='ssnanda/sideloader'
FORCE=false

usage() {
  cat <<'HELP'
SideLoader: compare and update the local project from GitHub.

Usage: ./bin/pull-latest.sh [-f|--force] [--help]

Default: show local/GitHub versions, download remote changes, rebase local
         commits safely, then restore uncommitted/untracked edits.
         Nothing is pushed. The ignored build/ folder is never touched.
-f, --force: discard uncommitted tracked edits, untracked files, and local-only
             commits, then reset to GitHub main. IGNORED build/ remains intact.
             Use only when you deliberately want to discard local work.
When started from an extracted ZIP, clone to ~/Projects/sideloader.
HELP
}
while (( $# )); do
  case "$1" in
    -f|--force) FORCE=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
  esac
  shift
done
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }

if [[ ! -d "$ROOT_DIR/.git" ]]; then
  DEST="$HOME/Projects/sideloader"
  [[ ! -e "$DEST" ]] || { echo "Directory already exists: $DEST" >&2; exit 1; }
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO_URL" "$DEST"
  printf '\nSideLoader cloned to %s\nVersion: %s\nRun ./bin/build-docker.sh to deploy.\n' "$DEST" "$(cat "$DEST/VERSION")"
  exit 0
fi
cd "$ROOT_DIR"
ORIGIN="$(git config --get remote.origin.url 2>/dev/null || true)"
case "$ORIGIN" in
  "https://github.com/$EXPECTED_REPO"|"https://github.com/$EXPECTED_REPO.git"|"git@github.com:$EXPECTED_REPO.git"|"ssh://git@github.com/$EXPECTED_REPO.git") ;;
  *) echo "Unexpected origin '$ORIGIN'; expected $EXPECTED_REPO." >&2; exit 1 ;;
esac
BRANCH="$(git symbolic-ref --quiet --short HEAD)" || { echo 'Cannot pull in detached HEAD.' >&2; exit 1; }

if [[ -d "$(git rev-parse --git-path rebase-merge)" || \
      -d "$(git rev-parse --git-path rebase-apply)" || \
      -f "$(git rev-parse --git-path MERGE_HEAD)" || \
      -n "$(git ls-files -u)" ]]; then
  echo 'Resolve the existing merge/rebase/conflicts before pulling.' >&2
  exit 1
fi

version_at() { git show "$1:VERSION" 2>/dev/null | tr -d '\r\n' || printf 'unknown'; }
OLD_HEAD="$(git rev-parse HEAD)"
OLD_SHA="$(git rev-parse --short HEAD)"
OLD_VERSION="$(version_at HEAD)"

if [[ "$FORCE" == false ]]; then
  STASHED=false
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo 'Preserving local uncommitted changes and untracked files...'
    PREVIOUS_STASH="$(git rev-parse -q --verify refs/stash 2>/dev/null || true)"
    git stash push --include-untracked -m "sideloader-pull-autostash-$(date +%Y%m%d%H%M%S)" >/dev/null
    NEW_STASH="$(git rev-parse -q --verify refs/stash 2>/dev/null || true)"
    if [[ -z "$NEW_STASH" || "$NEW_STASH" == "$PREVIOUS_STASH" ]]; then
      echo 'Could not safely stash local changes; cancelled.' >&2
      exit 1
    fi
    STASHED=true
  fi
fi

echo "Checking origin/$BRANCH..."
if ! git fetch origin "$BRANCH"; then
  echo 'Could not fetch GitHub. No local commits were replaced.' >&2
  if [[ "${STASHED:-false}" == true ]]; then git stash pop --index || true; fi
  exit 1
fi
REMOTE_HEAD="$(git rev-parse FETCH_HEAD)"
REMOTE_SHA="$(git rev-parse --short FETCH_HEAD)"
REMOTE_VERSION="$(version_at FETCH_HEAD)"
printf '\nSideLoader version comparison (before update)\n'
printf '  Local:  %-15s commit %s\n' "$OLD_VERSION" "$OLD_SHA"
printf '  GitHub: %-15s commit %s\n\n' "$REMOTE_VERSION" "$REMOTE_SHA"

if [[ "$FORCE" == true ]]; then
  echo "FORCE MODE: replacing local commits and tracked/untracked edits with origin/$BRANCH..."
  git reset --hard FETCH_HEAD
  git clean -fd  # Never -x: ignored build/ and local private runtime data are preserved.
else
  echo 'Downloading/rebasing GitHub changes while preserving local commits...'
  if ! git -c rebase.autoStash=false rebase FETCH_HEAD; then
    echo 'Rebase failed. Attempting to restore the pre-pull state.' >&2
    git rebase --abort >/dev/null 2>&1 || true
    if [[ "$STASHED" == true ]]; then
      if ! git stash pop --index; then echo 'Your edits remain in git stash if restoration conflicted.' >&2; fi
    fi
    exit 1
  fi
  if [[ "$STASHED" == true ]]; then
    echo 'Restoring uncommitted local changes...'
    if ! git stash pop --index; then
      echo 'Code synchronized, but restoring edits conflicted. The stash remains available.' >&2
      exit 1
    fi
  fi
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_SHA="$(git rev-parse --short HEAD)"
LOCAL_VERSION="$(version_at HEAD)"
printf '\nCurrent SideLoader state\n'
printf '  Local:  %-15s commit %s\n' "$LOCAL_VERSION" "$LOCAL_SHA"
printf '  GitHub: %-15s commit %s\n' "$REMOTE_VERSION" "$REMOTE_SHA"
if [[ "$OLD_HEAD" != "$LOCAL_HEAD" ]]; then
  printf '\nChanges applied:\n'
  git diff --stat "$OLD_HEAD" "$LOCAL_HEAD" || true
elif [[ "$FORCE" == false ]]; then
  echo 'No new commits to apply (already current).'
fi
if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]] && git merge-base --is-ancestor "$REMOTE_HEAD" "$LOCAL_HEAD"; then
  printf '\nLocal-only commits retained: %s (not pushed)\n' "$(git rev-list --count "$REMOTE_HEAD"..HEAD)"
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Uncommitted local edits retained:'
  git status --short
fi
printf '\nUpdate finished. Docker has NOT been rebuilt yet.\n'
printf '  Next: ./bin/build-docker.sh\n'