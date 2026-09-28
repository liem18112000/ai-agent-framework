"""F4 — back up memory as a version: snapshot memory/** to memory-backups/<version>/ + list them."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from common.admin._shared import _BACKUPS_ROOT, ROOT, _slug, _store


def _copy_blob(store, src: str, dst: str) -> int | None:
    """Copy one blob src→dst through the port (read+write); return its byte size, or None if the
    source vanished between listing and copy (concurrent delete → skip it, don't abort the snapshot).

    ponytail: read+write is uniform across GCS/in-memory and the bank blobs are small text."""
    blob = store.get_blob(src)
    if blob is None:  # ADM-05: listed then deleted mid-snapshot — skip rather than AttributeError
        return None
    data = blob.download_as_text()
    store.blob(dst).upload_from_string(data, content_type="application/octet-stream")
    return len(data.encode("utf-8"))


def backup_memory(bank, summary: str, *, now: datetime | None = None) -> str:
    """Snapshot memory/** to memory-backups/<version>/ + a MANIFEST.json (F4). pgvector is NOT copied
    (it rebuilds from the bank via pg/backfill.py). `now` is injectable for deterministic tests."""
    dt = now or datetime.now(UTC)
    version = f"{dt.strftime('%Y-%m-%dT%H-%M-%SZ')}_{_slug(summary) or 'backup'}"
    dest_root = f"{_BACKUPS_ROOT}/{version}"
    store = _store(bank)
    blob_count = 0
    byte_size = 0
    for blob in list(store.iter_blobs(f"{ROOT}/")):
        size = _copy_blob(store, blob.name, f"{dest_root}/{blob.name}")
        if size is None:  # ADM-05: concurrent delete — skip this blob, keep snapshotting the rest
            continue
        byte_size += size
        blob_count += 1
    manifest = {"datetime": dt.isoformat(), "summary": summary, "blob_count": blob_count,
                "byte_size": byte_size, "source_prefix": f"{ROOT}/"}
    store.blob(f"{dest_root}/MANIFEST.json").upload_from_string(
        json.dumps(manifest, indent=1, ensure_ascii=False), content_type="application/json")
    return (f"Backed up {blob_count} blobs ({byte_size} bytes) → {dest_root}/\n"
            f"(pgvector not copied — rebuild from the bank via pg/backfill.py.)")


def list_backups(bank) -> str:
    """Every memory-backups/*/MANIFEST.json, newest first (F4)."""
    store = _store(bank)
    manifests: list[dict] = []
    for blob in store.iter_blobs(f"{_BACKUPS_ROOT}/"):
        if not blob.name.endswith("/MANIFEST.json"):
            continue
        version = blob.name[len(_BACKUPS_ROOT) + 1: -len("/MANIFEST.json")]
        try:
            m = json.loads(blob.download_as_text())
        except (ValueError, KeyError):
            continue
        m["version"] = version
        manifests.append(m)
    if not manifests:
        return "No backups yet. Create one with backup_memory(summary)."
    manifests.sort(key=lambda m: m.get("datetime", ""), reverse=True)
    head = "| version | datetime | summary | blobs | bytes |\n|---|---|---|---|---|"
    rows = [f"| {m['version']} | {m.get('datetime', '-')} | {m.get('summary', '-')} | "
            f"{m.get('blob_count', 0)} | {m.get('byte_size', 0)} |" for m in manifests]
    return f"# Backups ({len(manifests)})\n\n{head}\n" + "\n".join(rows)
