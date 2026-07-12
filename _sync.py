"""Network sync for Aletheia -- pack fetch on unlock, runner self-update.

Two jobs, both stdlib-only (urllib + zipfile), both conservative about what
they touch on disk:

- fetch_pack(): asks the Yardstick delivery service for the buyer's
  personalized pack (ALETHEIA.md, audit-data.json, START-HERE.md,
  CHOOSE-YOUR-MODEL.md) and installs those files beside the runner.
  It never installs code -- the runner does not modify itself here.

- self_update(): downloads the public repo's main branch and refreshes the
  runner code (aletheia.py, _backends/, _artifacts.py, _eval.py, this file,
  examples). It never touches the buyer's personalization, memory, skills
  they have edited, .env, brand, sessions, or data.
"""

import io
import json
import os
import ssl
import urllib.error
import urllib.request
import zipfile

UNLOCK_ENDPOINT = "https://api.yardstickresearch.app/aletheia/unlock"
UPDATE_ZIP_URL = "https://github.com/ConnorYQueen/yardstick-aletheia/archive/refs/heads/main.zip"
UPDATE_ZIP_PREFIX = "yardstick-aletheia-main/"

MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024  # both the pack and the repo zip are far smaller

# The only files fetch_pack will ever write. Everything else in the pack zip
# (runner code, requirements, backends) already lives in the buyer's clone.
PERSONALIZATION_FILES = (
    "ALETHEIA.md",
    "audit-data.json",
    "START-HERE.md",
    "CHOOSE-YOUR-MODEL.md",
)

# What self_update is allowed to refresh: the runner program itself. Paths are
# zip-root-relative, forward slashes. skills/ is handled separately (add-only).
UPDATE_FILES = (
    "aletheia.py",
    "_artifacts.py",
    "_eval.py",
    "_sync.py",
    "requirements.txt",
    "README.md",
    "ORCHESTRATION.md",
    "LICENSE",
    "_backends/__init__.py",
    "_backends/anthropic_backend.py",
    "_backends/openai_backend.py",
    "eval/cases.example.json",
    "eval/models.example.json",
)

# One string for every pack-fetch failure the buyer can act on. Mirrors the
# service's own copy; deliberately says nothing about inputs' expected shape.
GENERIC_FETCH_FAIL = (
    "Could not fetch your personalized files. Check your code and email against "
    "your Full AI Deployment PDF or PowerPoint, or email hello@yardstickresearch.app. "
    "You can keep using Aletheia; run `python aletheia.py unlock <code> --email you@company.com` "
    "to try again."
)


