# Large Dataset & Multi-user Support Design

**Date:** 2026-04-06
**Project:** BA Review App (AssociateIQ)
**Status:** Approved

## Overview

The app currently loads the entire `import_merge_matches` table into a pandas DataFrame in memory on startup (`SELECT *`). This works at 30K rows but fails at the target scale of up to 2 million BAs and addresses. This design replaces the monolithic in-memory cache with a hybrid hot-cache + SQL-fallback architecture, and adds lightweight multi-user support via browser UUID identity.

## Goals

- Support datasets up to 2 million rows without excessive memory usage
- Keep the UI feeling fast for the common case (reviewer working within one bucket)
- Allow 2–5 concurrent users without collisions on shared state
- Record who made each change in the audit log
- No login/auth infrastructure required

## Architecture

### Data Layer

**Two operating modes, selected automatically:**

**Mode 1 — Hot cache (pandas, in-memory)**

- Holds one "working set": all rows for a single `recommendation` bucket (e.g., `REVIEW`)
- Maximum size: 100K rows. If the bucket exceeds this, falls back to SQL mode automatically
- Cache metadata tracked: active bucket name, load timestamp, total row count for that bucket
- TTL: 5 minutes. After expiry, next request triggers a background refresh
- Cache swap: selecting a new bucket evicts the old cache and loads the new one. One shared cache means all users experience the swap simultaneously — acceptable for small teams (2–5 users)

**Mode 2 — SQL fallback (Snowflake direct)**

Triggered when:
- Active bucket has > 100K rows
- A filter spans multiple buckets
- Global text search is requested (ILIKE across columns)
- Cache is mid-refresh

Implementation:
- Existing filter params (`recommendation`, `ssn_match`, score ranges, search text) are translated into SQL `WHERE` clauses
- Sorting → `ORDER BY [col] ASC|DESC`
- Pagination → `LIMIT [length] OFFSET [start]`
- Record counts always use `SELECT COUNT(*)` — cheap and accurate regardless of mode

**Writes**

- `_pending_changes` global dict is removed entirely
- Every Save (single record or bulk approve) writes immediately to Snowflake via the existing `merge_changes_to_snowflake()` function
- After a save, the hot cache row is updated in-place — no full reload needed
- "Save All Changes" button and unsaved-changes counter are removed from the UI

**Connection handling**

- Existing single persistent `_sf_conn` is sufficient for 2–5 users with Flask's default threading
- A `threading.Lock` wraps connection checkout to prevent concurrent access issues
- For higher concurrency: a simple pool of 2–4 connections using the Snowflake connector's built-in support

### Multi-user & User Identity

**Identity (no login required)**

- On first visit, server sets a `user_id` cookie: a UUID (e.g., `a3f8c1d2`). Persists across browser sessions.
- A dismissible first-visit banner prompts the user to set a display name: "You're reviewing as Guest. [Set your name]"
- Display name stored in a `user_name` cookie. If skipped, defaults to first 8 chars of UUID.
- Name shown unobtrusively in the top navigation bar

**Conflict resolution: last write wins**

- No record locking. Multiple users can open the same record simultaneously.
- When two users save the same record, the later save wins via Snowflake `MERGE` overwrite.
- The audit log provides the paper trail for any disputes.

**Audit trail**

- `UPDATE_LOG` table gains two new columns: `user_id VARCHAR` and `user_name VARCHAR`
- Every save stamps both values
- Existing saves without a user_id record `NULL` (backward compatible)

### Frontend & UX

**Bucket switcher**

- Existing recommendation filter buttons (`REVIEW`, `AUTO_MERGE`, `NO_MATCH`, `APPROVED`) become the primary bucket selector
- Each button shows a live record count: `REVIEW (4,821)` — from a lightweight `COUNT(*)` per bucket on page load, refreshed every 5 minutes
- Selecting a bucket triggers a cache load with a loading spinner/banner: "Loading REVIEW records…"

**Mode indicator**

- A subtle badge in the toolbar shows current mode: `Cached` (hot cache active) or `Live query` (SQL fallback)
- Sets user expectation for page-flip speed

**Save UX (immediate writes)**

- Single record edit: Save button in modal writes immediately, shows spinner, closes on success, displays a brief "Saved" toast
- Bulk approve: fires immediately with a progress indicator
- "Save All Changes" button removed (no longer needed)

**Cache refresh**

- "Refresh" toolbar button forces an immediate reload of the current bucket cache
- Auto-refresh every 5 minutes in the background; bucket counts update silently

## Data Flow

```
User selects bucket (e.g., REVIEW)
  → Server checks: is REVIEW already cached?
      YES and fresh → return pandas filtered slice
      YES but stale → trigger background refresh via threading.Thread (fire-and-forget), serve stale data with "Refreshing..." indicator
      NO → load from Snowflake (up to 100K rows), cache it, serve result
      Bucket > 100K → SQL mode: build WHERE clause, query Snowflake directly

User applies filter within cached bucket
  → pandas mask on hot cache (fast, in-memory)

User applies global text search or cross-bucket filter
  → SQL mode: ILIKE query to Snowflake

User saves a record
  → merge_changes_to_snowflake() immediately
  → update hot cache row in-place
  → stamp UPDATE_LOG with user_id, user_name
  → show "Saved" toast
```

## Files Affected

| File | Change |
|------|--------|
| `data_loader.py` | Add `load_bucket()`, `query_snowflake_page()`, `get_bucket_counts()` functions; add connection lock |
| `app.py` | Replace `load_cached_data()` with bucket-aware cache logic; remove `_pending_changes`; add `/api/set-username` endpoint; stamp user_id/user_name on saves |
| `templates/index.html` | Add user identity banner, username modal, mode badge, bucket count badges, remove Save All button |
| `static/js/app.js` | Update save flow (immediate write), bucket switcher logic, loading indicators, toast notifications |
| Snowflake `UPDATE_LOG` | Add `user_id` and `user_name` columns (migration on startup via `ensure_snowflake_schema`) |

## Non-goals

- User authentication / passwords / role-based access
- Record locking or conflict detection UI
- Per-user isolated caches (one shared cache is sufficient for 2–5 users)
- Support for datasets beyond 2 million rows (out of scope for this iteration)
