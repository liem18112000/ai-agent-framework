"""Tier-6/7 cloud service fetcher (roadmap X3/X4) — read a service's logs over an EXPANDING window,
distil (redacted) into a Note, and emit its communication edges as LinkRecords. Provider-neutral: the
reach is the `CloudProvider` port (selected by the id's `<provider>` segment); the expanding-window
loop, "enough" gate, redaction, edge-derivation + grounding gate, and no-silent-caps stay here.

A `NodeFetcher(kind="cloudsvc")`, so the unchanged crawl fetches + follows it like any other node. The
provider's `read_logs` is SYNC and wrapped in `asyncio.to_thread` (serial blocking calls once blew
Cloud Run's liveness). Log bodies carry secrets/PII, so everything persisted is REDACTED — signatures
and counts, never raw payloads."""

from __future__ import annotations

import asyncio
import re

from common.cloud import K8S, LogEntry, ServiceRef, cloud_providers, cloud_windows
from common.models import CLOUD_EDGE, CLOUD_SERVICE, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher
from knowledge_gathering.monitoring import get_logger

log = get_logger("crawl.fetch.cloud")

_MAX_ENTRIES = 2000          # per-window cap (matches the org skills' LIMIT)
_MIN_SEVERITY = "WARNING"    # default severity floor (widening to all severities = future refinement)
_ENOUGH_ERROR_SIGS = 3       # ≥k distinct error signatures …
_ENOUGH_DEPS = 2             # … OR ≥m outbound dependency edges …
_ENOUGH_ENTRIES = 50         # … OR ≥n in-scope entries → window is "enough"
_TOP_ROUTES = 5
_TOP_SIGS = 8

# Patchable seam for tests: a test injects a {name: FakeCloudProvider} registry here.
_providers = cloud_providers


# --- redaction (mandatory, security — strip before anything is persisted) -------------------------
_REDACT_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),                              # emails (PII)
    re.compile(r"[a-z][a-z0-9+.-]*://[^\s:@/]+:[^\s:@/]+@", re.IGNORECASE),   # creds in a URL/DSN
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|bearer)"
               r"\b\s*[:=]?\s*\S+"),                                          # key=value secrets
    re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),                                   # long opaque tokens/keys
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://\S+"),  # DSNs
)


def _redact(text: str) -> str:
    """Replace secret/PII/connection-string spans with `[REDACTED]`, keeping the surrounding signature."""
    out = text or ""
    for pat in _REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


# --- signal model + "enough" gate ----------------------------------------------------------------
class _Signal:
    def __init__(self) -> None:
        self.error_sigs: dict[str, int] = {}
        self.routes: dict[str, int] = {}
        self.deps: set[str] = set()
        self.total = 0

    def brief(self) -> str:
        return f"{len(self.error_sigs)} sigs / {len(self.deps)} deps / {self.total} entries"


_ERROR_SEVERITIES = {"ERROR", "CRITICAL", "ALERT", "EMERGENCY", "WARNING"}
_NORM = re.compile(r"\b(?:0x[0-9a-f]+|[0-9a-f]{8,}|\d+)\b", re.IGNORECASE)  # ids/hex/nums → placeholder


def _signature(message: str) -> str:
    """Dedup key for an error line: redact, then blank out ids/numbers so near-identical stack traces
    (2000 of them) collapse to one signature."""
    return _NORM.sub("#", _redact(message)).strip()[:200]


def _summarize(entries: list[LogEntry]) -> _Signal:
    sig = _Signal()
    sig.total = len(entries)
    for e in entries:
        msg = e.message or ""
        is_error = (e.severity or "").upper() in _ERROR_SEVERITIES or "error" in msg.lower() or "exception" in msg.lower()
        if is_error and (key := _signature(msg)):
            sig.error_sigs[key] = sig.error_sigs.get(key, 0) + 1
        if route := (e.route or "").strip():
            sig.routes[route] = sig.routes.get(route, 0) + 1
        if host := (e.outbound_host or "").strip():
            sig.deps.add(host)
    return sig


def _enough(sig: _Signal) -> bool:
    return (len(sig.error_sigs) >= _ENOUGH_ERROR_SIGS
            or len(sig.deps) >= _ENOUGH_DEPS
            or sig.total >= _ENOUGH_ENTRIES)


