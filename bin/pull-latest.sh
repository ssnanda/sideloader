#!/usr/bin/env bash
# Default: pull the latest code while preserving local edits. -f discards all uncommitted edits and unpushed commits.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL='https://github.com/ssnanda/sideloader.git'
EXPECTED_REPO='ssnanda/sideloader'
FORCE=false
FRESH=false

version_at() {
  git show "$1:VERSION" 2>/dev/null | tr -d '\r\n' || printf 'unknown'
}

version_gt() {
  local left="$1" right="$2"
  local left_major left_minor left_patch left_build
  local right_major right_minor right_patch right_build
  [[ "$left" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]] || return 1
  [[ "$right" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]] || return 1
  IFS='.+ ' read -r left_major left_minor left_patch left_build <<< "$left"
  IFS='.+ ' read -r right_major right_minor right_patch right_build <<< "$right"
  if (( left_major != right_major )); then (( left_major > right_major )); return; fi
  if (( left_minor != right_minor )); then (( left_minor > right_minor )); return; fi
  if (( left_patch != right_patch )); then (( left_patch > right_patch )); return; fi
  (( left_build > right_build ))
}

result_banner() {
  local title="$1"
  local detail="${2:-}"
  printf '\n============================================================\n'
  printf '  %s\n' "$title"
  [[ -z "$detail" ]] || printf '  %s\n' "$detail"
  printf '============================================================\n'
}

usage() {
  cat <<'HELP'
SideLoader: update local project from GitHub.

Usage: ./bin/pull-latest.sh [-f|--force] [--fresh|--wipe] [--help]

Default: stash local edits (including untracked files), rebase on origin,
         then restore those edits. Ignored build/ data is never touched.
         If local is newer than GitHub, report it and exit with status 3 so
         calling scripts cannot continue to an automatic push.
-f, --force: replace tracked files and unpushed commits with the remote branch;
             remove untracked files/directories (NOT ignored build/ data).
             Use only if you intentionally want to discard local work.
--fresh, --wipe: move the ENTIRE local project, including ignored build/ data,
                 to the macOS Trash and clone a clean copy at the same path.
If run from an unpacked ZIP instead of a Git checkout, clone to
~/Projects/sideloader without changing the extracted directory.
HELP
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--force) FORCE=true ;;
    --fresh|--wipe) FRESH=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
if [[ "$FORCE" == true && "$FRESH" == true ]]; then
  echo '--force and --fresh cannot be used together.' >&2
  exit 2
fi
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }

if [[ ! -d "$ROOT_DIR/.git" ]]; then
  DEST="$HOME/Projects/sideloader"
  [[ ! -e "$DEST" ]] || { echo "Directory already exists: $DEST" >&2; exit 1; }
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO_URL" "$DEST"
  CLONED_VERSION="$(tr -d '\r\n' < "$DEST/VERSION" 2>/dev/null || printf 'unknown')"
  echo "Local version:  $CLONED_VERSION"
  echo "GitHub version: $CLONED_VERSION"
  result_banner 'NEW VERSION CLONED' "SideLoader $CLONED_VERSION is ready in $DEST"
  echo 'Docker is unchanged until you run ./bin/build-docker.sh.'
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

if [[ "$FRESH" == true ]]; then
  [[ "$(uname -s)" == Darwin ]] || {
    echo '--fresh currently requires macOS so the old project can be moved safely to Trash.' >&2
    exit 1
  }
  command -v osascript >/dev/null 2>&1 || {
    echo 'macOS Finder access is required for --fresh.' >&2
    exit 1
  }
  echo "Verifying origin/$BRANCH before replacing the local project..."
  git ls-remote --exit-code origin "refs/heads/$BRANCH" >/dev/null || {
    result_banner 'FRESH CLONE CANCELLED' 'GitHub could not be verified; the local project was not touched.' >&2
    exit 1
  }
  PARENT_DIR="$(dirname "$ROOT_DIR")"
  cd "$PARENT_DIR"
  echo "Moving the complete local project to Trash: $ROOT_DIR"
  osascript - "$ROOT_DIR" <<'APPLESCRIPT'
on run argv
  tell application "Finder" to delete POSIX file (item 1 of argv)
end run
APPLESCRIPT
  if [[ -e "$ROOT_DIR" ]]; then
    result_banner 'FRESH CLONE CANCELLED' 'Finder did not move the old project to Trash.' >&2
    exit 1
  fi
  echo "Cloning a clean origin/$BRANCH into $ROOT_DIR..."
  if ! git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$ROOT_DIR"; then
    result_banner 'CLONE FAILED — OLD PROJECT IS IN TRASH' 'Use Finder Put Back to restore it.' >&2
    exit 1
  fi
  FRESH_VERSION="$(tr -d '\r\n' < "$ROOT_DIR/VERSION" 2>/dev/null || printf 'unknown')"
  result_banner 'FRESH VERSION INSTALLED' "SideLoader $FRESH_VERSION was cloned; the previous directory is in Trash."
  echo 'Docker must be rebuilt with ./bin/build-docker.sh; previous build/ runtime data was moved to Trash.'
  exit 0
