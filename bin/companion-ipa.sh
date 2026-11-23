#!/usr/bin/env bash
# Build the unsigned SideLoader Companion IPA and attach it to the matching
# SideLoader GitHub release. AltServer signs the IPA when the user installs it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT_DIR/companion/SideLoaderCompanion.xcodeproj"
SCHEME='SideLoaderCompanion'
DIST="$ROOT_DIR/dist"
ALTSTORE_SOURCE="$ROOT_DIR/altstore.json"
PUBLISH=true
RELEASE_TAG=''
BUMP=true
BUMP_ARGS=()

usage() {
  cat <<'USAGE'
Build and publish the SideLoader Companion IPA.

Usage: ./bin/companion-ipa.sh [--build-only] [--tag vX.Y.Z]
                              [--skip-bump] [--no-push]

  (default)     Build an unsigned IPA and upload it to the matching GitHub
                release derived from VERSION.
  --build-only  Build the IPA locally without contacting GitHub.
  --tag TAG     Publish to this existing release instead of VERSION's tag.
  --skip-bump   Build pending changes without running bump-version.sh.
  --no-push     Pass --no-push to bump-version.sh.
  --help        Show this help.

The resulting IPA is intentionally unsigned. SideLoader/AltServer applies the
user's development signature during installation. Publishing requires gh to
be authenticated. A missing matching release is created automatically.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-only) PUBLISH=false; shift ;;
    --tag) [[ $# -ge 2 ]] || { echo '--tag needs a value' >&2; exit 2; }; RELEASE_TAG="$2"; shift 2 ;;
    --skip-bump) BUMP=false; shift ;;
    --no-push) BUMP_ARGS+=(--no-push); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

# Keep release provenance consistent with build-docker.sh: pending source
# changes are versioned, committed and pushed before an artifact is built.
# Read VERSION only after this step so the IPA and release use the new tag.
if [[ "$BUMP" == true && -n "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal)" ]]; then
  echo 'Uncommitted changes detected; running bump-version.sh before building.'
  "$ROOT_DIR/bin/bump-version.sh" ${BUMP_ARGS[@]+"${BUMP_ARGS[@]}"}
fi

VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
SEMVER="${VERSION%+*}"
BUILD_NUMBER="${VERSION#*+}"
TAG="v$SEMVER"
IPA="$DIST/sideloader-companion-v${SEMVER}-${BUILD_NUMBER}.ipa"
STABLE_IPA="$DIST/sideloader-companion.ipa"

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION" >&2; exit 1; }
[[ -d "$PROJECT" ]] || { echo "Missing Xcode project: $PROJECT" >&2; exit 1; }
command -v xcodebuild >/dev/null 2>&1 || { echo 'Xcode command-line tools are required.' >&2; exit 1; }
command -v ditto >/dev/null 2>&1 || { echo 'ditto is required.' >&2; exit 1; }

trash_path() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  osascript - "$target" <<'APPLESCRIPT'
on run argv
  set targetAlias to POSIX file (item 1 of argv) as alias
  tell application "Finder" to delete targetAlias
end run
APPLESCRIPT
}

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sideloader-companion.XXXXXX")"
cleanup() { trash_path "$WORK_DIR" >/dev/null 2>&1 || true; }
trap cleanup EXIT
DERIVED="$WORK_DIR/DerivedData"
PAYLOAD="$WORK_DIR/Payload"

mkdir -p "$DIST" "$PAYLOAD"
echo "Building SideLoader Companion $VERSION (unsigned; AltServer signs during installation)..."
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration Release \
  -sdk iphoneos \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build

APP="$DERIVED/Build/Products/Release-iphoneos/SideLoader Companion.app"
[[ -d "$APP" ]] || { echo "Built app not found: $APP" >&2; exit 1; }
ditto "$APP" "$PAYLOAD/SideLoader Companion.app"
trash_path "$IPA"
ditto -c -k --sequesterRsrc --keepParent "$PAYLOAD" "$IPA"
trash_path "$STABLE_IPA"
ditto "$IPA" "$STABLE_IPA"
echo "Built: $IPA"

if [[ "$PUBLISH" != true ]]; then
  echo 'Build-only mode: GitHub release was not changed.'
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo 'GitHub CLI (gh) is required to publish.' >&2; exit 1; }
[[ -f "$ALTSTORE_SOURCE" ]] || { echo "Missing AltStore source: $ALTSTORE_SOURCE" >&2; exit 1; }
TARGET_TAG="${RELEASE_TAG:-$TAG}"
gh auth status >/dev/null
git fetch origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || {
  echo 'Local HEAD must be committed and pushed to origin/main before publishing a release.' >&2
  exit 1
}
if ! gh release view "$TARGET_TAG" --repo ssnanda/sideloader >/dev/null 2>&1; then
  echo "Creating SideLoader release $TARGET_TAG..."
  gh release create "$TARGET_TAG" --repo ssnanda/sideloader --target main \
    --title "SideLoader $VERSION" \
    --notes "SideLoader $VERSION with the SideLoader Companion IPA and AltStore source."
fi
echo "Uploading $(basename "$IPA"), stable companion IPA, and altstore.json to SideLoader release $TARGET_TAG..."
gh release upload "$TARGET_TAG" "$IPA" "$STABLE_IPA" "$ALTSTORE_SOURCE" --repo ssnanda/sideloader --clobber
echo "Published: https://github.com/ssnanda/sideloader/releases/tag/$TARGET_TAG"
