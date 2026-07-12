"""Network sync for Aletheia -- pack fetch on unlock, runner self-update.

Two jobs, both stdlib-only (urllib + zipfile + hashlib), both conservative
about what they touch on disk:

- fetch_pack(): asks the Yardstick delivery service for the buyer's
  personalized pack (ALETHEIA.md, audit-data.json, START-HERE.md,
  CHOOSE-YOUR-MODEL.md) and installs those files beside the runner.
  It never installs code -- the runner does not modify itself here.

- self_update(): downloads a cut GitHub Release of the runner (not the
  moving main branch) and refreshes the runner code (aletheia.py,
  _backends/, _artifacts.py, _eval.py, this file, examples). Every file it
  installs is verified byte-for-byte against the release's SHA256SUMS before
  it is written. It never touches the buyer's personalization, memory, skills
  they have edited, .env, brand, sessions, or data.

What the SHA256SUMS check does and does not buy: it is an INTEGRITY control.
It pins the runner to a reviewed, tagged release (not whatever happens to be
on main this second) and proves the bytes we install match the bytes that
release published -- so a corrupted download or a file swapped in transit is
refused. It is NOT cryptographic authenticity: the checksums are fetched from
the same GitHub origin over the same TLS channel as the zip, so a compromise
of the repo or the publishing account could ship a matching zip + SHA256SUMS
pair and this check would pass. Real authenticity needs a signature verified
against a key we trust, and the stdlib has no signature-verification
primitive. The runner is deliberately stdlib-only (urllib + zipfile +
hashlib), so we do not claim more than integrity here.
"""

import hashlib
import io
import json
import os
import ssl
import urllib.error
import urllib.request
import zipfile

UNLOCK_ENDPOINT = "https://api.yardstickresearch.app/aletheia/unlock"

# Self-update pulls a cut GitHub Release, not the moving main branch. These are
# GitHub's stable "latest release" redirects, so they always resolve to the most
# recent published (non-draft, non-prerelease) release's assets.
UPDATE_ZIP_URL = "https://github.com/ConnorYQueen/yardstick-aletheia/releases/latest/download/aletheia-runner.zip"
UPDATE_SUMS_URL = "https://github.com/ConnorYQueen/yardstick-aletheia/releases/latest/download/SHA256SUMS"

MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024  # both the pack and the runner zip are far smaller

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


def _read_member_capped(zf, member):
    """Read one zip member, aborting if its ACTUAL decompressed size exceeds the
    cap. The uncompressed size recorded in the zip header is attacker-controlled,
    so it is used only as a fast first reject -- never trusted as the real size.
    The real defense is streaming the member and stopping the moment the bytes we
    have actually decompressed pass the cap, so a member that lies about its size
    (a decompression bomb) cannot force an unbounded read into memory."""
    if zf.getinfo(member).file_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("member exceeds size cap")
    out = io.BytesIO()
    with zf.open(member) as src:
        while True:
            chunk = src.read(65536)
            if not chunk:
                break
            out.write(chunk)
            if out.tell() > MAX_DOWNLOAD_BYTES:
                raise ValueError("member exceeds size cap")
    return out.getvalue()


def _is_within(base, target):
    """True if target resolves to base itself or a path underneath it. Used to
    refuse any zip-supplied name that would escape the pack directory."""
    base_abs = os.path.abspath(base)
    target_abs = os.path.abspath(target)
    return target_abs == base_abs or target_abs.startswith(base_abs + os.sep)


