"""Acquire a repo's source tree for graphify — gitless (Bitbucket tarball) or a local clone."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import httpx

BITBUCKET = "https://bitbucket.org"
BITBUCKET_API = "https://api.bitbucket.org/2.0"

_MAX_TARBALL_BYTES = 200 * 1024 * 1024        # compressed download cap
_MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024   # total uncompressed cap (decompression-bomb guard)
_MAX_MEMBERS = 100_000                         # member-count cap


def _local_commit(repo_dir: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "local"


def acquire_repo(
    ws: str, repo: str, ref: str | None, dest: Path,
    *, bb_auth: tuple[str, str] | None = None, local_root: Path | None = None, timeout: float = 120.0,
) -> tuple[Path, str]:
    """Return ``(source_dir, commit)`` for ``<ws>/<repo>``."""
    if local_root:
        local = Path(local_root) / repo
        if local.is_dir():
            return local, _local_commit(local)

    dest.mkdir(parents=True, exist_ok=True)
    tar_path = dest / f"{repo}.tar.gz"
    auth = httpx.BasicAuth(*bb_auth) if bb_auth else None
    with httpx.Client(auth=auth, follow_redirects=True, timeout=timeout) as http:
        if not ref:
            meta = http.get(f"{BITBUCKET_API}/repositories/{ws}/{repo}")
            meta.raise_for_status()
            ref = (meta.json().get("mainbranch") or {}).get("name") or "master"
        # stream the tarball with a compressed-size cap (don't buffer a whole repo in RAM).
        total = 0
        with http.stream("GET", f"{BITBUCKET}/{ws}/{repo}/get/{ref}.tar.gz") as tar, tar_path.open("wb") as fh:
            tar.raise_for_status()
            for chunk in tar.iter_bytes():
                total += len(chunk)
                if total > _MAX_TARBALL_BYTES:
                    raise ValueError(f"tarball exceeds {_MAX_TARBALL_BYTES} bytes: {ws}/{repo}")
                fh.write(chunk)

    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()  # one scan — drives top-dir, the caps, and extractall (CLD-04)
        top = members[0].name.split("/")[0] if members else ""
        if len(members) > _MAX_MEMBERS:
            raise ValueError(f"tarball has too many members ({len(members)} > {_MAX_MEMBERS}): {ws}/{repo}")
        extracted = sum(m.size for m in members)
        if extracted > _MAX_EXTRACT_BYTES:
            raise ValueError(f"tarball extracts to > {_MAX_EXTRACT_BYTES} bytes: {ws}/{repo}")
        tf.extractall(dest, members=members, filter="data")  # zip-slip mitigated by filter="data"
    tar_path.unlink(missing_ok=True)
    src = dest / top
    commit = top.rsplit("-", 1)[-1] if "-" in top else (ref or "head")
    return src, commit
