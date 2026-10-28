#!/usr/bin/env bash
# Default: pull the latest code while preserving local edits. -f discards all uncommitted edits and unpushed commits.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL='https://github.com/ssnanda/sideloader.git'
EXPECTED_REPO='ssnanda/sideloader'
FORCE=false

usage() {
  cat <<'HELP'
SideLoader: update local project from GitHub.

Usage: ./bin/pull-latest.sh [-f|--force] [--help]

Default: stash local edits (including untracked files), rebase on origin,
         then restore those edits. Ignored build/ data is never touched.
-f, --force: replace tracked files and unpushed commits with the remote branch;
             remove untracked files/directories (NOT ignored build/ data).
             Use only if you intentionally want to discard local work.
If run from an unpacked ZIP instead of a Git checkout, clone to
~/Projects/sideloader without changing the extracted directory.
HELP
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--force) FORCE=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }

if [[ ! -d "$ROOT_DIR/.git" ]]; then
  DEST="$HOME/Projects/sideloader"
  [[ ! -e "$DEST" ]] || { echo "Directory already exists: $DEST" >&2; exit 1; }
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO_URL" "$DEST"
  echo "SideLoader cloned to $DEST. Run its bin/build-docker.sh to deploy."
  exit 0
fi
cd "$ROOT_DIR"
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
case "$ORIGIN" in
  "https://github.com/$EXPECTED_REPO"|"https://github.com/$EXPECTED_REPO.git"|"git@github.com:$EXPECTED_REPO.git"|"ssh://git@github.com/$EXPECTED_REPO.git") ;;
  *) echo "Unexpected origin '$ORIGIN'; expected $EXPECTED_REPO." >&2; exit 1 ;;
esac
BRANCH="$(git symbolic-ref --quiet --short HEAD)" || {
  echo 'Cannot pull in detached HEAD.' >&2; exit 1;
}

# Do not disturb an existing merge, rebase or unresolved index.
if [[ -d "$(git rev-parse --git-path rebase-merge)" || \
      -d "$(git rev-parse --git-path rebase-apply)" || \
      -f "$(git rev-parse --git-path MERGE_HEAD)" || \
      -n "$(git ls-files -u)" ]]; then
  echo 'Resolve the existing merge/rebase/conflicts before pulling.' >&2
  exit 1
fi

if [[ "$FORCE" == true ]]; then
  echo "Force syncing origin/$BRANCH. Uncommitted edits and local-only commits will be discarded."
  git fetch origin "$BRANCH"  # Never erase data if fetch failed.
  git reset --hard FETCH_HEAD
  git clean -fd            # Never -x: ignored build/ remains.
  echo "SideLoader matches origin/$BRANCH. Ignored build/ data was preserved."
  exit 0
fi

STASHED=false
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo 'Preserving local changes, including untracked files...'
  PREVIOUS_STASH="$(git rev-parse -q --verify refs/stash 2>/dev/null || true)"
  git stash push --include-untracked -m "sideloader-pull-autostash-$(date +%Y%m%d%H%M%S)" >/dev/null
  NEW_STASH="$(git rev-parse -q --verify refs/stash 2>/dev/null || true)"
  if [[ -z "$NEW_STASH" || "$NEW_STASH" == "$PREVIOUS_STASH" ]]; then
    echo 'Could not safely stash local changes; cancelled.' >&2
    exit 1
  fi
  STASHED=true
fi

echo "Pulling origin/$BRANCH into $ROOT_DIR..."
if ! git -c rebase.autoStash=false pull --rebase origin "$BRANCH"; then
  echo 'Pull failed; attempting to restore local changes.' >&2
  git rebase --abort >/dev/null 2>&1 || true
  if [[ "$STASHED" == true ]]; then
    if ! git stash pop --index; then
      echo 'Your changes remain in git stash if they could not be restored.' >&2
    fi
  fi
  exit 1
fi
if [[ "$STASHED" == true ]]; then
  echo 'Restoring pre-pull changes...'
  if ! git stash pop --index; then
    echo 'Pull succeeded, but restoring changes conflicted. The stash is retained.' >&2
    exit 1
  fi
fi
echo "SideLoader is current on $BRANCH. Docker is unchanged until you run ./bin/build-docker.sh."
git status --short
