#!/usr/bin/env bash
# SideLoader updater: make the source-version comparison visible on every run.
# Preserve local commits/edits by default and NEVER push automatically.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL='https://github.com/ssnanda/sideloader.git'
EXPECTED_REPO='ssnanda/sideloader'
FORCE=false
REPORT_ONLY=false

usage() {
  cat <<'HELP'
SideLoader: compare local and GitHub versions, then update the local checkout.

Usage: ./bin/pull-latest.sh [-f|--force] [--help]

Default: display the installed local version immediately; fetch GitHub,
         display the remote version and commit, preserve local commits/edits,
         and show the installed and remote versions after updating.
         No GitHub push or Docker rebuild is performed.
-f, --force: discard uncommitted tracked edits, untracked files, and local-only
             commits; reset to GitHub main. Ignored build/ remains intact.
             Use only when intentionally discarding local work.
HELP
}
while (( $# )); do
  case "$1" in
    -f|--force) FORCE=true ;;
    --report-only) REPORT_ONLY=true ;; # Internal: new script reports after updating itself.
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
  esac
  shift
done
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }

if [[ ! -d "$ROOT_DIR/.git" ]]; then
  if [[ "$REPORT_ONLY" == true ]]; then echo 'No Git checkout to report.' >&2; exit 1; fi
  DEST="$HOME/Projects/sideloader"
  [[ ! -e "$DEST" ]] || { echo "Directory already exists: $DEST" >&2; exit 1; }
  mkdir -p "$(dirname "$DEST")"
  echo 'Cloning SideLoader from GitHub...'
  git clone "$REPO_URL" "$DEST"
  printf '\nDownloaded SideLoader version: %s\n' "$(cat "$DEST/VERSION")"
  printf 'Run %s/bin/build-docker.sh to deploy the new source.\n' "$DEST"
  exit 0
fi
cd "$ROOT_DIR"
ORIGIN="$(git config --get remote.origin.url 2>/dev/null || true)"
case "$ORIGIN" in
  "https://github.com/$EXPECTED_REPO"|"https://github.com/$EXPECTED_REPO.git"|"git@github.com:$EXPECTED_REPO.git"|"ssh://git@github.com/$EXPECTED_REPO.git") ;;
  *) echo "Unexpected origin '$ORIGIN'; expected $EXPECTED_REPO." >&2; exit 1 ;;
esac
BRANCH="$(git symbolic-ref --quiet --short HEAD)" || { echo 'Cannot pull in detached HEAD.' >&2; exit 1; }

version_at() { git show "$1:VERSION" 2>/dev/null | tr -d '\r\n' || printf 'unknown'; }
version_from_file() {
  if [[ -f VERSION ]]; then tr -d '\r\n' < VERSION; else printf 'unknown'; fi
}
short_rev() { git rev-parse --short "$1"; }
print_comparison() {
  local title="$1" local_ver="$2" local_sha="$3" github_ver="$4" github_sha="$5"
  printf '\n%s\n' "$title"
  printf '  Local SideLoader:  %-16s (%s)\n' "$local_ver" "$local_sha"
  printf '  GitHub SideLoader: %-16s (%s)\n' "$github_ver" "$github_sha"
}
status_banner() {
  # Readable in logs, bold in interactive macOS/Linux terminals. No colors
  # required, and NO_COLOR disables terminal control sequences.
  local label="$1" rule="===================================================================="
  printf '\n%s\n' "$rule"
  if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    printf '\033[1m  %s\033[0m\n' "$label"
  else
    printf '  %s\n' "$label"
  fi
  printf '%s\n' "$rule"
}

