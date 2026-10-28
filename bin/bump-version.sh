#!/usr/bin/env bash
# Default: patch bump, commit local changes, push main; no workflows triggered.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null || fail 'git is required.'
[[ -d .git ]] || fail 'Clone this project from GitHub before bumping the version.'
BRANCH="$(git symbolic-ref -q --short HEAD)" || fail 'Detached HEAD.'
[[ "$BRANCH" == main ]] || fail "Use main (on $BRANCH)."
ORIGIN="$(git remote get-url origin 2>/dev/null || :)"
case "$ORIGIN" in
  https://github.com/ssnanda/sideloader|https://github.com/ssnanda/sideloader.git|git@github.com:ssnanda/sideloader.git|ssh://git@github.com/ssnanda/sideloader.git) ;;
  *) fail "Unexpected Git remote: $ORIGIN" ;;
esac
[[ -f VERSION ]] || fail 'Missing VERSION file.'
CURRENT="$(tr -d '[:space:]' < VERSION)"
[[ "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Invalid VERSION: $CURRENT"
IFS=. read -r MAJOR MINOR PATCH <<< "$CURRENT"
echo "Current SideLoader version: $CURRENT"
echo '  1) Patch  (default)'
echo '  2) Minor'
echo '  3) Major'
echo '  4) Custom version'
echo '  5) Keep version (commit changes only)'
read -r -p 'Choose [1]: ' CHOICE || CHOICE=''
case "${CHOICE:-1}" in
  1) PATCH=$((PATCH + 1)); NEXT="$MAJOR.$MINOR.$PATCH" ;;
  2) MINOR=$((MINOR + 1)); NEXT="$MAJOR.$MINOR.0" ;;
  3) MAJOR=$((MAJOR + 1)); NEXT="$MAJOR.0.0" ;;
  4) read -r -p 'Enter X.Y.Z: ' NEXT; [[ "$NEXT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'Invalid version.' ;;
  5) NEXT="$CURRENT" ;;
  *) fail 'Choose 1-5.' ;;
esac
printf '\nChanges to commit (runtime build/ is ignored):\n'
git status --short
printf '\nVersion %s -> %s\n' "$CURRENT" "$NEXT"
read -r -p 'Commit and push to GitHub? [Y/n] ' OK || OK=''
case "${OK:-Y}" in y|Y|yes|YES) ;; *) echo 'Cancelled.'; exit 0 ;; esac
# Sync before committing to avoid pushing behind origin. Never discard edits.
git fetch origin main
if ! git merge-base --is-ancestor origin/main HEAD; then
  fail 'GitHub has newer commits. Commit/stash and pull latest before bumping.'
fi
printf '%s\n' "$NEXT" > VERSION
git add -A
if git diff --cached --quiet; then
  echo 'No changes to commit.'
  exit 0
fi
if [[ "$NEXT" == "$CURRENT" ]]; then
  git commit -m "Update SideLoader $CURRENT [skip ci]"
else
  git commit -m "Release SideLoader $NEXT [skip ci]"
fi
git push -u origin main
printf 'Pushed %s to GitHub. Run ./bin/build-docker.sh to apply the new version.\n' "$NEXT"
