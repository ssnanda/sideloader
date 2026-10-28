"""Read provenance of the AltServer-Linux executable built into this image.

A pinned source revision is NOT proof that Apple account authentication works.
Never infer the actual backend version from SideLoader's version or git checkout.
"""
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path

EXPECTED_REVISION = "5c32531fe0eb6ff87ed8f7b137da803c91945a02"
METADATA_PATH = Path("/etc/sideloader/altserver-build.json")
BINARY_PATH = Path("/usr/local/bin/AltServer")


@lru_cache(maxsize=16)
def status(metadata_path=None, binary_path=None):
    meta_file = Path(metadata_path) if metadata_path is not None else METADATA_PATH
    executable = Path(binary_path) if binary_path is not None else BINARY_PATH
    result = {
        "name": "AltServer-Linux NG", "ref": "unknown", "revision": None,
        "expected_revision": EXPECTED_REVISION, "built_at": None,
        "binary_sha256": None, "status": "unknown",
        "message": "Build provenance unavailable; cannot verify the AltServer-Linux version.",
    }
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            result.update(status="missing_binary", message="AltServer executable missing or not executable.")
            return result
        with executable.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result["binary_sha256"] = digest.hexdigest()
    except OSError:
        result.update(status="unreadable", message="AltServer executable cannot be read.")
        return result
    try:
        metadata = json.loads(meta_file.read_text())
        if not isinstance(metadata, dict):
            raise ValueError("metadata is not an object")
        revision = metadata.get("revision")
        if not isinstance(revision, str) or len(revision) != 40 or not all(c in "0123456789abcdef" for c in revision.lower()):
            raise ValueError("missing or invalid build revision")
        result["revision"] = revision.lower()
        if metadata.get("ref") == "ng":
            result["ref"] = "ng"
        if isinstance(metadata.get("built_at"), str):
            result["built_at"] = metadata["built_at"][:35]
    except (OSError, ValueError, TypeError):
        result.update(status="unknown", message="AltServer binary present but its build revision cannot be confirmed.")
        return result
    if result["revision"] != EXPECTED_REVISION or result["ref"] != "ng":
        result.update(status="unexpected", message="Installed AltServer-Linux revision differs from SideLoader's pinned NG build.")
    else:
        result.update(status="pinned", message="Running binary and pinned NG build metadata present. This does not verify Apple sign-in.")
    return result


# Manual, unauthenticated metadata lookup. No Apple Account credentials,
# signing files, or IPA bytes are sent by this update check.
import datetime
import urllib.error
import urllib.request

UPSTREAM_REPOSITORY = "jaakkopalvaila/AltServer-Linux"
UPSTREAM_BRANCH = "ng"
API_BASE = "https://api.github.com/repos/" + UPSTREAM_REPOSITORY
_SHA = set("0123456789abcdef")


def _github_json(url):
    # Fixed GitHub API endpoints only; never accept a user-supplied URL here.
    if not (url == API_BASE + "/commits/ng" or
            url.startswith(API_BASE + "/compare/")):
        raise ValueError("Unexpected GitHub update-check endpoint")
    request = urllib.request.Request(url, headers={
        "User-Agent": "SideLoader-AltServer-version-check",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("GitHub metadata response too large")
        return json.loads(data)


def check_updates():
    """Check latest NG branch; never download, change, or launch AltServer."""
    installed = status()
    outcome = {
        "installed_revision": installed.get("revision"),
        "expected_revision": EXPECTED_REVISION,
        "latest_revision": None,
        "latest_date": None,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "status": "unavailable",
        "message": "Could not check GitHub for a newer AltServer-Linux revision.",
        "repository": UPSTREAM_REPOSITORY,
        "branch": UPSTREAM_BRANCH,
    }
    try:
        latest = _github_json(API_BASE + "/commits/ng")
        sha = str(latest.get("sha", "")).lower()
        if len(sha) != 40 or any(c not in _SHA for c in sha):
            raise ValueError("GitHub did not return a valid commit SHA")
        outcome["latest_revision"] = sha
        committer = latest.get("commit", {}).get("committer", {})
        date = committer.get("date") if isinstance(committer, dict) else None
        if isinstance(date, str):
            outcome["latest_date"] = date[:35]
        built = installed.get("revision")
        if not built:
            outcome.update(status="unknown_installed",
                           message="GitHub NG revision found, but the installed AltServer build is unverified. Rebuild locally before comparing.")
        elif built == sha:
            outcome.update(status="up_to_date",
                           message="Installed AltServer-Linux revision matches the latest NG commit.")
        else:
            # GitHub Compare establishes ancestry; a different SHA alone
            # does not prove that the new code is a safe or newer upgrade.
            comparison = _github_json(API_BASE + "/compare/" + built + "..." + sha)
            ahead = int(comparison.get("ahead_by", -1))
            behind = int(comparison.get("behind_by", -1))
            if ahead > 0 and behind == 0:
                outcome.update(status="update_available",
                               message="Newer NG source code is available. SideLoader must validate its patches and pin the new revision before a local Docker rebuild.")
            elif ahead == 0 and behind > 0:
                outcome.update(status="installed_ahead",
                               message="Installed build is ahead of the current NG branch. Review revisions manually.")
            else:
                outcome.update(status="different_revision",
                               message="Installed and latest NG revisions have diverged; review upstream changes before updating.")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError,
            KeyError, TypeError, json.JSONDecodeError) as exc:
        if outcome["latest_revision"]:
            outcome.update(status="different_revision",
                           message="The upstream revision differs, but ancestry could not be verified; do not auto-update.")
        elif isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
            outcome["message"] = "GitHub API rate limit or access restriction; check again later."
        else:
            outcome["message"] = "GitHub update check unavailable; no signing backend changes were made."
    return outcome
