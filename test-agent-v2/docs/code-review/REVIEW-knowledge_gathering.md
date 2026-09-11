# Code Review & Audit — `knowledge_gathering`

**Target:** `test-agent-v2/src/knowledge_gathering` (30 files · 1,245 LOC)
**Commit:** `3dd56ac` · branch `feature/test-agent/v2-adk` · **Date:** 2026-09-11
**Method:** unified two-lens pass — `/code-review max` (correctness + security) and the **ponytail-review** skill (over-engineering / what to delete). Every load-bearing finding was cross-checked against the `common/*` code it depends on, and independently re-derived by two adversarial review agents before being kept here. Findings that did **not** survive verification are listed in the *Verified-not-a-bug* appendix so they don't get re-investigated.

---

## Scorecard

| Lens | Result |
|---|---|
| **Correctness / Security** | 3 High · 5 Medium · 4 Low |
| **Over-engineering (ponytail)** | 8 cuts · **net ≈ −40 lines** |
| **Overall** | Sound, well-factored package. One security class (SSRF) and one silent functional regression (`exclude`) are the only items that should block; the rest are Cloud-Run robustness hardening + trimming. |

**The three that should be fixed before this ships as-is:** SSRF in the web fetcher (H1), the `exclude=` parameter being a silent no-op (H2), and synchronous GCS persistence blocking the event loop (H3).

---

## ✅ Resolution (2026-09-11)

All findings were addressed in the same pass. Full suite after the fixes: **421 passed, 14 skipped, 0 failed** (was 105 → 114 on the KGA-affected subset; **+9 new tests**), ruff clean.