if [[ "$REPORT_ONLY" == true ]]; then
  # No fetch, stash, checkout or other mutations. This is also used when the
  # updater script was replaced by the very pull that launched it.
  local_sha="$(short_rev HEAD)"
  remote_ref="refs/remotes/origin/$BRANCH"
  if git rev-parse --verify "$remote_ref" >/dev/null 2>&1; then
    remote_sha="$(short_rev "$remote_ref")"
    remote_ver="$(version_at "$remote_ref")"
  else
    remote_sha="unknown"; remote_ver="unknown"
  fi
  print_comparison 'CURRENT VERSIONS (updated updater)' "$(version_from_file)" "$local_sha" "$remote_ver" "$remote_sha"
  if [[ "$(git rev-parse HEAD)" == "$(git rev-parse "$remote_ref" 2>/dev/null || echo unknown)" ]]; then
    status_banner "UPDATE COMPLETE — SIDELOADER $(version_from_file) — LATEST ON GITHUB"
  else
    status_banner "UPDATE COMPLETE — GITHUB SYNCED; LOCAL COMMITS RETAINED"
  fi
  echo 'SOURCE UPDATED. DOCKER IMAGE NOT MODIFIED. Run ./bin/build-docker.sh to deploy.'
  exit 0
fi

if [[ -d "$(git rev-parse --git-path rebase-merge)" || \
      -d "$(git rev-parse --git-path rebase-apply)" || \
      -f "$(git rev-parse --git-path MERGE_HEAD)" || \
      -n "$(git ls-files -u)" ]]; then
  echo 'Resolve the existing merge/rebase/conflicts before pulling.' >&2
  exit 1
fi

OLD_HEAD="$(git rev-parse HEAD)"
OLD_SHA="$(short_rev HEAD)"
OLD_VERSION="$(version_from_file)"
OLD_COMMIT_VERSION="$(version_at HEAD)"
SCRIPT_SHA_BEFORE="$(git hash-object "$ROOT_DIR/bin/pull-latest.sh")"
printf '\n============================================\n'
printf ' SideLoader local version: %s\n' "$OLD_VERSION"
printf ' Local commit: %s\n' "$OLD_SHA"
printf ' Checking GitHub branch: %s\n' "$BRANCH"
printf '============================================\n'
if [[ "$OLD_VERSION" != "$OLD_COMMIT_VERSION" ]]; then
  printf ' Note: local VERSION file differs from committed version %s.\n' "$OLD_COMMIT_VERSION"
fi

status_banner "CHECKING GITHUB FOR SIDELOADER UPDATES"
echo "Fetching latest version from origin/$BRANCH..."
if ! git fetch origin "$BRANCH"; then
  status_banner "UPDATE CHECK FAILED — LOCAL CODE UNCHANGED"
  echo 'Could not fetch GitHub. No local commits were replaced.' >&2
  exit 1
fi
REMOTE_HEAD="$(git rev-parse FETCH_HEAD)"
REMOTE_SHA="$(short_rev FETCH_HEAD)"
REMOTE_VERSION="$(version_at FETCH_HEAD)"
print_comparison 'SIDELOADER VERSION COMPARISON (before update)' "$OLD_VERSION" "$OLD_SHA" "$REMOTE_VERSION" "$REMOTE_SHA"

# A matching commit or an existing descendant is already synchronized with
# GitHub. Do not rebase, stash, or imply an update is being performed.
if [[ "$FORCE" == false ]]; then
  if [[ "$OLD_HEAD" == "$REMOTE_HEAD" ]]; then
    printf 'No GitHub update is needed. Local files and Docker are untouched.\n'
    if [[ "$OLD_VERSION" != "$REMOTE_VERSION" ]]; then
      printf 'NOTE: local VERSION file has edits; GitHub commit is current.\n'
    fi
    print_comparison 'SIDELOADER VERSION COMPARISON (after check)' "$OLD_VERSION" "$OLD_SHA" "$REMOTE_VERSION" "$REMOTE_SHA"
    if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
      echo 'Local uncommitted changes preserved:'
      git status --short
    fi
    status_banner "ALREADY ON LATEST VERSION — SIDELOADER $REMOTE_VERSION"
    echo 'Docker is unchanged by this check.'
    exit 0
  elif git merge-base --is-ancestor "$REMOTE_HEAD" "$OLD_HEAD"; then
    printf 'NO UPDATE NEEDED. Current local HEAD already contains the latest GitHub commit.\n'
    print_comparison 'SIDELOADER VERSION COMPARISON (after check)' "$OLD_VERSION" "$OLD_SHA" "$REMOTE_VERSION" "$REMOTE_SHA"
    printf 'Local-only commits: %s\n' "$(git rev-list --count "$REMOTE_HEAD"..HEAD)"
    if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
      echo 'Uncommitted local edits retained:'
      git status --short
    fi
    status_banner "LATEST GITHUB VERSION ALREADY INCLUDED — LOCAL COMMITS RETAINED"
    echo 'Docker is unchanged by this check.'
    exit 0
  fi
