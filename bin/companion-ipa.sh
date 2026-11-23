#!/usr/bin/env bash
# Build the unsigned SideLoader Companion IPA and attach it to the matching
# SideLoader GitHub release. AltServer signs the IPA when the user installs it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT_DIR/companion/SideLoaderCompanion.xcodeproj"
SCHEME='SideLoaderCompanion'
VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
SEMVER="${VERSION%+*}"
BUILD_NUMBER="${VERSION#*+}"
TAG="v$SEMVER"
DIST="$ROOT_DIR/dist"
IPA="$DIST/sideloader-companion-v${SEMVER}-${BUILD_NUMBER}.ipa"
PUBLISH=true
RELEASE_TAG=''

usage() {
  cat <<'USAGE'
Build and publish the SideLoader Companion IPA.

Usage: ./bin/companion-ipa.sh [--build-only] [--tag vX.Y.Z]

  (default)     Build an unsigned IPA and upload it to the matching GitHub
                release derived from VERSION.
  --build-only  Build the IPA locally without contacting GitHub.
  --tag TAG     Publish to this existing release instead of VERSION's tag.
  --help        Show this help.

The resulting IPA is intentionally unsigned. SideLoader/AltServer applies the
user's development signature during installation. Publishing requires gh to
be authenticated and the target GitHub release to already exist.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-only) PUBLISH=false; shift ;;
    --tag) [[ $# -ge 2 ]] || { echo '--tag needs a value' >&2; exit 2; }; RELEASE_TAG="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+$ ]] || { echo "Invalid VERSION: $VERSION" >&2; exit 1; }
[[ -d "$PROJECT" ]] || { echo "Missing Xcode project: $PROJECT" >&2; exit 1; }
command -v xcodebuild >/dev/null 2>&1 || { echo 'Xcode command-line tools are required.' >&2; exit 1; }
command -v ditto >/dev/null 2>&1 || { echo 'ditto is required.' >&2; exit 1; }

trash_path() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  osascript - "$target" <<'APPLESCRIPT'
on run argv
  tell application "Finder" to delete POSIX file (item 1 of argv)
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
  MARKETING_VERSION="$SEMVER" \
  CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build

APP="$DERIVED/Build/Products/Release-iphoneos/SideLoader Companion.app"
[[ -d "$APP" ]] || { echo "Built app not found: $APP" >&2; exit 1; }
ditto "$APP" "$PAYLOAD/SideLoader Companion.app"
trash_path "$IPA"
ditto -c -k --sequesterRsrc --keepParent "$PAYLOAD" "$IPA"
echo "Built: $IPA"

if [[ "$PUBLISH" != true ]]; then
  echo 'Build-only mode: GitHub release was not changed.'
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo 'GitHub CLI (gh) is required to publish.' >&2; exit 1; }
TARGET_TAG="${RELEASE_TAG:-$TAG}"
gh auth status >/dev/null
gh release view "$TARGET_TAG" --repo ssnanda/sideloader >/dev/null || {
  echo "GitHub release $TARGET_TAG does not exist. Create and verify the SideLoader release first." >&2
  exit 1
}
echo "Uploading $(basename "$IPA") to SideLoader release $TARGET_TAG..."
gh release upload "$TARGET_TAG" "$IPA" --repo ssnanda/sideloader --clobber
echo "Published: https://github.com/ssnanda/sideloader/releases/tag/$TARGET_TAG"