# --- Tier 7: edges (grounding gate — a real target resource, else demoted to unconfirmed) ----------
def _resolve_target(host: str, provider: str, env: str) -> tuple[str, bool]:
    """Map an outbound host to a graph target. k8s cluster-DNS (`name.namespace.svc.cluster.local`,
    neutral across GKE/EKS/AKS) resolves to a fetchable `cloudsvc:` node (grounded, in_scope). Anything
    else is an external host we can't resolve to a service resource → recorded-only `cloudext:` edge
    (unconfirmed, in_scope=False). Provider-specific hostname shapes (e.g. *.run.app) are a future
    per-adapter hook; until then they demote safely."""
    h = (host or "").strip().lower().rstrip(".")
    if h.endswith(".svc.cluster.local"):
        return f"cloudsvc:{provider}/{env}/{K8S}/{h.split('.')[0]}", True
    return f"cloudext:{h}", False


def _edges(nid: str, deps: set[str], provider: str, env: str) -> list[LinkRecord]:
    """One LinkRecord per distinct outbound host — grounded edges in-scope (crawl walks them),
    unconfirmed ones recorded-only (in_scope=False). The LLM may label but never create an edge."""
    out: list[LinkRecord] = []
    seen: set[str] = set()
    for host in sorted(deps):
        target, grounded = _resolve_target(host, provider, env)
        if target in seen or target == nid:
            continue
        seen.add(target)
        out.append(LinkRecord(source_id=nid, url=host, type=CLOUD_EDGE, origin="cloud-log",
                              canonical_url=target, in_scope=grounded))
    return out


# --- Tier 6: distill ------------------------------------------------------------------------------
def _synopsis(sig: _Signal, days: int, shortfall: bool) -> str:
    """Distil the window into a compact, REDACTED synopsis: purpose · health · deps · provenance."""
    top_routes = sorted(sig.routes.items(), key=lambda kv: -kv[1])[:_TOP_ROUTES]
    top_sigs = sorted(sig.error_sigs.items(), key=lambda kv: -kv[1])[:_TOP_SIGS]
    lines = [
        f"Purpose: {', '.join(_redact(r) for r, _ in top_routes) or '(no routes seen)'}",
        f"Health: {'; '.join(f'{s} (x{c})' for s, c in top_sigs) or 'no error signatures'}",
        f"Deps: {', '.join(_redact(h) for h in sorted(sig.deps)) or '(none seen)'}",
        f"[window: {days}d; entries: {sig.total}]",
    ]
    if shortfall:
        lines.append(f"[SHORTFALL: {days}d window still under the 'enough' gate — {sig.brief()}]")
    return "\n".join(lines)


def _parse_ident(ident: str) -> tuple[str, str, str, str]:
    parts = ident.split("/", 3)
    if len(parts) != 4 or not all(parts):
        raise ValueError(f"malformed cloudsvc id (want provider/env/platform/name): {ident!r}")
    return parts[0], parts[1], parts[2], parts[3]


class CloudServiceFetcher(NodeFetcher):
    """`cloudsvc:<provider>/<env>/<platform>/<name>` — Tier 6 (expanding-window logs) + Tier 7 (edges)."""

    kind = "cloudsvc"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        provider_name, env, platform, name = _parse_ident(ident)
        provider = _providers().get(provider_name)
        if provider is None or not provider.is_configured():
            raise RuntimeError(f"cloud provider not configured for {nid} (provider={provider_name})")

        ref = ServiceRef(provider=provider_name, env=env, platform=platform, name=name)
        windows = cloud_windows()
        sig, used_days, shortfall = _Signal(), windows[-1] if windows else 28, True
        for days in windows:
            entries = await asyncio.to_thread(
                provider.read_logs, ref, days, cap=_MAX_ENTRIES, min_severity=_MIN_SEVERITY)
            sig, used_days = _summarize(entries), days
            if _enough(sig):
                shortfall = False
                break
            log.info("cloudsvc %s: %dd window insufficient (%s) — widening", nid, days, sig.brief())
        if shortfall:  # 28d cap reached without enough signal — surfaced, never silent
            log.warning("cloudsvc %s: %dd cap reached, still insufficient (%s) — recording shortfall",
                        nid, used_days, sig.brief())

        note = Note(id=nid, type=CLOUD_SERVICE, title=f"{name} ({provider_name}/{env}/{platform})",
                    source_url=ref.resource_path, synopsis=_synopsis(sig, used_days, shortfall))
        edges = _edges(nid, sig.deps, provider_name, env)
        note.links = edges
        return edges, note, ""  # empty body: nothing raw persisted (synopsis is already redacted)