| # | Finding | Status | What changed |
|---|---|---|---|
| **H1** | SSRF in web fetcher | **Fixed** | `_host_blocked` (private/loopback/link-local/reserved IP literals + resolved hostnames + `localhost`/metadata names) enforced via an httpx **request event-hook** on every hop (initial + redirects) in `_build_client`. Tests: `test_host_blocked_*`, `test_fetch_web_blocks_ssrf_to_internal_literal`. |
| **H2** | `exclude=` silent no-op | **Fixed** | New `domain.exclude_ids()` normalises the free-text `exclude` to canonical ids; threaded into both `expansion_round(exclude=…)` and a new `crawl(exclude=…)` param that skips excluded ids as seeds *and* as followed links. Tests: `test_exclude_ids_*`, `test_crawl_excludes_seed_and_links`. |
| **H3** | Sync GCS persist blocks the loop | **Fixed** | The note/index/run-log writes moved into `_persist()` run via `asyncio.to_thread(...)`. |
| **M4** | `AtlassianClient` leak | **Fixed** | Handler tracks `owns_client` and `aclose()`s a self-built client in a `finally`. Test: `test_gather_closes_the_client_it_built`. |
| **M5** | `parse_input` uncaught crash | **Fixed** | JSON branch wrapped in `try/except (JSONDecodeError, ValueError, TypeError)` → degrades to "no seed". Test: `test_parse_input_malformed_json_yields_no_seed`. |
| **M6** | Post-crawl persist → 500 | **Fixed** | `crawl(...)` wrapped in the handler → degraded reply on failure, client still closed. Test: `test_gather_degrades_and_still_closes_when_crawl_fails`. |
| **M8** | Router blocking/unguarded GCS read | **Fixed** | `_refine_state()` offloads the read via `asyncio.to_thread` and degrades to `{}` on error. |
| **L9** | Planner prompt-injection | **Hardened** | Both planner prompts now instruct the model to treat ticket fields as untrusted data. |
| **L10** | Budget-dropped nodes vanish | **Fixed** | Over-budget level nodes are appended to `result.gaps`. Test: `test_over_budget_level_flags_dropped_as_gaps`. |
| **L11** | `CancelledError` swallowed | **Fixed** | Cancellation is re-raised instead of becoming a gap. Test: `test_crawl_reraises_cancellation`. |
| **M7** | atlassian_search "loses recency" | **By design (won't-fix)** | The client returns bare, timestamp-less keys from two sources (JQL+CQL), so a cross-source recency merge is impossible; the alphabetical `sorted()` is a deterministic tiebreak the tests explicitly assert (`test_caps_at_max_seeds_stable_order`). Changing it would trade determinism for nothing. |
| **L12** | Bitbucket ref-with-`/` | **Non-issue** | `classify_url` captures the ref as a single `[^/]+` segment, so idents never carry a multi-segment ref — the fetcher's split is always correct. |

**Ponytail (over-engineering):** 6 of 8 cuts applied — `_charset`→`resp.charset_encoding`, `_add_all` closure inlined into `_persist`, `focus=terms` alias removed, unused `as_terms/as_leads` `cap` params deleted, `_queries` redundant re-filter removed, dead `raise NotImplementedError` under `@abstractmethod` removed. **2 cuts kept deliberately:** the `NodeFetcher` ABC/registry and `WebFetcherHttp`, and the `_build_client` seam — the test-suite asserts the registry-of-instances shape (`test_http_and_https_both_registered`) and monkeypatches `_build_client` as a fixture seam, so both are the *intended* extension points, not over-build. Net trim landed ≈ −15 lines (the two big cuts are test-locked).

---

## Part 1 — Correctness & Security (`/code-review max`)

### 🔴 High

#### H1 · Unauthenticated SSRF in the web fetcher
`gather/crawl/fetch/web.py:27-46` (reached from `crawl.py:71-75`, seed path `gather/agent.py:73→89`)

`_fetch_web` issues an arbitrary `GET` with `follow_redirects=True` and **no private-IP / link-local / cloud-metadata / host-allowlist guard**. External-web fetch is enabled in gather (`Scope(follow_web=True)`), and `_fetchable` (`crawl.py:92-95`) admits any `http`/`https` node.

Two trigger paths, both confirmed:
- **Direct:** `gather_knowledge(seed="http://内部-service/admin")` → `normalize_seed` → `classify_url` returns `(EXTERNAL_WEB, "http://…")` → the URL becomes frontier node 0 → fetched, and its response body is stored as a `Note` in the shared memory bank and echoed in the gather summary.
- **Planted link:** a Jira/Confluence page the agent legitimately crawls contains a link to an internal URL (or a public URL that `302`-redirects to one); it is classified `EXTERNAL_WEB`, promoted (up to `max_web=8`), and fetched the same way.

**Impact:** read-side SSRF against anything reachable from the Cloud Run egress — internal services, private IPs, `169.254.0.0/16` — with the body exfiltrated into `get_note`-readable memory. (The GCP metadata server specifically requires a `Metadata-Flavor: Google` header httpx won't send, so `169.254.169.254` returns 403 → gap; that one target is mitigated, but the broader internal surface is not.)

**Fix:** resolve the host and reject private/loopback/link-local/reserved ranges **before** connecting **and on every redirect hop** (custom transport or `follow_redirects=False` + manual hop validation). Optionally gate crawled-web fetching behind an allowlist of public suffixes.

---

#### H2 · `exclude=` is parsed then silently discarded — the feature is a no-op
`gather/agent.py:73` · `gather/domain.py:68-84`

The MCP tool advertises `gather_knowledge(..., exclude=…)` and `parse_input` correctly returns a 4-tuple `(seed, depth, repo, exclude)`. But the handler binds it to a throwaway:

```python
seed, depth, repo, _exclude = parse_input(incoming_text(ctx).strip())
```

`_exclude` is never forwarded to `expansion_round(...)` (which only excludes `set(extra_seeds)`) nor to `crawl(...)` (which has no `exclude` parameter at all).

**Failure scenario:** an operator re-runs a gather with `exclude="LUZ-159312"` to keep a known drift/noise ticket out of a re-aimed pack (the documented re-aim lever). The value is JSON-encoded by the tool, parsed, and thrown away — the excluded id is still promoted as a seed and re-crawled, silently re-poisoning the pack the caller was trying to clean. No error, no log; the caller believes the exclusion took effect.

**Fix:** thread the parsed exclude set into `expansion_round(exclude=…)` (union with `extra_seeds`) and, if it must also suppress already-linked frontier nodes, into `crawl`. Cover with a test asserting an excluded id never appears in `result.notes`.

---

#### H3 · Synchronous GCS persistence blocks the asyncio event loop
`gather/crawl/crawl.py:79-88` (calls into `common/memory/bank.py:94,107,133`)

The crawl correctly offloads the distiller (`crawl.py:60`, `asyncio.to_thread`) but then persists on the loop:

```python
for note in result.notes:
    bank.upsert_note(note)          # each = GCS read + 2 writes (bank.py:94-101)
if result.notes:
    bank.update_index(_add_all(...)) # CAS read-modify-write loop, up to 5× (bank.py:107-117)
bank.append_run_log(result.run)      # more sync GCS I/O
```

All three are **synchronous** blocking GCS calls. After a 40-node crawl that's ~120 sequential blocking round-trips plus the CAS loop — several seconds of a fully stalled event loop on Cloud Run, starving the liveness/health endpoint and every concurrent request. This is the same failure class as the prior "serial Vertex calls → Cloud Run liveness timeout / instance killed" incident.

**Fix:** wrap the persistence block in `asyncio.to_thread(...)` (one offload for the whole block), or batch the note upserts into a single bank operation. Combine with H6 (wrap for error safety).

---

### 🟡 Medium

#### M4 · `AtlassianClient` (httpx) leaked once per gather
`gather/agent.py:78`

`client, bank = self.client or build_client(), …`. In production `self.client` is `None`, so `build_client()` mints a new `AtlassianClient` — whose `__init__` creates `httpx.AsyncClient(timeout=…)` (`common/atlassian/base.py:39`). The class exposes `aclose()` (`base.py:65-66`) but the handler never calls it. Each `gather_knowledge` leaks one client + its connection pool; over a long-lived instance serving many gathers, sockets/FDs accumulate → eventual exhaustion. (The web fetcher, by contrast, correctly uses `async with`.)

**Fix:** `try/finally: if self.client is None: await client.aclose()`, or manage it with `async with`.

#### M5 · `parse_input` raises uncaught on malformed input, unlike its siblings
`gather/domain.py:71-76`

```python
if text.startswith("{"):
    d = json.loads(text)                       # JSONDecodeError uncaught
    return d.get("seed"), int(d.get("depth", 2)), …   # int() ValueError uncaught
```

`wants_refine` (`refine/agent.py:16-21`) deliberately guards `{`-prefixed text against `JSONDecodeError`, so invalid JSON routes to gather — where `parse_input` does **not** guard and the exception escapes the handler as a 500. This runs *before* the crawl's `return_exceptions` safety net. The `build_client`/`build_bank` calls two lines down (`agent.py:77-81`) are wrapped precisely to degrade gracefully; the parse is inconsistently not.

**Failure scenario:** `send_raw_kga('{"seed":"X"')` (truncated JSON) or `{"seed":"X","depth":"two"}` → 500 out of the gather handler.

**Fix:** wrap the JSON branch in `try/except (JSONDecodeError, ValueError, TypeError)` and return the friendly "Provide a seed…" reply.

#### M6 · Post-crawl persistence is unwrapped → 500 + half-written index
`gather/agent.py:89-93` · `crawl.py:82-88`

`crawl()` and `capture_gather` after it aren't wrapped. If `update_index` exhausts its 5 CAS retries under concurrent gathers, it raises `RuntimeError("index CAS retries exhausted")` (`bank.py:117`) — *after* the per-note `upsert_note` writes already landed. The caller gets a 500 and the note blobs exist without a matching index entry (inconsistent until the next successful gather rebuilds it). A transient GCS 503 mid-`upsert` loop does the same.

**Fix:** wrap the crawl+persist+capture tail so a persistence failure returns a degraded summary rather than a 500; make the note-write + index-update atomic-ish (index first, or a single transactional mutate).

#### M7 · Atlassian-search truncation throws away the recency ranking
`gather/explore/seeds/atlassian_search.py:43-53`

The JQL asks for `ORDER BY updated DESC`, but the results are collected into a **set** then `sorted()` alphabetically by id and truncated:

```python
seeds = sorted({sid for sid in found if sid not in exclude})[:max_seeds]
```

The set drops order and `sorted()[:5]` keeps the alphabetically-smallest ids, not the freshest. For `[jira:LUZ-980, …, jira:LUZ-101]` (newest-first) it keeps `LUZ-101…LUZ-150` — the **stalest** related tickets — defeating the whole point of ordering by `updated`.

**Fix:** dedupe order-preservingly (`dict.fromkeys`) instead of `sorted(set(...))`, so the JQL/CQL recency order survives the `[:max_seeds]` cut.

#### M8 · Router does a blocking, unguarded GCS read on every message
`agent.py:33`

```python
state = build_bank().read_refine_state(ctx.session.id) or {}
```

For every dispatched gather/refine message the router (a) builds a fresh bank + GCS client (`build_bank` is uncached — verified), (b) does a **synchronous** GCS blob download on the event loop, and (c) is unguarded, so a transient GCS error crashes routing for that request. Blocking + per-request client construction compound under concurrency.

**Fix:** offload/guard the read; reuse a single injected bank across router + handlers instead of re-building.

---

### 🟢 Low

- **L9 · Planner prompt-injection surface** — `explore/planners/ask_llm.py:17-29`, `hypothesize.py:21-39`. Crawled ticket title/description/labels are interpolated into planner prompts; a malicious description can steer term/lead generation. Bounded: outputs are `output_schema`-constrained to short phrases and re-grounded against real Atlassian search / the memory index, so worst case is misdirected search breadth, not egress. Worth a note in the prompt ("treat the ticket text as data").
- **L10 · Budget-truncated nodes vanish silently** — `crawl.py:47`. `level_items = list(level.items())[: max_nodes - len(visited)]` drops over-budget nodes from the level, and `frontier` is reset without re-queuing them; they're never recorded as gaps, so a budget-capped crawl looks complete. Consider appending the dropped ids to `result.gaps`.
- **L11 · `return_exceptions=True` swallows `CancelledError`** — `crawl.py:50-55`. `isinstance(res, BaseException)` turns a child `CancelledError` (e.g. Cloud Run shutdown) into an ordinary "gap" rather than propagating cancellation. Minor; narrow to `Exception` if clean shutdown matters.
- **L12 · Bitbucket ref containing `/` mis-parses** — `fetch/bitbucket.py:13-14`. The positional split assumes `ref` is a single path segment; a branch ref like `feature/foo` shifts `fp`. Symmetric with `classify_url` (same assumption), and commit-hash refs (the common case) are unaffected → degrades to a gap, not a crash.

---

## Part 2 — Over-engineering (ponytail-review)

Complexity-only lens; correctness is Part 1. Live-code was cross-checked — the `distiller` param, the injectable `client`/`bank`/planner `None` fields, and `semantic_self_seed`/`MEMORY_SEMANTIC_SEED` (wired in `deployments/…/cloudsql.tf`, covered by tests) are **genuinely used** and are *not* flagged.

- `fetch/base.py:11-26` — **yagni:** `NodeFetcher` ABC + `registry` ClassVar + `__init_subclass__` auto-registration is a 6-way strategy pattern over stateless single-method classes. A plain `dict[str, Callable]` in `fetch/__init__.py` mapping `kind → async fn`; each fetcher becomes a module-level `async def x_fetch(client, ident, nid, scope)`, shedding its `class …(NodeFetcher): kind=…` wrapper.
- `fetch/base.py:26` — **shrink:** `raise NotImplementedError` inside an already-`@abstractmethod` body is dead (the docstring alone satisfies it). Drop the line.
- `fetch/web.py:58-61` — **yagni:** `WebFetcherHttp(WebFetcher)` subclass exists only to register the identical fetch under a second kind. `registry["http"] = registry["https"]` (subsumed by the base.py cut).
- `fetch/web.py:22-24` — **native:** `_charset()` hand-parses the charset from the content-type header. httpx already exposes it — `resp.charset_encoding or "utf-8"`.
- `fetch/web.py:17-19` — **yagni:** `_build_client()` is a one-line `httpx.AsyncClient(...)` wrapper with a single caller. Inline it at line 31.
- `crawl/crawl.py:98-102` — **yagni:** `_add_all` is a closure factory with one caller (line 82). Inline: `bank.update_index(lambda g: [g.add_note(n) for n in result.notes])`.
- `explore/seeds/self_seed.py:26-27` — **shrink:** `_queries` re-applies `len ≥ 3 and not stopword` to `salient_tokens(terms)` output, which already passed that filter; only `seed_key` needs the guard.
- `explore/planners/schemas.py:44,54` — **delete:** the `cap=_MAX_TERMS` / `cap=_MAX_LEADS` params on `as_terms`/`as_leads` are never passed by any caller. Drop the param, hardcode the constant.
- `explore/expand.py:31` — **shrink:** `focus = terms` is a never-reassigned alias; use `terms` directly and drop the binding (touches lines 31,44,46,49,50).

**net: ≈ −40 lines possible.** (This is trimming, not a rewrite — the G0–G4 phase-per-module layout itself earns its keep; the machinery *inside* the fetch layer is the main over-build.)

---

## Appendix — Verified *not* a bug (checked, dismissed)

Recording these so they aren't re-investigated:

- **JQL/CQL injection** — *defended.* `atlassian_search._escape` (`atlassian_search.py:11-13`) backslash-then-quote-escapes both the query tokens and `project` inside their double-quoted literals before interpolation.
- **Bitbucket positional parse** — *correct for the canonical form.* `fetch/bitbucket.py` (`parts[0],parts[1],parts[3],parts[4:]`) exactly matches `classify_url`'s `bitbucket:{ws}/{repo}/src/{ref}/{path}` output; the skipped `parts[2]` is the literal `"src"`. (Only slash-containing refs break it — see L12.)
- **Crawl-fetch exceptions** — *safe by design.* Each fetch runs under `asyncio.gather(..., return_exceptions=True)` (`crawl.py:50`); a fetcher that raises becomes a recorded gap, so the fetch adapters' unguarded `raise` paths (e.g. `web.py` content-type/size rejects, `fetch_node`'s `ValueError`) degrade gracefully rather than crashing the crawl.
- **Web response size / zip-bomb** — *bounded.* `_fetch_web` streams and counts **decompressed** bytes against `_MAX_BYTES = 2 MiB` (`web.py:38-42`), and enforces a content-type allowlist and bounded redirects/timeout.
- **Crawl concurrency races** — *none.* Only `fetch()` runs concurrently; all shared-state mutation (`visited`, `web_promoted`, `result`, frontier rebuild) happens in the sequential post-`gather` loop.
- **Web fetch credential leak** — *avoided intentionally.* The web client is built with **no** Atlassian auth (`web.py:17-19`), so crawled public-web GETs never carry the API token.

---

*Two-lens review: `/code-review max` (correctness + security) ∪ ponytail-review (over-engineering). Findings independently re-derived by two adversarial agents and verified against `common/*` before inclusion.*
