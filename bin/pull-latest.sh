#!/usr/bin/env bash
# Run without arguments to fast-forward local source from GitHub.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO='https://github.com/ssnanda/sideloader.git'
EXPECTED='ssnanda/sideloader'
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null || fail 'git is required.'
if [[ ! -d "$ROOT/.git" ]]; then
  DEST="$HOME/Projects/sideloader"
  [[ ! -e "$DEST" ]] || fail "Target exists but is not a checkout: $DEST"
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO" "$DEST"
  printf '\nCloned project to %s\n' "$DEST"
  exit 0
fi
cd "$ROOT"
ORIGIN="$(git remote get-url origin 2>/dev/null || :)"
case "$ORIGIN" in
  "https://github.com/$EXPECTED"|"https://github.com/$EXPECTED.git"|"git@github.com:$EXPECTED.git"|"ssh://git@github.com/$EXPECTED.git") ;;
  *) fail "Unexpected origin '$ORIGIN'; expected $EXPECTED. Refusing to pull." ;;
esac
BRANCH="$(git symbolic-ref -q --short HEAD)" || fail 'Detached HEAD; checkout main first.'
[[ "$BRANCH" == main ]] || fail "Expected main; current branch is $BRANCH."
[[ -z "$(git status --porcelain)" ]] || fail 'Local changes detected. Commit them with bin/bump-version.sh first.'
printf 'Checking GitHub for the latest code…\n'
git fetch --prune origin main
git merge --ff-only origin/main
printf 'Local code is current: %s\n' "$(git rev-parse --short HEAD)"
printf 'Docker runtime is not changed until you run ./bin/build-docker.sh.\n'
