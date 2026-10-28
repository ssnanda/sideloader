"""Discover and merge GitHub-owned AltStore source files into SideLoader."""
import json
import urllib.error
from . import github_sources


def status():
    return {"has_token": bool(github_sources.load_token())}


def disconnect():
    github_sources.forget_token()
    return {"ok": True}


def scan(source_store, data):
    # Import lazily to avoid a cycle with sources.py.
    from .sources import _catalog, _LOCK
    owner = github_sources.parse_owner(data.get("url", ""))
    supplied = str(data.get("token") or "").strip()
    token = supplied or github_sources.load_token()
    if supplied:
        github_sources.check_token_owner(supplied, owner)
        github_sources.save_token(supplied)
    try:
        candidates, errors, examined = github_sources.discover(owner, token)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub scan failed (HTTP {exc.code}); check token permissions and rate limits") from exc
    except urllib.error.URLError as exc:
        raise ValueError("GitHub is unreachable; check network connectivity") from exc

    with _LOCK:
        existing_urls = source_store._urls()
    known_keys = {github_sources.dedup_key(url) for url in existing_urls}
    known_ids = set()
    for old in existing_urls:
        try:
            identifier = _catalog(old).get("identifier", "").casefold()
            if identifier:
                known_ids.add(identifier)
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
            pass

    to_add, duplicates, invalid = [], 0, []
    for repo_owner, repo, branch, path, is_private in candidates:
        url = (github_sources.make_ref(repo_owner, repo, path) if is_private
               else github_sources.public_url(repo_owner, repo, branch, path))
        key = github_sources.dedup_key(url)
        if key in known_keys:
            duplicates += 1
            continue
        try:
            source = _catalog(url)
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            invalid.append(f"{repo}/{path}: invalid or unreadable ({type(exc).__name__})")
            continue
        identifier = source.get("identifier", "").casefold()
        if identifier and identifier in known_ids:
            duplicates += 1
            continue
        to_add.append((url, repo, source["name"]))
        known_keys.add(key)
        if identifier:
            known_ids.add(identifier)

    added = []
    with _LOCK:
        urls = source_store._urls()
        keys = {github_sources.dedup_key(u) for u in urls}
        for url, repo, name in to_add:
            if github_sources.dedup_key(url) in keys:
                duplicates += 1
                continue
            if len(urls) >= 200:
                errors.append("200-source limit reached; remaining sources were not added")
                break
            urls.append(url)
            keys.add(github_sources.dedup_key(url))
            added.append({"repository": repo, "name": name})
        if added:
            source_store._save(urls)
    return {"ok": True, "owner": owner, "repositories_scanned": examined,
            "matching_files": len(candidates), "added": len(added),
            "already_exists": duplicates, "invalid": len(invalid),
            "sources": added[:100], "warnings": (errors + invalid)[:40],
            "has_token": bool(github_sources.load_token())}