fi

# Do not disturb an existing merge, rebase or unresolved index.
if [[ -d "$(git rev-parse --git-path rebase-merge)" || \
      -d "$(git rev-parse --git-path rebase-apply)" || \
      -f "$(git rev-parse --git-path MERGE_HEAD)" || \
      -n "$(git ls-files -u)" ]]; then
  echo 'Resolve the existing merge/rebase/conflicts before pulling.' >&2
  exit 1
fi

LOCAL_VERSION_BEFORE="$(tr -d '\r\n' < VERSION 2>/dev/null || printf 'unknown')"
LOCAL_COMMIT_BEFORE="$(git rev-parse --short HEAD)"

echo "Checking origin/$BRANCH..."
if ! git fetch origin "$BRANCH"; then
  result_banner 'UPDATE FAILED' 'Could not retrieve the GitHub version.' >&2
  exit 1
fi

GITHUB_VERSION="$(version_at FETCH_HEAD)"
GITHUB_COMMIT="$(git rev-parse --short FETCH_HEAD)"
REMOTE_CHANGED=false
[[ "$(git rev-list --count HEAD..FETCH_HEAD)" == 0 ]] || REMOTE_CHANGED=true

printf '\nSideLoader version comparison\n'
printf '  Local:  %s (commit %s)\n' "$LOCAL_VERSION_BEFORE" "$LOCAL_COMMIT_BEFORE"
printf '  GitHub: %s (commit %s)\n\n' "$GITHUB_VERSION" "$GITHUB_COMMIT"

if [[ "$FORCE" == true ]]; then
  echo "Force syncing origin/$BRANCH. Uncommitted edits and local-only commits will be discarded."
  git reset --hard FETCH_HEAD
  git clean -fd            # Never -x: ignored build/ remains.
  if [[ "$REMOTE_CHANGED" == true ]]; then
    result_banner 'NEW VERSION PULLED' "SideLoader $GITHUB_VERSION now matches GitHub."
  else
    result_banner 'SAME VERSION' "SideLoader $GITHUB_VERSION already matched GitHub."
  fi
  echo 'Ignored build/ data was preserved. Docker is unchanged until you run ./bin/build-docker.sh.'
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

echo "Updating $ROOT_DIR from origin/$BRANCH..."
if ! git rebase FETCH_HEAD; then
  echo 'Pull failed; attempting to restore local changes.' >&2
  git rebase --abort >/dev/null 2>&1 || true
  if [[ "$STASHED" == true ]]; then
    if ! git stash pop --index; then
      echo 'Your changes remain in git stash if they could not be restored.' >&2
    fi
  fi
  result_banner 'CONFLICT — ACTION REQUIRED' 'The update was not applied cleanly.' >&2
  exit 1
fi
if [[ "$STASHED" == true ]]; then
  echo 'Restoring pre-pull changes...'
  if ! git stash pop --index; then
    echo 'Pull succeeded, but restoring changes conflicted. The stash is retained.' >&2
    result_banner 'CONFLICT — ACTION REQUIRED' 'GitHub was updated, but local changes need attention.' >&2
    exit 1
  fi
fi

LOCAL_VERSION_AFTER="$(tr -d '\r\n' < VERSION 2>/dev/null || printf 'unknown')"
LOCAL_COMMIT_AFTER="$(git rev-parse --short HEAD)"
printf '\nCurrent local state\n'
printf '  Version: %s\n' "$LOCAL_VERSION_AFTER"
printf '  Commit:  %s\n' "$LOCAL_COMMIT_AFTER"

LOCAL_NEWER=false
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)" ]] && \
   git merge-base --is-ancestor FETCH_HEAD HEAD; then
  LOCAL_NEWER=true
elif version_gt "$LOCAL_VERSION_AFTER" "$GITHUB_VERSION"; then
  LOCAL_NEWER=true
fi

if [[ "$LOCAL_NEWER" == true ]]; then
  result_banner 'LOCAL VERSION NEWER — NOT PUSHED' "Local $LOCAL_VERSION_AFTER is ahead of GitHub $GITHUB_VERSION."
  echo 'Automatic push blocked. Review the local commits and push manually only when intended.'
  git status --short
  exit 3
elif [[ "$REMOTE_CHANGED" == true ]]; then
  result_banner 'NEW VERSION PULLED' "GitHub version $GITHUB_VERSION was applied; local work was preserved."
else
  result_banner 'SAME VERSION' "Local and GitHub are both SideLoader $GITHUB_VERSION."
fi
echo 'Docker is unchanged until you run ./bin/build-docker.sh.'
git status --short
