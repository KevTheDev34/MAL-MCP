# Title Resolver

Phase 5 provides deterministic title resolution: a user-supplied anime or manga
title becomes one high-confidence `ResolvedMedia`, a small ambiguous candidate
set, or a typed not-found outcome.

The resolver searches MAL and may read list membership for scoring. It **never**
writes to MAL.

## Architecture

```text
Raw user title
    ↓
Normalization + hint extraction
    ↓
Optional user alias lookup
    ↓
Bounded MAL search (anime and/or manga)
    ↓
Dedupe by (media_type, mal_id)
    ↓
Enrich top candidates (details + on-list flag)
    ↓
Deterministic scoring + confidence policy
    ↓
Resolved | Ambiguous | NotFound
```

| Module | Role |
|---|---|
| `backend/app/resolver/normalize.py` | Comparison and search normalization |
| `backend/app/resolver/hints.py` | Year / season / format / media-type hints |
| `backend/app/resolver/search.py` | Search variants, dedupe, enrichment helpers |
| `backend/app/resolver/scoring.py` | Pure score and confidence functions |
| `backend/app/resolver/policy.py` | Limits and thresholds |
| `backend/app/resolver/aliases.py` | Alias service |
| `backend/app/resolver/service.py` | `TitleResolver` orchestration |
| `backend/app/resolver/models.py` | Request, candidate, and outcome models |

Dependency direction:

```text
resolver → mal.client / mal.domain_mapping / domain.* / db.repositories
resolver ↛ api routes / llm / commands / recommendations
```

## Request and outcomes

`ResolveTitleRequest` accepts `title` plus optional `media_type`, `release_year`,
`season_number`, `media_format`, and `allow_aliases`.

Outcomes are a discriminated union on `kind`:

- `resolved` — one `ResolvedMedia` with confidence and reasons
- `ambiguous` — up to three `ResolutionCandidate` rows
- `not_found` — no plausible match

Normal outcomes are return values. Exceptions cover auth, temporary MAL
failures, total enrichment failure, and alias store failures.

## Normalization

- `normalize_for_search` — light NFKC / whitespace / apostrophe-dash cleanup for
  MAL queries; preserves years, seasons, and numerals.
- `normalize_for_comparison` — casefold, punctuation collapse, safe `&`↔`and`,
  ordinal/roman expansion for scoring equality only.

Normalization never selects a MAL ID.

## Hint extraction

Deterministic patterns only (no LLM): trailing `anime`/`manga`, years
`1900–2100`, `season N`, compact `sN`, roman season suffixes, `movie N`,
`part N`, and format words. Explicit request fields override extracted hints.
Hints narrow scoring; they do not rewrite MAL metadata.

## MAL search strategy

1. Build at most two distinct search strings (original / remaining / abbreviation
   expansion).
2. Search anime only, manga only, or both when media type is unspecified.
3. Default limit 10 results per call.
4. Deduplicate by `(media_type, mal_id)`.

**Maximum search calls:** `2 query variants × (1 or 2 media types) = 2 or 4`.

Anime is never preferred merely because MAL ranks it higher. Cross-type
collisions remain ambiguous unless an explicit media-type hint resolves them.

## Candidate enrichment

After a cheap pre-score, enrich the top 5 candidates (configurable) via:

- `MalClient.get_anime_resolution_context` / `get_manga_resolution_context`

Each call returns details **and** an on-list flag in one GET (unlike
`get_*_list_entry`, which returns `None` when not on the list and drops details).

Default total MAL GET budget (search + enrich + alias validate): **10**.

## Scoring and confidence

Transparent weights (alias +50, exact canonical +40, year ±15/20, season ±15/25,
format / anime-manga / movie-TV conflicts, weak +5 list bonus). Reasons and
penalties are recorded as stable string codes.

Confidence combines absolute score and runner-up margin:

```text
abs_conf = clamp(top_score / 55, 0, 1)
margin_factor = clamp((top - second) / 25, 0, 1)
confidence = abs_conf * (0.55 + 0.45 * margin_factor)
```

Default resolve rules:

- Resolved when confidence ≥ 0.90, margin ≥ 20, and raw score ≥ 40
- Resolved when there is a sole candidate with raw score ≥ 40
- Ambiguous when raw score ≥ 25 but resolve rules fail (max 3 candidates)
- Not found when no candidate clears raw score ≥ 25 (or only a single weak hit)

Popularity is unused. Tie-break is stable `(score, media_type, mal_id)` for
ordering only.

## Existing-list signal

Included as a weak +5 during enrichment when the title is already on the user's
list. Implemented with per-ID resolution-context GETs — never a full-list scan.
Lookup failures skip the bonus and do not fail resolution.

## Aliases

Table `title_aliases` (migration `0003_title_aliases`):

- Unique `(user_id, alias_normalized, media_type)` — `media_type` is required
- Fields: `mal_id`, `canonical_title`, `created_at`, `last_used_at`

Behavior:

1. Lookup before search when `allow_aliases` and `user_id` are set
2. Validate target still exists on MAL
3. Treat as a strong signal (+50), not an unconditional bypass
4. Ignore aliases that conflict with explicit type/year/format hints
5. Update `last_used_at` on successful alias-assisted resolve
6. Do not auto-create aliases from every resolve
7. `TitleResolver.save_alias` for later clarification flows

## Diagnostic script

```bash
python scripts/resolve_title.py "Steins;Gate"
python scripts/resolve_title.py "Hunter x Hunter"
python scripts/resolve_title.py "Hunter x Hunter 2011"
python scripts/resolve_title.py "Pluto"
python scripts/resolve_title.py "Pluto" --media manga
python scripts/resolve_title.py "Vinland Saga season 2"
```

Requires a connected MAL account. Prints hints, outcome, scores, and reasons.
Does not update MAL or print credentials.

## Known limitations

- No MAL relationship graph (`related_anime` / `related_manga`); season/remake
  disambiguation uses title text, year, format, and totals
- No popularity signal
- Season numbers are inferred from title strings, not structured MAL fields
- No process-wide cache (request-local memoization only if needed)
- No public HTTP resolve endpoint in Phase 5

## Intentionally not implemented

- Change plans, confirmation, apply, verification, audit, undo
- LLM / OpenAI integration and chat UI
- Full list synchronization / Redis
- Recommendations
- Automatic alias creation from every successful resolve
