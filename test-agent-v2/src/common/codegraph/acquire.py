"""Acquire a repo's source tree for graphify — gitless (Bitbucket tarball) or a local clone."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import httpx

BITBUCKET = "https://bitbucket.org"
BITBUCKET_API = "https://api.bitbucket.org/2.0"


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

    auth = httpx.BasicAuth(*bb_auth) if bb_auth else None
    with httpx.Client(auth=auth, follow_redirects=True, timeout=timeout) as http:
        if not ref:
            meta = http.get(f"{BITBUCKET_API}/repositories/{ws}/{repo}")
            meta.raise_for_status()
            ref = (meta.json().get("mainbranch") or {}).get("name") or "master"
        tar = http.get(f"{BITBUCKET}/{ws}/{repo}/get/{ref}.tar.gz")
        tar.raise_for_status()

    dest.mkdir(parents=True, exist_ok=True)
    tar_path = dest / f"{repo}.tar.gz"
    tar_path.write_bytes(tar.content)
    with tarfile.open(tar_path, "r:gz") as tf:
        top = tf.getnames()[0].split("/")[0] if tf.getnames() else ""
        tf.extractall(dest, filter="data")
    tar_path.unlink(missing_ok=True)
    src = dest / top
    commit = top.rsplit("-", 1)[-1] if "-" in top else (ref or "head")
    return src, commit
