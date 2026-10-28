"""GitHub AltStore discovery with optional, locally stored read-only credentials.

Only HTTPS GitHub API endpoints receive a GitHub token. Never put a token in a
source URL, a response, a log, or a release-asset CDN redirect.
"""
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import config

API = "https://api.github.com"
TOKEN_FILE = "minisideload-github-token"
MAX_REPOS = 500
MAX_CANDIDATES = 250
FILENAMES = {"altstore.json", "alstore.json"}
OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+$")
REF_PREFIX = "github://"


def parse_owner(value):
    value = str(value or "").strip()
    if value.lower().startswith("https://github.com/"):
        url = urllib.parse.urlsplit(value)
        if url.hostname != "github.com" or url.username or url.password or url.port or url.query or url.fragment:
            raise ValueError("enter a GitHub profile URL, such as https://github.com/username")
        parts = [part for part in url.path.split("/") if part]
        if len(parts) != 1:
            raise ValueError("enter a GitHub profile URL, not a repository link")
        value = parts[0]
    if not OWNER.fullmatch(value):
        raise ValueError("enter a GitHub username or https://github.com/username")
    return value


def token_file():
    return config.DATA / TOKEN_FILE


def load_token():
    path = token_file()
    try:
        if path.is_symlink():
            raise ValueError("unsafe GitHub token file; remove the link manually")
        return path.read_text().strip()
    except FileNotFoundError:
        return ""


def save_token(token):
    token = str(token or "").strip()
    if not token or "\n" in token or "\r" in token or len(token) > 512:
        raise ValueError("invalid GitHub token")
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("unsafe GitHub token file")
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(token + "\n")
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        temp.unlink(missing_ok=True)


def forget_token():
    token_file().unlink(missing_ok=True)


def is_ref(url):
    return isinstance(url, str) and url.startswith(REF_PREFIX)


def make_ref(owner, repo, path):
    if not OWNER.fullmatch(owner) or not REPO.fullmatch(repo):
        raise ValueError("invalid GitHub repository name")
    segments = path.split("/")
    if not segments or any(not segment or segment in (".", "..") for segment in segments):
        raise ValueError("invalid source path")
    return f"github://{owner}/{repo}/" + "/".join(urllib.parse.quote(s, safe="-_.~") for s in segments)


def split_ref(value):
    if not is_ref(value):
        raise ValueError("not a GitHub source reference")
    parsed = urllib.parse.urlsplit(value)
    owner = parsed.hostname or ""
    parts = parsed.path.lstrip("/").split("/", 1)
    if parsed.query or parsed.fragment or len(parts) != 2:
        raise ValueError("invalid GitHub source reference")
    repo, path = parts[0], urllib.parse.unquote(parts[1])
    make_ref(owner, repo, path)
    return owner, repo, path


def dedup_key(value):
    """Match internally discovered refs to manually added GitHub raw URLs."""
    if is_ref(value):
        owner, repo, path = split_ref(value)
        return (owner.lower(), repo.lower(), path.casefold())
    p = urllib.parse.urlsplit(str(value))
    if p.scheme != "https" or p.username or p.password or p.query or p.fragment:
        return ("url", str(value).rstrip("/"))
    if p.hostname == "raw.githubusercontent.com":
        pieces = p.path.strip("/").split("/")
        if len(pieces) >= 4 and pieces[2] in ("main", "master"):
            return (pieces[0].lower(), pieces[1].lower(), "/".join(pieces[3:]).casefold())
    return ("url", str(value).rstrip("/"))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlsplit(newurl)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            raise ValueError("unsafe GitHub redirect")
        for info in socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise ValueError("private network redirect refused")
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is not None and p.hostname != urllib.parse.urlsplit(req.full_url).hostname:
            for name in list(newreq.headers):
                if name.lower() in ("authorization", "cookie", "proxy-authorization"):
                    del newreq.headers[name]
        return newreq


_OPENER = urllib.request.build_opener(_Redirect())