fi

if [[ "$FORCE" == true ]]; then
  status_banner "FORCE RESET REQUESTED — REPLACING LOCAL SOURCE WITH GITHUB $REMOTE_VERSION"
else
  status_banner "UPDATE AVAILABLE — GITHUB $REMOTE_VERSION (LOCAL $OLD_VERSION)"
  printf 'Local commits and edits will be preserved.\n'
fi
STASHED=false
if [[ "$FORCE" == false && -n "$(git status --porcelain --untracked-files=normal)" ]]; then
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

if [[ "$FORCE" == true ]]; then
  status_banner "FORCE RESET IN PROGRESS — REPLACING LOCAL SOURCE"
  echo "FORCE MODE: replacing local commits and tracked/untracked edits with origin/$BRANCH..."
  git reset --hard FETCH_HEAD
  git clean -fd  # Never -x: ignored build/ and local private runtime data are preserved.
else
  status_banner "UPDATING SIDELOADER — PLEASE DO NOT INTERRUPT"
  echo 'Updating from GitHub while preserving local commits...'
  if ! git -c rebase.autoStash=false rebase FETCH_HEAD; then
    status_banner "UPDATE FAILED — REBASE CONFLICT"
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
      status_banner "UPDATE INCOMPLETE — LOCAL EDITS NEED ATTENTION"
      echo 'Code synchronized, but restoring edits conflicted. The stash remains available.' >&2
      exit 1
    fi
  fi
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_SHA="$(short_rev HEAD)"
LOCAL_VERSION="$(version_from_file)"
print_comparison 'SIDELOADER VERSION COMPARISON (after update)' "$LOCAL_VERSION" "$LOCAL_SHA" "$REMOTE_VERSION" "$REMOTE_SHA"
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
if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
  status_banner "UPDATE COMPLETE — SIDELOADER $LOCAL_VERSION — LATEST ON GITHUB"
else
  status_banner "UPDATE COMPLETE — GITHUB SYNCED; LOCAL COMMITS PRESERVED"
fi
printf 'SOURCE UPDATED. DOCKER IMAGE NOT MODIFIED.\n'
printf 'Next step: ./bin/build-docker.sh\n'

# A pull can replace the script currently running. Bash keeps executing the
# old script in memory, so explicitly use the new one for the final report.
# No extra fetch, rebase, or local data changes occur in this handoff.
SCRIPT_SHA_AFTER="$(git hash-object "$ROOT_DIR/bin/pull-latest.sh")"
if [[ "$SCRIPT_SHA_AFTER" != "$SCRIPT_SHA_BEFORE" ]]; then
  echo 'Updater script changed during pull; displaying versions with the newly downloaded updater...'
  if grep -q 'REPORT_ONLY=true' "$ROOT_DIR/bin/pull-latest.sh"; then
    exec bash "$ROOT_DIR/bin/pull-latest.sh" --report-only
  else
    printf 'New updater has no report-only mode; local SideLoader version: %s\n' "$(version_from_file)"
  fi
fi