def _http_get_bytes(url, timeout):
    """GET a URL, enforcing the size cap. Returns bytes or raises."""
    req = urllib.request.Request(url, headers={"User-Agent": "aletheia-runner"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("download exceeds size cap")
    return data


def _is_within(base, target):
    """True if target resolves to base itself or a path underneath it. Used to
    refuse any zip-supplied name that would escape the pack directory."""
    base_abs = os.path.abspath(base)
    target_abs = os.path.abspath(target)
    return target_abs == base_abs or target_abs.startswith(base_abs + os.sep)


def _install_file(dest_path, content):
    """Write content to dest_path, backing up a differing existing file to .bak."""
    if os.path.exists(dest_path):
        with open(dest_path, "rb") as fh:
            existing = fh.read()
        if existing == content:
            return "unchanged"
        with open(dest_path + ".bak", "wb") as fh:
            fh.write(existing)
        status = "updated"
    else:
        status = "added"
    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest_path, "wb") as fh:
        fh.write(content)
    return status


def fetch_pack(pack_dir, code, email):
    """Ask the delivery service for the buyer's pack; install personalization files.

    Returns (ok, message). Never raises; never installs runner code.
    """
    payload = json.dumps({"email": email, "code": code}).encode("utf-8")
    req = urllib.request.Request(
        UNLOCK_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "aletheia-runner"},
        method="POST",
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            body = json.loads(resp.read(1024 * 64).decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        if err.code == 429:
            return False, "Too many attempts right now. Wait a few minutes and try again."
        return False, GENERIC_FETCH_FAIL
    except Exception:
        return False, (
            "Could not reach the Yardstick service (network problem). "
            "You can keep using Aletheia and try `unlock` again later."
        )

    pack_url = body.get("pack_url") if isinstance(body, dict) else None
    if not pack_url:
        return False, GENERIC_FETCH_FAIL

    try:
        blob = _http_get_bytes(pack_url, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        return False, (
            "Matched your purchase but the download failed. "
            "Try `unlock` again in a minute, or email hello@yardstickresearch.app."
        )

    installed = []
    names = set(zf.namelist())
    for fname in PERSONALIZATION_FILES:
        if fname not in names:
            continue
        content = zf.read(fname)
        status = _install_file(os.path.join(pack_dir, fname), content)
        if status != "unchanged":
            installed.append(f"{fname} ({status})")

    if not installed:
        return True, "Your personalized files are already up to date."
    return True, "Installed your personalized files: " + ", ".join(installed) + \
        ". Replaced files were backed up as .bak."


def self_update(pack_dir):
    """Refresh the runner code from the public repo's main branch.

    Returns a summary string. Only touches the paths in UPDATE_FILES plus
    add-only skills; buyer personalization, memory, .env, brand, sessions,
    data, and artifacts are never written.
    """
    try:
        blob = _http_get_bytes(UPDATE_ZIP_URL, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as err:
        return f"Update failed: could not download the latest runner ({err})."

    names = set(zf.namelist())
    updated, added, unchanged, skipped = [], [], 0, []

    def _read_capped(member):
        # Guard against a decompression bomb: refuse a member whose declared
        # uncompressed size alone exceeds the whole-download cap.
        if zf.getinfo(member).file_size > MAX_DOWNLOAD_BYTES:
            raise ValueError("member exceeds size cap")
        return zf.read(member)

    for rel in UPDATE_FILES:
        member = UPDATE_ZIP_PREFIX + rel
        if member not in names:
            continue
        dest = os.path.join(pack_dir, rel.replace("/", os.sep))
        # UPDATE_FILES names are fixed and safe; this is defense in depth.
        if not _is_within(pack_dir, dest):
            skipped.append(rel)
            continue
        try:
            status = _install_file(dest, _read_capped(member))
        except OSError as err:
            skipped.append(f"{rel} ({err.__class__.__name__})")
            continue
        if status == "updated":
            updated.append(rel)
        elif status == "added":
            added.append(rel)
        else:
            unchanged += 1

    # Skills are add-only: new template skills install, but a skill directory
    # that already exists is the buyer's (Aletheia edits them over time) and
    # is never overwritten. Names here come straight from the zip, so every
    # destination is checked for path escape before any write.
    for member in sorted(names):
        if not member.startswith(UPDATE_ZIP_PREFIX + "skills/") or member.endswith("/"):
            continue
        rel = member[len(UPDATE_ZIP_PREFIX):]
        if ".." in rel.split("/"):
            continue
        skill_dir = rel.split("/")[1] if len(rel.split("/")) > 2 else None
        if not skill_dir:
            continue
        if os.path.isdir(os.path.join(pack_dir, "skills", skill_dir)):
            continue
        dest = os.path.join(pack_dir, rel.replace("/", os.sep))
        if not _is_within(pack_dir, dest):
            continue
        try:
            _install_file(dest, _read_capped(member))
            added.append(rel)
        except (OSError, ValueError):
            continue

    parts = []
    if updated:
        parts.append(f"updated {len(updated)}: " + ", ".join(updated))
    if added:
        parts.append(f"added {len(added)}: " + ", ".join(added))
    parts.append(f"{unchanged} already current")
    if skipped:
        parts.append(f"skipped {len(skipped)}: " + ", ".join(skipped))
    summary = "Update complete -- " + "; ".join(parts) + "."
    if updated:
        summary += " Previous versions saved as .bak. Your memory, skills you have" \
            " edited, .env, and personalized files were not touched."
    if skipped:
        summary += " Skipped files were left as they were; run `update` again or" \
            " check file permissions."
    return summary