def request(url, token="", accept="application/vnd.github+json"):
    """Only attach credentials to api.github.com; other URLs must use no token."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.port or parsed.username or parsed.password:
        raise ValueError("GitHub API URL must be https://api.github.com")
    headers = {"User-Agent": "SideLoader-GitHub-Sources/1", "Accept": accept,
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return _OPENER.open(urllib.request.Request(url, headers=headers), timeout=25)


def read_json(url, token="", limit=5 * 1024 * 1024):
    with request(url, token) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("GitHub API response too large")
    return json.loads(data)


def _api_path(path):
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))


def check_token_owner(token, owner):
    try:
        account = read_json(API + "/user", token)
    except (urllib.error.URLError, ValueError) as exc:
        raise ValueError("GitHub authentication failed; check the read-only token") from exc
    if str(account.get("login", "")).lower() != owner.lower():
        raise ValueError("private-repository token must belong to the GitHub profile being scanned")
    return account["login"]


def _paged(url, token):
    results = []
    for page in range(1, 7):
        separator = "&" if "?" in url else "?"
        data = read_json(f"{url}{separator}per_page=100&page={page}", token, limit=8 * 1024 * 1024)
        if not isinstance(data, list):
            raise ValueError("GitHub repository list was not an array")
        results.extend(data)
        if len(results) >= MAX_REPOS:
            return results[:MAX_REPOS], True
        if len(data) < 100:
            return results, False
    return results[:MAX_REPOS], True


def repositories(owner, token=""):
    if token:
        check_token_owner(token, owner)
        url = API + "/user/repos?affiliation=owner"
    else:
        url = API + "/users/" + urllib.parse.quote(owner) + "/repos?type=owner"
    repos, limited = _paged(url, token)
    repos = [r for r in repos if isinstance(r, dict) and str((r.get("owner") or {}).get("login", "")).lower() == owner.lower()]
    return repos, limited


def _tree_candidates(repo, token):
    owner, name = repo["owner"]["login"], repo["name"]
    branch = repo.get("default_branch")
    if not branch:
        return [], "repository has no default branch"
    uri = (API + "/repos/" + urllib.parse.quote(owner) + "/" + urllib.parse.quote(name)
           + "/git/trees/" + urllib.parse.quote(branch, safe="") + "?recursive=1")
    try:
        tree = read_json(uri, token, limit=15 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return [], f"GitHub tree lookup failed (HTTP {exc.code})"
    except (OSError, ValueError) as exc:
        return [], f"repository scan unavailable: {type(exc).__name__}"
    if tree.get("truncated"):
        return [], "repository tree too large for a complete scan"
    matches = []
    for entry in tree.get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path") or ""
        if path.split("/")[-1].casefold() in FILENAMES:
            matches.append((owner, name, branch, path, repo.get("private") or repo.get("visibility") == "private"))
    if len(matches) > 25:
        return matches[:25], "more than 25 matching files in repository; scan capped"
    return matches, ""


def discover(owner, token=""):
    repos, limited = repositories(owner, token)
    results, errors = [], []
    if limited:
        errors.append("Repository listing limited to 500; remaining repositories not scanned")
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {pool.submit(_tree_candidates, repo, token): repo["name"] for repo in repos if not repo.get("archived")}
        for task in as_completed(jobs):
            name = jobs[task]
            try:
                candidates, error = task.result()
                results.extend(candidates)
                if error:
                    errors.append(f"{name}: {error}")
            except Exception:
                errors.append(f"{name}: repository scan failed")
    return sorted(results, key=lambda i: (i[1].lower(), i[3].lower()))[:MAX_CANDIDATES], sorted(errors), len(repos)


def public_url(owner, repo, branch, path):
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{urllib.parse.quote(branch, safe='/')}/{_api_path(path)}"


def source_contents(ref, max_bytes, token=""):
    owner, repo, path = split_ref(ref)
    uri = API + "/repos/" + owner + "/" + repo + "/contents/" + _api_path(path)
    result = read_json(uri, token or load_token(), limit=max_bytes * 2)
    if not isinstance(result, dict) or result.get("type") != "file":
        raise ValueError("GitHub source path is not a file")
    if int(result.get("size", 0)) > max_bytes:
        raise ValueError("GitHub source JSON exceeds size limit")
    if result.get("encoding") != "base64":
        raise ValueError("GitHub did not return a small readable JSON source")
    content = base64.b64decode(result.get("content", ""), validate=False)
    if len(content) > max_bytes:
        raise ValueError("GitHub source JSON exceeds size limit")
    default_url = result.get("download_url")
    if not default_url:
        raise ValueError("GitHub did not include a source base URL")
    return json.loads(content), default_url


def _release_download(url, token):
    p = urllib.parse.urlsplit(url)
    parts = p.path.strip("/").split("/")
    if len(parts) != 6 or parts[2:4] != ["releases", "download"] or not all(parts):
        return None
    owner, repo, tag, filename = parts[0], parts[1], parts[4], parts[5]
    if not OWNER.fullmatch(owner) or not REPO.fullmatch(repo):
        return None
    uri = API + f"/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    release = read_json(uri, token)
    asset = next((a for a in release.get("assets", []) if a.get("name") == urllib.parse.unquote(filename)), None)
    if asset is None:
        raise ValueError("IPA release asset not found in private GitHub repository")
    url = API + f"/repos/{owner}/{repo}/releases/assets/{asset['id']}"
    return request(url, token, accept="application/octet-stream")


def private_download(url):
    """Return an authenticated stream only for private GitHub release/raw URLs.

    None means normal public/third-party downloads should be used. A token never
    leaves api.github.com, including on cross-host redirects.
    """
    token = load_token()
    if not token:
        return None
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.username or p.password or p.port or p.query or p.fragment:
        return None
    parts = p.path.strip("/").split("/")
    if p.hostname == "github.com" and len(parts) == 6 and parts[2:4] == ["releases", "download"]:
        owner, repo = parts[:2]
    elif p.hostname == "raw.githubusercontent.com" and len(parts) >= 4:
        owner, repo = parts[:2]
    else:
        return None
    if not OWNER.fullmatch(owner) or not REPO.fullmatch(repo):
        return None
    try:
        data = read_json(API + f"/repos/{owner}/{repo}", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not data.get("private"):
        return None
    if p.hostname == "github.com":
        return _release_download(url, token)
    branch = data.get("default_branch", "")
    rest = p.path.strip("/").split("/", 2)[-1]
    prefix = branch + "/"
    if not rest.startswith(prefix):
        raise ValueError("private GitHub raw asset must use the repository default branch")
    path = rest[len(prefix):]
    api = API + f"/repos/{owner}/{repo}/contents/{_api_path(path)}?ref=" + urllib.parse.quote(branch, safe="")
    return request(api, token, accept="application/vnd.github.raw+json")