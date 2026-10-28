"""Provenance for the Sideloop core built into the running Docker image.

Sideloop has no reliable semantic release number in this integration. Report
its upstream Git commit together with the versioned SideLoader modifications.
"""
import json
from pathlib import Path

MANIFEST = Path(__file__).with_name("sideloop-build.json")


def status(manifest=None):
    path = Path(manifest) if manifest is not None else MANIFEST
    result = {
        "status": "unknown", "repository": "filippofinke/sideloop",
        "revision": None, "side_loader_version": None,
        "prepared_at": None, "modified": None,
        "message": "Sideloop build information unavailable. Rebuild SideLoader locally.",
    }
    try:
        record = json.loads(path.read_text())
        if not isinstance(record, dict):
            return result
        revision = record.get("upstream_revision")
        version = record.get("sideloader_version")
        timestamp = record.get("prepared_at")
        if (not isinstance(revision, str) or len(revision) != 40
                or any(c not in "0123456789abcdef" for c in revision.lower())
                or not isinstance(version, str) or not version.strip()
                or record.get("repository") != "filippofinke/sideloop"):
            return result
        result.update(status="identified", revision=revision.lower(),
                      side_loader_version=version.strip(),
                      prepared_at=timestamp if isinstance(timestamp, str) else None,
                      modified=True,
                      message="Sideloop core built from this upstream commit with SideLoader overlays. "
                              "Source revision alone does not verify Apple signing.")
    except (OSError, ValueError, TypeError):
        pass
    return result