def _parse_sha256sums(text):
    """Parse a standard sha256sum manifest into {path: hexdigest}.

    Each line is `<64-hex sha256><whitespace><path>`; paths are forward-slash,
    relative to the zip root, no zip prefix directory. A leading `*` marker
    (sha256sum's binary-mode flag) on the path is tolerated. Malformed lines and
    bad-length digests are skipped rather than trusted.
    """
    sums = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, path = parts[0].lower(), parts[1].strip()
        if path.startswith("*"):
            path = path[1:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            continue
        sums[path] = digest
    return sums


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
        try:
            content = _read_member_capped(zf, fname)
        except (OSError, ValueError):
            continue
        status = _install_file(os.path.join(pack_dir, fname), content)
        if status != "unchanged":
            installed.append(f"{fname} ({status})")

    if not installed:
        return True, "Your personalized files are already up to date."
    return True, "Installed your personalized files: " + ", ".join(installed) + \
        ". Replaced files were backed up as .bak."


def self_update(pack_dir):
    """Refresh the runner code from a cut GitHub Release, integrity-verified.

    Downloads the release's aletheia-runner.zip plus its SHA256SUMS manifest,
    and installs only the members whose bytes match the manifest. A member
    whose path is absent from SHA256SUMS, or whose sha256 does not match, is
    refused (skipped and recorded) -- one bad file never aborts the rest.

    This is INTEGRITY, not authenticity: it proves the installed bytes match
    what the tagged release published and pins us to a reviewed release, but it
    cannot detect a repo/account compromise that ships a matching zip +
    SHA256SUMS pair over the same TLS origin (the stdlib has no signature
    verification). See the module docstring.

    Returns a summary string. Only touches the paths in UPDATE_FILES plus
    add-only skills; buyer personalization, memory, .env, brand, sessions,
    data, and artifacts are never written.
    """
    # Fetch the checksum manifest first. No manifest -> we cannot verify
    # anything, so install nothing and fail safe.
    try:
        sums_text = _http_get_bytes(UPDATE_SUMS_URL, timeout=60).decode("utf-8", "replace")
    except Exception:
        return ("Update failed: could not fetch the release checksums, so nothing"
                " was changed. Check your connection and run `update` again, or"
                " email hello@yardstickresearch.app.")
    sums = _parse_sha256sums(sums_text)
    if not sums:
        return ("Update failed: the release checksums were unreadable, so nothing"
                " was changed. Run `update` again in a minute, or email"
                " hello@yardstickresearch.app.")

    try:
        blob = _http_get_bytes(UPDATE_ZIP_URL, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        return ("Update failed: could not download the latest runner, so nothing"
                " was changed. Run `update` again in a minute, or email"
                " hello@yardstickresearch.app.")

    names = set(zf.namelist())
    updated, added, unchanged, skipped = [], [], 0, []

    def _verified(rel, content):
        # Integrity gate: the member's path must be listed in SHA256SUMS and
        # its bytes must hash to the listed digest. Refuse otherwise.
        expected = sums.get(rel)
        if expected is None:
            return False
        return hashlib.sha256(content).hexdigest() == expected

    # The release zip has NO top-level prefix directory: members are named by
    # their repo-relative path directly, matching the SHA256SUMS paths.
    for rel in UPDATE_FILES:
        if rel not in names:
            continue
        dest = os.path.join(pack_dir, rel.replace("/", os.sep))
        # UPDATE_FILES names are fixed and safe; this is defense in depth.
        if not _is_within(pack_dir, dest):
            skipped.append(rel)
            continue
        try:
            content = _read_member_capped(zf, rel)
        except (OSError, ValueError):
            skipped.append(rel)
            continue
        if not _verified(rel, content):
            skipped.append(f"{rel} (failed verification)")
            continue
        try:
            status = _install_file(dest, content)
        except OSError:
            skipped.append(rel)
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
    # destination is checked for path escape AND against SHA256SUMS before any
    # write.
    for member in sorted(names):
        if not member.startswith("skills/") or member.endswith("/"):
            continue
        rel = member
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
            content = _read_member_capped(zf, rel)
        except (OSError, ValueError):
            continue
        if not _verified(rel, content):
            skipped.append(f"{rel} (failed verification)")
            continue
        try:
            _install_file(dest, content)
            added.append(rel)
        except OSError:
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
            " email hello@yardstickresearch.app if it keeps happening."
    return summary
