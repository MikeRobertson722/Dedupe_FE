# Large Dataset & Multi-user Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic in-memory `SELECT *` cache with a hybrid hot-cache + SQL-fallback architecture, remove `_pending_changes` so every save writes immediately to Snowflake, and add lightweight user identity (UUID cookie + display name) stamped on every audit log entry.

**Architecture:** A `BucketCache` class holds up to 100K rows for one recommendation bucket in memory; all other queries hit Snowflake directly via parameterized SQL. Save endpoints write immediately using `save_record_immediately()` / `save_records_batch()` instead of accumulating a pending dict. A UUID cookie identifies each browser session; the display name is stored in a second cookie and stamped on `UPDATE_LOG`.

**Tech Stack:** Flask, pandas, snowflake-connector-python, Bootstrap 5, AG Grid, jQuery, pytest, unittest.mock

---

## File Map

| File | What changes |
|------|-------------|
| `data_loader.py` | Add `BucketCache`, `get_bucket_counts()`, `query_snowflake_page()`, `save_record_immediately()`, `save_records_batch()`; add `threading.Lock`; update `ensure_snowflake_schema()` and `write_audit_log_to_snowflake()` for user identity |
| `app.py` | Replace `load_cached_data()` / `_pending_changes` globals; update all save endpoints to write immediately; add `/api/bucket-counts`, `/api/cache-status`, `/api/set-username`, `/api/user-info`; remove `/api/save_changes` |
| `templates/index.html` | Add user-identity banner + modal, bucket count badges, mode badge, remove Save All button/counter |
| `static/js/app.js` | Update every save AJAX call to include `id`, `source_id`, `source_ssn`, `old_value`; remove `pendingCount` tracking; add toast helper; add bucket-count polling; add refresh button; add user-identity flow |
| `tests/unit/test_bucket_cache.py` | New — unit tests for `BucketCache` |
| `tests/unit/test_sql_builder.py` | New — unit tests for `query_snowflake_page` SQL construction |
| `tests/unit/test_save_functions.py` | New — unit tests for `save_record_immediately` and `save_records_batch` |

---

## Key Design Notes (read before starting)

- **`_row_id` switch:** Currently `_row_id` is the pandas integer index. After this change it becomes the Snowflake `id` column value in both hot-cache and SQL modes. This makes saves consistent: every `/api/update` request identifies the record by `id` (WHERE clause), `source_id`, and `source_ssn` (audit log). The frontend's `_row_id` references continue to work — they just now hold the Snowflake `id` value.
- **Hot-cache row update:** Use `cache.df.loc[cache.df['id'] == row_id, field] = value` instead of `df.at[row_id, field]`.
- **SQL mode:** When a bucket has > 100K rows, or when filters span multiple buckets, every `/api/matches` request runs a parameterized SQL query against Snowflake.
- **Immediate saves:** `_pending_changes` is removed. Every edit (single, bulk, search-replace, import-ids) writes directly to Snowflake before returning a response.
- **`/api/save_changes` becomes a no-op stub** that returns `{success: true, saved: 0}` to avoid breaking any bookmark/external integration. Frontend removes the Save All button.

---

## Task 1: Add connection lock and `tests/unit/` scaffold

**Files:**
- Modify: `data_loader.py` (top of file)
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_bucket_cache.py`

- [ ] **Step 1: Create the unit test directory**

```bash
mkdir -p /c/ClaudeMain/BA_Review_App/tests/unit
touch /c/ClaudeMain/BA_Review_App/tests/unit/__init__.py
```

- [ ] **Step 2: Write a failing test for thread-safe connection**

Create `tests/unit/test_bucket_cache.py`:

```python
"""Unit tests for BucketCache and related data_loader functions."""
import threading
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Connection lock test
# ---------------------------------------------------------------------------

def test_connection_lock_is_threading_lock():
    """data_loader._conn_lock must be a threading.Lock instance."""
    import data_loader
    assert isinstance(data_loader._conn_lock, type(threading.Lock()))
```

- [ ] **Step 3: Run to verify it fails**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_bucket_cache.py::test_connection_lock_is_threading_lock -v
```
Expected: `FAILED` — `data_loader has no attribute '_conn_lock'`

- [ ] **Step 4: Add `_conn_lock` to `data_loader.py`**

At the top of `data_loader.py`, after the existing module-level globals (`_sf_conn`, `_sf_config_hash`, `_sf_conn_verified_at`, `_SF_CONN_TTL`), add:

```python
import threading

_conn_lock = threading.Lock()
```

Then wrap the body of `get_snowflake_connection` with the lock. Replace the function's `global` block and return logic as follows (keep the existing function signature and docstring, change only the body):

```python
def get_snowflake_connection(config: Dict[str, Any]):
    """
    Get a persistent Snowflake connection, creating one only if needed.
    Reuses the same connection across all operations to avoid repeated SSO prompts.
    Skips the SELECT 1 health check if the connection was verified within _SF_CONN_TTL seconds.
    Thread-safe via _conn_lock.
    """
    global _sf_conn, _sf_config_hash, _sf_conn_verified_at

    try:
        from snowflake import connector
    except ImportError:
        raise ImportError(
            "snowflake-connector-python not installed. "
            "Install with: pip install snowflake-connector-python"
        )

    conn_params = _build_conn_params(config)
    config_hash = str(sorted(conn_params.items()))

    with _conn_lock:
        if _sf_conn is not None and _sf_config_hash == config_hash:
            if (time.time() - _sf_conn_verified_at) < _SF_CONN_TTL:
                return _sf_conn
            try:
                _sf_conn.cursor().execute("SELECT 1")
                _sf_conn_verified_at = time.time()
                return _sf_conn
            except Exception:
                try:
                    _sf_conn.close()
                except Exception:
                    pass
                _sf_conn = None

        _sf_conn = connector.connect(**conn_params)
        _sf_config_hash = config_hash
        _sf_conn_verified_at = time.time()
        return _sf_conn
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_bucket_cache.py::test_connection_lock_is_threading_lock -v
```
Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add data_loader.py tests/unit/__init__.py tests/unit/test_bucket_cache.py
git commit -m "feat: add threading.Lock to Snowflake connection for multi-user safety"
```

---

## Task 2: Add `BucketCache` class to `data_loader.py`

**Files:**
- Modify: `data_loader.py`
- Modify: `tests/unit/test_bucket_cache.py`

- [ ] **Step 1: Write failing tests for BucketCache**

Append to `tests/unit/test_bucket_cache.py`:

```python
# ---------------------------------------------------------------------------
# BucketCache tests
# ---------------------------------------------------------------------------

BUCKET_CACHE_MAX_ROWS = 100_000


def _make_df(n=10, bucket='REVIEW'):
    """Create a small test DataFrame mimicking import_merge_matches."""
    return pd.DataFrame({
        'id': range(n),
        'recommendation': [bucket] * n,
        'source_id': [f'SRC{i}' for i in range(n)],
        'source_ssn': [f'SSN{i}' for i in range(n)],
        'name_score': [80.0] * n,
        'address_score': [75.0] * n,
        'ssn_match': [100] * n,
    })


def test_bucket_cache_stores_bucket_and_df():
    from data_loader import BucketCache
    df = _make_df(5, 'REVIEW')
    cache = BucketCache('REVIEW', df)
    assert cache.bucket == 'REVIEW'
    assert len(cache.df) == 5


def test_bucket_cache_is_fresh_within_ttl():
    from data_loader import BucketCache
    cache = BucketCache('REVIEW', _make_df())
    assert cache.is_fresh(ttl_seconds=300) is True


def test_bucket_cache_is_stale_after_ttl():
    from data_loader import BucketCache
    import datetime
    cache = BucketCache('REVIEW', _make_df())
    # Backdate load_time by 6 minutes
    cache.load_time = cache.load_time - datetime.timedelta(seconds=361)
    assert cache.is_fresh(ttl_seconds=300) is False


def test_bucket_cache_update_row():
    from data_loader import BucketCache
    df = _make_df(5)
    cache = BucketCache('REVIEW', df)
    cache.update_row(row_id=2, field='recommendation', value='APPROVED')
    assert cache.df.loc[cache.df['id'] == 2, 'recommendation'].values[0] == 'APPROVED'


def test_bucket_cache_update_row_no_match_is_noop():
    from data_loader import BucketCache
    df = _make_df(5)
    cache = BucketCache('REVIEW', df)
    # id=999 doesn't exist — should not raise
    cache.update_row(row_id=999, field='recommendation', value='APPROVED')


def test_bucket_cache_rejects_oversized_df():
    from data_loader import BucketCache, BUCKET_CACHE_MAX_ROWS
    big_df = pd.DataFrame({'id': range(BUCKET_CACHE_MAX_ROWS + 1)})
    with pytest.raises(ValueError, match='exceeds'):
        BucketCache('REVIEW', big_df)
```

- [ ] **Step 2: Run to verify all new tests fail**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_bucket_cache.py -v -k "bucket_cache"
```
Expected: all 6 `FAILED` — `cannot import name 'BucketCache'`

- [ ] **Step 3: Implement `BucketCache` in `data_loader.py`**

Add at the bottom of the imports section (after the existing imports):

```python
import datetime

BUCKET_CACHE_MAX_ROWS = 100_000
```

Then add this class after the `DataSource` class (before `ensure_snowflake_schema`):

```python
class BucketCache:
    """
    In-memory cache for a single recommendation bucket (e.g., 'REVIEW').
    Holds up to BUCKET_CACHE_MAX_ROWS rows as a pandas DataFrame.
    Thread-safe reads; caller is responsible for serialising writes.
    """

    def __init__(self, bucket: str, df: pd.DataFrame):
        if len(df) > BUCKET_CACHE_MAX_ROWS:
            raise ValueError(
                f"DataFrame with {len(df):,} rows exceeds "
                f"BUCKET_CACHE_MAX_ROWS ({BUCKET_CACHE_MAX_ROWS:,})"
            )
        self.bucket = bucket
        self.df = df.copy()
        self.load_time = datetime.datetime.now()
        self.row_count = len(df)

    def is_fresh(self, ttl_seconds: int = 300) -> bool:
        """Return True if the cache is younger than ttl_seconds."""
        age = (datetime.datetime.now() - self.load_time).total_seconds()
        return age < ttl_seconds

    def update_row(self, row_id, field: str, value) -> None:
        """
        Update a single field for the row whose 'id' column equals row_id.
        No-op if row_id is not found in the cache.
        """
        mask = self.df['id'] == row_id
        if not mask.any():
            return
        self.df.loc[mask, field] = value
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_bucket_cache.py -v -k "bucket_cache"
```
Expected: all 6 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add data_loader.py tests/unit/test_bucket_cache.py
git commit -m "feat: add BucketCache class with TTL and in-place row updates"
```

---

## Task 3: Add `get_bucket_counts()` and `query_snowflake_page()` to `data_loader.py`

**Files:**
- Modify: `data_loader.py`
- Create: `tests/unit/test_sql_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_sql_builder.py`:

```python
"""Unit tests for SQL query building in data_loader."""
from unittest.mock import MagicMock, patch, call
import pytest


def _make_cursor(rows=None, description=None, rowcount=1):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = (rows or [[None]])[0] if rows else None
    cursor.description = description or [('COUNT(*)',)]
    cursor.rowcount = rowcount
    return cursor


# ---------------------------------------------------------------------------
# get_bucket_counts
# ---------------------------------------------------------------------------

def test_get_bucket_counts_returns_dict():
    from data_loader import get_bucket_counts
    cursor = _make_cursor(rows=[('REVIEW', 1234), ('AUTO_MERGE', 5678), ('APPROVED', 90)])
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_bucket_counts({'table': 'import_merge_matches'})
    assert result == {'REVIEW': 1234, 'AUTO_MERGE': 5678, 'APPROVED': 90}


def test_get_bucket_counts_handles_empty():
    from data_loader import get_bucket_counts
    cursor = _make_cursor(rows=[])
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_bucket_counts({'table': 'import_merge_matches'})
    assert result == {}


# ---------------------------------------------------------------------------
# query_snowflake_page — SQL construction
# ---------------------------------------------------------------------------

def test_query_snowflake_page_single_bucket_filter():
    from data_loader import query_snowflake_page
    executed_sqls = []

    cursor = MagicMock()
    # First call = total count, second = filtered count, third = page data
    cursor.fetchone.side_effect = [(50000,), (50000,)]
    cursor.fetchall.return_value = []
    cursor.description = [('id',), ('recommendation',), ('source_id',)]

    def capture_execute(sql, params=None):
        executed_sqls.append((sql, params))

    cursor.execute.side_effect = capture_execute
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch('data_loader.get_snowflake_connection', return_value=conn):
        query_snowflake_page(
            config={'table': 'import_merge_matches'},
            filters={'recommendation': 'REVIEW'},
            sort_col='name_score',
            sort_dir='desc',
            start=0,
            length=25,
        )

    # At least one SQL call must contain WHERE ... RECOMMENDATION
    sql_bodies = [s for s, _ in executed_sqls]
    assert any('RECOMMENDATION' in s.upper() for s in sql_bodies)
    assert any('ORDER BY' in s.upper() for s in sql_bodies)
    assert any('LIMIT' in s.upper() for s in sql_bodies)


def test_query_snowflake_page_returns_tuple():
    from data_loader import query_snowflake_page
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1000,), (250,)]
    cursor.fetchall.return_value = [{'id': 1, 'recommendation': 'REVIEW'}]
    cursor.description = [('id',), ('recommendation',)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        rows, total, filtered = query_snowflake_page(
            config={'table': 'import_merge_matches'},
            filters={},
            sort_col=None,
            sort_dir='asc',
            start=0,
            length=25,
        )
    assert isinstance(rows, list)
    assert isinstance(total, int)
    assert isinstance(filtered, int)
```

- [ ] **Step 2: Run to verify tests fail**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_sql_builder.py -v
```
Expected: all `FAILED` — `cannot import name 'get_bucket_counts'`

- [ ] **Step 3: Implement `get_bucket_counts()` in `data_loader.py`**

Add after `BucketCache` class:

```python
def get_bucket_counts(config: Dict[str, Any]) -> Dict[str, int]:
    """
    Return a dict of {recommendation_value: row_count} for all buckets.
    Uses a single GROUP BY query — fast even on 2M rows.
    """
    table = config.get('table', 'import_merge_matches').upper()
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT RECOMMENDATION, COUNT(*) AS CNT "
        f"FROM {table} "
        f"GROUP BY RECOMMENDATION"
    )
    return {row[0]: int(row[1]) for row in cursor.fetchall() if row[0] is not None}
```

- [ ] **Step 4: Implement `query_snowflake_page()` in `data_loader.py`**

Add after `get_bucket_counts()`:

```python
# Columns the frontend grid needs — used for SELECT projection
_GRID_COLUMNS = [
    'ID', 'SSN_MATCH', 'NAME_SCORE', 'ADDRESS_SCORE', 'NAMEADDRSCORE',
    'RECOMMENDATION', 'HOW_TO_PROCESS', 'SOURCE_ID', 'SOURCE_ADDRSEQ',
    'SOURCE_NAME', 'SOURCE_ADDRESS', 'SOURCE_CITY', 'SOURCE_STATE',
    'SOURCE_ZIP', 'SOURCE_SSN', 'SOURCE_ADDRESS_RECOMEND',
    'DEC_SSN', 'DEC_NAME', 'DEC_ADDRESS', 'DEC_CITY', 'DEC_STATE',
    'DEC_ZIP', 'DEC_HDRCODE', 'DEC_ADDRSUBCODE', 'DEC_CONTACT',
    'DEC_ADDRESS_LOOKED_UP', 'ADDRESS_REASON', 'JIB', 'REV', 'VENDOR',
    'MEMO', 'IS_TRUST', 'RUN_ID',
    'NAME_NORMAL_DETAIL', 'ADDRESS_NORMAL_DETAIL',
    'NAME_MATCH_DETAIL', 'ADDR_MATCH_DETAIL',
]

# Columns safe to sort by (prevents SQL injection via ORDER BY)
_SORTABLE_COLS = {
    'id', 'ssn_match', 'name_score', 'address_score', 'recommendation',
    'source_name', 'source_address', 'source_city', 'source_id',
    'dec_name', 'dec_address', 'dec_city', 'dec_hdrcode',
    'dec_address_looked_up', 'jib', 'rev', 'vendor', 'how_to_process', 'memo',
}


def query_snowflake_page(
    config: Dict[str, Any],
    filters: Dict[str, Any],
    sort_col: Optional[str],
    sort_dir: str,
    start: int,
    length: int,
) -> Tuple[List[dict], int, int]:
    """
    Run a paginated SQL query against Snowflake.

    Args:
        config:    Snowflake config dict
        filters:   Dict of active filter values — keys:
                     'recommendation' (str, comma-separated or single)
                     'ssn_filter'     ('yes'|'no'|'partial')
                     'min_name_score', 'max_name_score'  (float)
                     'min_addr_score', 'max_addr_score'  (float)
                     'search'         (str, global text search)
        sort_col:  Column name to sort by (None = no sort)
        sort_dir:  'asc' or 'desc'
        start:     Row offset (0-based)
        length:    Page size (-1 = all)

    Returns:
        (rows_as_dicts, total_count, filtered_count)
    """
    table = config.get('table', 'import_merge_matches').upper()
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()

    # --- Build WHERE clause ---
    conditions: List[str] = []
    params: List[Any] = []

    rec = filters.get('recommendation', '')
    if rec:
        rec_values = [v.strip() for v in rec.split(',') if v.strip()]
        if len(rec_values) == 1:
            conditions.append('RECOMMENDATION = %s')
            params.append(rec_values[0])
        elif rec_values:
            placeholders = ', '.join(['%s'] * len(rec_values))
            conditions.append(f'RECOMMENDATION IN ({placeholders})')
            params.extend(rec_values)

    ssn_filter = filters.get('ssn_filter', '')
    if ssn_filter == 'yes':
        conditions.append('SSN_MATCH = 100')
    elif ssn_filter == 'no':
        conditions.append('SSN_MATCH = 0')
    elif ssn_filter == 'partial':
        conditions.append('SSN_MATCH > 0 AND SSN_MATCH < 100')

    for col, op in [
        ('min_name_score', 'NAME_SCORE >= %s'),
        ('max_name_score', 'NAME_SCORE <= %s'),
        ('min_addr_score', 'ADDRESS_SCORE >= %s'),
        ('max_addr_score', 'ADDRESS_SCORE <= %s'),
    ]:
        val = filters.get(col)
        if val is not None:
            conditions.append(op)
            params.append(float(val))

    search = filters.get('search', '').strip()
    if search:
        text_cols = [
            'SOURCE_NAME', 'SOURCE_ADDRESS', 'SOURCE_CITY', 'SOURCE_STATE',
            'SOURCE_ZIP', 'DEC_NAME', 'DEC_ADDRESS', 'DEC_CITY',
            'DEC_HDRCODE', 'RECOMMENDATION', 'HOW_TO_PROCESS', 'MEMO',
        ]
        like_clauses = ' OR '.join(f"{c} ILIKE %s" for c in text_cols)
        conditions.append(f'({like_clauses})')
        params.extend([f'%{search}%'] * len(text_cols))

    where_sql = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

    # --- Total count (no filters) ---
    cursor.execute(f'SELECT COUNT(*) FROM {table}')
    total_count = int(cursor.fetchone()[0])

    # --- Filtered count ---
    cursor.execute(f'SELECT COUNT(*) FROM {table} {where_sql}', params)
    filtered_count = int(cursor.fetchone()[0])

    # --- Page data ---
    col_list = ', '.join(_GRID_COLUMNS)
    order_sql = ''
    if sort_col and sort_col.lower() in _SORTABLE_COLS:
        direction = 'DESC' if sort_dir.lower() == 'desc' else 'ASC'
        order_sql = f'ORDER BY {sort_col.upper()} {direction}'

    limit_sql = '' if length == -1 else f'LIMIT {int(length)} OFFSET {int(start)}'

    cursor.execute(
        f'SELECT {col_list} FROM {table} {where_sql} {order_sql} {limit_sql}',
        params,
    )
    col_names = [desc[0].lower() for desc in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]

    return rows, total_count, filtered_count
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_sql_builder.py -v
```
Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add data_loader.py tests/unit/test_sql_builder.py
git commit -m "feat: add get_bucket_counts and query_snowflake_page SQL functions"
```

---

## Task 4: Add `save_record_immediately()` and `save_records_batch()` to `data_loader.py`

**Files:**
- Modify: `data_loader.py`
- Create: `tests/unit/test_save_functions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_save_functions.py`:

```python
"""Unit tests for immediate-write save functions."""
from unittest.mock import MagicMock, patch, call
import pytest
from datetime import datetime


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 1
    conn.cursor.return_value = cursor
    return conn, cursor


def test_save_record_immediately_runs_update():
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=42,
            source_id='SRC001',
            source_ssn='555-12-3456',
            fields={'recommendation': ('REVIEW', 'APPROVED')},
            user_id='uuid-abc',
            user_name='Alice',
        )
    assert result == 1
    # Verify UPDATE was called (not MERGE)
    calls = [str(c) for c in cursor.execute.call_args_list]
    assert any('UPDATE' in c.upper() for c in calls)
    assert any('WHERE' in c.upper() and 'ID' in c.upper() for c in calls)


def test_save_record_immediately_writes_audit_log():
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=42,
            source_id='SRC001',
            source_ssn='555-12-3456',
            fields={'recommendation': ('REVIEW', 'APPROVED')},
            user_id='uuid-abc',
            user_name='Alice',
        )
    calls = [str(c) for c in cursor.execute.call_args_list]
    assert any('UPDATE_LOG' in c.upper() or 'INSERT' in c.upper() for c in calls)


def test_save_records_batch_updates_all_records():
    from data_loader import save_records_batch
    conn, cursor = _mock_conn()
    cursor.rowcount = 3
    records = [
        {'record_id': 1, 'source_id': 'S1', 'source_ssn': 'SSN1',
         'fields': {'recommendation': ('REVIEW', 'APPROVED')}},
        {'record_id': 2, 'source_id': 'S2', 'source_ssn': 'SSN2',
         'fields': {'recommendation': ('REVIEW', 'APPROVED')}},
        {'record_id': 3, 'source_id': 'S3', 'source_ssn': 'SSN3',
         'fields': {'recommendation': ('AUTO_MERGE', 'APPROVED')}},
    ]
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        affected = save_records_batch(
            config={'table': 'import_merge_matches'},
            records=records,
            user_id='uuid-abc',
            user_name='Alice',
        )
    assert affected >= 0  # returns rowcount


def test_save_record_maps_source_address_recomend():
    """source_address_recomend maps to SOURCE_ADDRESS column in DB."""
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    executed = []
    cursor.execute.side_effect = lambda sql, params=None: executed.append(sql)
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=1,
            source_id='S1',
            source_ssn='SSN1',
            fields={'source_address_recomend': ('123 Old St', '456 New Ave')},
        )
    update_sql = next(s for s in executed if 'UPDATE' in s.upper())
    assert 'SOURCE_ADDRESS' in update_sql.upper()
    assert 'SOURCE_ADDRESS_RECOMEND' not in update_sql.upper()
```

- [ ] **Step 2: Run to verify tests fail**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_save_functions.py -v
```
Expected: all `FAILED` — `cannot import name 'save_record_immediately'`

- [ ] **Step 3: Implement `save_record_immediately()` and `save_records_batch()` in `data_loader.py`**

Add after `query_snowflake_page()`:

```python
# Field name to Snowflake column name override
_FIELD_TO_DB_COL = {
    'source_address_recomend': 'SOURCE_ADDRESS',
}
_INT_DB_COLS = {'JIB', 'REV', 'VENDOR'}


def save_record_immediately(
    config: Dict[str, Any],
    record_id,
    source_id: str,
    source_ssn: str,
    fields: Dict[str, Any],
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> int:
    """
    Immediately persist changes for a single record.

    Args:
        config:     Snowflake config dict
        record_id:  Value of the ID column (Snowflake primary key)
        source_id:  Source system identifier (for audit log)
        source_ssn: Source SSN (for audit log)
        fields:     {field_name: (old_value, new_value)} or {field_name: new_value}
        user_id:    Browser UUID cookie (optional, for audit log)
        user_name:  Display name (optional, for audit log)

    Returns:
        Number of rows updated (should be 1)
    """
    if not fields:
        return 0

    table = config.get('table', 'import_merge_matches').upper()
    set_parts: List[str] = []
    set_params: List[Any] = []

    for field, change in fields.items():
        new_val = change[1] if isinstance(change, tuple) else change
        db_col = _FIELD_TO_DB_COL.get(field, field.upper())
        if db_col in _INT_DB_COLS:
            set_parts.append(f'{db_col} = CAST(%s AS INTEGER)')
            set_params.append(int(new_val) if new_val is not None else 0)
        else:
            set_parts.append(f'{db_col} = CAST(%s AS VARCHAR)')
            set_params.append(str(new_val) if new_val is not None else '')

    set_params.append(record_id)
    sql = f"UPDATE {table} SET {', '.join(set_parts)} WHERE ID = %s"

    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    cursor.execute(sql, set_params)

    # Audit log
    now = datetime.now()
    log_entries = []
    for field, change in fields.items():
        old_val, new_val = change if isinstance(change, tuple) else ('', change)
        log_entries.append((
            str(source_id), str(source_ssn), field,
            str(old_val), str(new_val), now, user_id, user_name,
        ))
    write_audit_log_to_snowflake(config, log_entries, cursor=cursor)
    conn.commit()
    return cursor.rowcount


def save_records_batch(
    config: Dict[str, Any],
    records: List[Dict[str, Any]],
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> int:
    """
    Immediately persist changes for multiple records in a single transaction.

    Args:
        config:   Snowflake config dict
        records:  List of dicts, each with keys:
                    record_id, source_id, source_ssn,
                    fields: {field_name: (old_value, new_value)}
        user_id:  Browser UUID (optional)
        user_name: Display name (optional)

    Returns:
        Total rows updated
    """
    if not records:
        return 0

    # Collect all unique field names to build one UPDATE per field group
    # Group records by the set of fields being updated (most bulk ops update
    # the same field for all records, so this is typically one group).
    from collections import defaultdict
    groups: Dict[frozenset, List[dict]] = defaultdict(list)
    for rec in records:
        key = frozenset(rec['fields'].keys())
        groups[key].append(rec)

    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    table = config.get('table', 'import_merge_matches').upper()
    total_affected = 0
    now = datetime.now()
    all_log_entries = []

    for field_set, group in groups.items():
        fields_list = sorted(field_set)
        set_parts: List[str] = []
        for field in fields_list:
            db_col = _FIELD_TO_DB_COL.get(field, field.upper())
            if db_col in _INT_DB_COLS:
                set_parts.append(f'{db_col} = CAST(%s AS INTEGER)')
            else:
                set_parts.append(f'{db_col} = CAST(%s AS VARCHAR)')

        set_sql = ', '.join(set_parts)
        id_placeholders = ', '.join(['%s'] * len(group))
        sql = f"UPDATE {table} SET {set_sql} WHERE ID IN ({id_placeholders})"

        # Build params: one set of values per unique value combination
        # For bulk approve all records get same values, so build once per group
        # This handles the common case; heterogeneous batches fall back to per-record
        value_sets = set()
        for rec in group:
            vals = tuple(
                (rec['fields'][f][1] if isinstance(rec['fields'][f], tuple)
                 else rec['fields'][f])
                for f in fields_list
            )
            value_sets.add(vals)

        if len(value_sets) == 1:
            # All records in group get identical new values — one UPDATE
            new_vals = list(next(iter(value_sets)))
            coerced = []
            for field, val in zip(fields_list, new_vals):
                db_col = _FIELD_TO_DB_COL.get(field, field.upper())
                if db_col in _INT_DB_COLS:
                    coerced.append(int(val) if val is not None else 0)
                else:
                    coerced.append(str(val) if val is not None else '')
            id_params = [rec['record_id'] for rec in group]
            cursor.execute(sql, coerced + id_params)
            total_affected += cursor.rowcount
        else:
            # Heterogeneous values — fall back to per-record saves
            for rec in group:
                affected = save_record_immediately(
                    config, rec['record_id'], rec['source_id'], rec['source_ssn'],
                    rec['fields'], user_id=user_id, user_name=user_name,
                )
                total_affected += affected
            continue  # audit log handled inside save_record_immediately

        # Audit log for uniform-value batch
        for rec in group:
            for field, change in rec['fields'].items():
                old_val, new_val = change if isinstance(change, tuple) else ('', change)
                all_log_entries.append((
                    str(rec['source_id']), str(rec['source_ssn']), field,
                    str(old_val), str(new_val), now, user_id, user_name,
                ))

    if all_log_entries:
        write_audit_log_to_snowflake(config, all_log_entries, cursor=cursor)
    conn.commit()
    return total_affected
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_save_functions.py -v
```
Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add data_loader.py tests/unit/test_save_functions.py
git commit -m "feat: add save_record_immediately and save_records_batch for immediate Snowflake writes"
```

---

## Task 5: Update `ensure_snowflake_schema()` and `write_audit_log_to_snowflake()` for user identity

**Files:**
- Modify: `data_loader.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_save_functions.py`:

```python
def test_write_audit_log_includes_user_id_and_user_name():
    """write_audit_log_to_snowflake must accept 8-tuple entries with user_id/user_name."""
    from data_loader import write_audit_log_to_snowflake
    from datetime import datetime
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        write_audit_log_to_snowflake(
            config={'table': 'import_merge_matches'},
            log_entries=[('S1', 'SSN1', 'recommendation', 'REVIEW', 'APPROVED',
                          datetime.now(), 'uuid-abc', 'Alice')],
        )
    calls = [str(c) for c in cursor.executemany.call_args_list]
    assert any('USER_ID' in c.upper() or 'USER_NAME' in c.upper() for c in calls)
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/test_save_functions.py::test_write_audit_log_includes_user_id_and_user_name -v
```
Expected: `FAILED` — INSERT statement does not include USER_ID

- [ ] **Step 3: Update `ensure_snowflake_schema()` to add USER_ID/USER_NAME columns**

In `data_loader.py`, find the `ensure_snowflake_schema()` function. After the existing UPDATE_LOG column rename block (the `if 'canvas_id' in log_cols` block), add:

```python
    # Add USER_ID and USER_NAME columns to UPDATE_LOG if missing
    if 'user_id' not in log_cols:
        try:
            cursor.execute("ALTER TABLE UPDATE_LOG ADD COLUMN USER_ID VARCHAR")
            print("  Added USER_ID to UPDATE_LOG")
        except Exception as e:
            print(f"  Adding USER_ID to UPDATE_LOG skipped: {e}")
    if 'user_name' not in log_cols:
        try:
            cursor.execute("ALTER TABLE UPDATE_LOG ADD COLUMN USER_NAME VARCHAR")
            print("  Added USER_NAME to UPDATE_LOG")
        except Exception as e:
            print(f"  Adding USER_NAME to UPDATE_LOG skipped: {e}")
```

- [ ] **Step 4: Update `write_audit_log_to_snowflake()` to accept 8-tuple entries**

Replace the `write_audit_log_to_snowflake` function body with:

```python
def write_audit_log_to_snowflake(
    config: Dict[str, Any],
    log_entries: List[Tuple],
    cursor=None
) -> None:
    """
    Batch-insert audit log entries to Snowflake UPDATE_LOG table.

    Each entry in log_entries must be a tuple of:
        (source_id, source_ssn, field_name, old_value, new_value, updated_at)
    OR the extended form:
        (source_id, source_ssn, field_name, old_value, new_value, updated_at,
         user_id, user_name)

    Both forms are accepted for backward compatibility.
    """
    if not log_entries:
        return

    own_cursor = cursor is None
    if own_cursor:
        conn = get_snowflake_connection(config)
        cursor = conn.cursor()

    # Normalise all entries to 8-tuples
    normalised = []
    for entry in log_entries:
        if len(entry) == 6:
            normalised.append(entry + (None, None))
        else:
            normalised.append(entry)

    cursor.executemany(
        """INSERT INTO UPDATE_LOG
               (SOURCE_ID, SOURCE_SSN, FIELD_NAME, OLD_VALUE, NEW_VALUE,
                UPDATED_AT, USER_ID, USER_NAME)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        normalised,
    )
    if own_cursor:
        conn.commit()
```

- [ ] **Step 5: Run all unit tests to verify nothing broke**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/ -v
```
Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add data_loader.py tests/unit/test_save_functions.py
git commit -m "feat: add USER_ID/USER_NAME columns to UPDATE_LOG audit trail"
```

---

## Task 6: Add `BucketCache` instance and helpers to `app.py`; replace `load_cached_data()`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add module-level cache state and helper, replacing `_df_cache` globals**

In `app.py`, find and remove these lines:

```python
# In-memory cache to avoid re-reading Snowflake on every request
_df_cache = None
_df_cache_time = None

# Track unsaved changes: {row_id: {field: (old_value, new_value), ...}, ...}
_pending_changes = {}
```

Replace with:

```python
import uuid as _uuid_module
import threading as _threading

# Single active BucketCache — shared across all users
_bucket_cache: Optional['BucketCache'] = None
_bucket_cache_lock = _threading.Lock()
CACHE_TTL_SECONDS = 300  # 5 minutes
```

- [ ] **Step 2: Add `_get_or_load_bucket_cache()` helper**

Add this function in `app.py` after the `_get_source_company_name()` function:

```python
def _get_or_load_bucket_cache(bucket: str, force: bool = False):
    """
    Return the active BucketCache for the given bucket.
    Loads from Snowflake if the cache is empty, stale, or for a different bucket.
    If the bucket has > BUCKET_CACHE_MAX_ROWS rows, returns None (SQL mode).
    """
    global _bucket_cache
    from data_loader import BucketCache, BUCKET_CACHE_MAX_ROWS

    with _bucket_cache_lock:
        if (
            not force
            and _bucket_cache is not None
            and _bucket_cache.bucket == bucket
            and _bucket_cache.is_fresh(CACHE_TTL_SECONDS)
        ):
            return _bucket_cache

        # Check bucket size before loading
        counts = get_bucket_counts(DATA_CONFIG)
        bucket_size = counts.get(bucket, 0)
        if bucket_size > BUCKET_CACHE_MAX_ROWS:
            _bucket_cache = None
            return None  # SQL mode

        # Load bucket into cache
        conn = get_snowflake_connection(DATA_CONFIG)
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        df = pd.read_sql_query(
            f"SELECT * FROM {table} WHERE RECOMMENDATION = %s LIMIT %s",
            conn,
            params=(bucket, BUCKET_CACHE_MAX_ROWS),
        )
        df.columns = df.columns.str.lower()
        df = DataSource._normalize_dataframe(df)

        try:
            _bucket_cache = BucketCache(bucket, df)
        except ValueError:
            _bucket_cache = None
            return None  # Oversized — SQL mode

        return _bucket_cache


def _invalidate_cache():
    """Clear the active bucket cache (call after writes)."""
    global _bucket_cache
    with _bucket_cache_lock:
        _bucket_cache = None
```

Also update imports at the top of `app.py` to include the new data_loader functions:

```python
from data_loader import (
    load_data, get_snowflake_connection, merge_changes_to_snowflake,
    write_audit_log_to_snowflake, read_audit_log_from_snowflake,
    ensure_snowflake_schema, count_staging_eligible, stage_approved_records,
    save_grid_setting, load_grid_setting,
    get_bucket_counts, query_snowflake_page,
    save_record_immediately, save_records_batch,
    DataSource, BucketCache, BUCKET_CACHE_MAX_ROWS,
)
```

- [ ] **Step 3: Remove `load_cached_data()` function**

Delete the entire `load_cached_data()` function from `app.py`.

- [ ] **Step 4: Add user-identity cookie helper**

Add this helper after `_invalidate_cache()`:

```python
def _get_user_identity():
    """
    Return (user_id, user_name) from request cookies.
    user_id: UUID string set on first visit.
    user_name: Display name chosen by user (may be None).
    """
    user_id = request.cookies.get('user_id')
    user_name = request.cookies.get('user_name')
    return user_id, user_name
```

- [ ] **Step 5: Update the `/` index route to set `user_id` cookie on first visit**

Replace the existing `index()` route with:

```python
@app.route('/')
def index():
    response = make_response(render_template(
        'index.html',
        source_company_name=_get_source_company_name()
    ))
    if not request.cookies.get('user_id'):
        new_uid = str(_uuid_module.uuid4())
        response.set_cookie('user_id', new_uid, max_age=365 * 24 * 3600, samesite='Lax')
    return response
```

Add `make_response` to the Flask import at the top of `app.py`:

```python
from flask import Flask, render_template, request, jsonify, Response, make_response
```

- [ ] **Step 6: Verify app still starts (smoke test)**

```bash
cd /c/ClaudeMain/BA_Review_App && python -c "import app; print('app imports OK')"
```
Expected: `app imports OK`

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: replace monolithic cache with BucketCache + user_id cookie on first visit"
```

---

## Task 7: Update `/api/matches` to use hybrid cache + SQL mode

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Replace `get_matches()` route**

Find and replace the entire `get_matches()` function in `app.py` with:

```python
@app.route('/api/matches')
def get_matches():
    """Server-side DataTables endpoint — hybrid hot-cache / SQL mode."""
    try:
        draw = request.args.get('draw', type=int, default=1)
        start = request.args.get('start', type=int, default=0)
        length = request.args.get('length', type=int, default=25)

        recommendation_filter = request.args.get('recommendation', default='')
        ssn_filter = request.args.get('ssn_match', default='')
        min_name_score = request.args.get('min_name_score', type=float, default=None)
        max_name_score = request.args.get('max_name_score', type=float, default=None)
        min_addr_score = request.args.get('min_addr_score', type=float, default=None)
        max_addr_score = request.args.get('max_addr_score', type=float, default=None)
        search_value = request.args.get('search[value]', default='').strip()
        order_col_idx = request.args.get('order[0][column]', type=int, default=None)
        order_dir = request.args.get('order[0][dir]', default='asc')

        sort_col = None
        if order_col_idx is not None:
            col_data = request.args.get(f'columns[{order_col_idx}][data]', default=None)
            if col_data in {
                'id', 'ssn_match', 'name_score', 'address_score', 'recommendation',
                'source_name', 'source_address', 'source_city', 'source_id',
                'dec_name', 'dec_address', 'dec_city', 'dec_hdrcode',
                'dec_address_looked_up', 'jib', 'rev', 'vendor', 'how_to_process', 'memo',
            }:
                sort_col = col_data

        # Decide mode: hot cache if single bucket filter, no global search,
        # and bucket fits in memory.
        rec_values = [v.strip() for v in recommendation_filter.split(',') if v.strip()]
        single_bucket = len(rec_values) == 1
        use_cache = single_bucket and not search_value

        cache_mode = 'sql'
        data = []
        records_total = 0
        records_filtered = 0

        if use_cache:
            cache = _get_or_load_bucket_cache(rec_values[0])
            if cache is not None:
                cache_mode = 'cached'
                df = cache.df

                records_total = len(df)

                # Apply sub-filters in pandas
                mask = pd.Series(True, index=df.index)
                if ssn_filter == 'yes':
                    mask &= df['ssn_match'] == 100
                elif ssn_filter == 'no':
                    mask &= df['ssn_match'] == 0
                elif ssn_filter == 'partial':
                    mask &= (df['ssn_match'] > 0) & (df['ssn_match'] < 100)
                if min_name_score is not None:
                    mask &= df['name_score'] >= min_name_score
                if max_name_score is not None:
                    mask &= df['name_score'] <= max_name_score
                if min_addr_score is not None:
                    mask &= df['address_score'] >= min_addr_score
                if max_addr_score is not None:
                    mask &= df['address_score'] <= max_addr_score

                df_filtered = df[mask]

                if sort_col and sort_col in df_filtered.columns:
                    df_filtered = df_filtered.sort_values(
                        sort_col, ascending=(order_dir == 'asc'), na_position='last'
                    )

                records_filtered = len(df_filtered)
                df_page = df_filtered.iloc[start:] if length == -1 else df_filtered.iloc[start:start + length]

                needed_cols = [
                    'id', 'ssn_match', 'name_score', 'address_score', 'nameaddrscore',
                    'recommendation', 'how_to_process', 'source_id', 'source_addrseq',
                    'source_name', 'source_address', 'source_city', 'source_state',
                    'source_zip', 'source_ssn', 'source_address_recomend',
                    'dec_ssn', 'dec_name', 'dec_address', 'dec_city', 'dec_state',
                    'dec_zip', 'dec_hdrcode', 'dec_addrsubcode', 'dec_contact',
                    'dec_address_looked_up', 'address_reason', 'jib', 'rev', 'vendor',
                    'memo', 'is_trust', 'run_id',
                    'name_normal_detail', 'address_normal_detail',
                    'name_match_detail', 'addr_match_detail',
                ]
                available = [c for c in needed_cols if c in df_page.columns]
                df_out = df_page[available].fillna('').copy()
                df_out['_row_id'] = df_page['id']
                data = df_out.to_dict('records')

        if cache_mode == 'sql':
            filters = {
                'recommendation': recommendation_filter,
                'ssn_filter': ssn_filter,
                'min_name_score': min_name_score,
                'max_name_score': max_name_score,
                'min_addr_score': min_addr_score,
                'max_addr_score': max_addr_score,
                'search': search_value,
            }
            rows, records_total, records_filtered = query_snowflake_page(
                config=DATA_CONFIG,
                filters=filters,
                sort_col=sort_col,
                sort_dir=order_dir,
                start=start,
                length=length,
            )
            for row in rows:
                row['_row_id'] = row.get('id')
                # Fill None → ''
                data = [{k: ('' if v is None else v) for k, v in r.items()} for r in rows]

        result = json.dumps({
            'draw': draw,
            'recordsTotal': records_total,
            'recordsFiltered': records_filtered,
            'data': data,
            'cache_mode': cache_mode,
        }, ensure_ascii=False, default=str)

        return Response(result, mimetype='application/json')

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Update `/api/stats` to use SQL counts instead of in-memory DataFrame**

Replace the `get_stats()` function with:

```python
@app.route('/api/stats')
def get_stats():
    try:
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()

        cursor.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN SSN_MATCH = 100 THEN 1 ELSE 0 END) AS ssn_perfect,
                SUM(CASE WHEN SSN_MATCH > 0 AND SSN_MATCH < 100 THEN 1 ELSE 0 END) AS ssn_partial,
                SUM(CASE WHEN SSN_MATCH = 0 THEN 1 ELSE 0 END) AS ssn_none,
                AVG(NAME_SCORE) AS avg_name,
                AVG(ADDRESS_SCORE) AS avg_addr
            FROM {table}
        """)
        row = cursor.fetchone()
        total, ssn_perfect, ssn_partial, ssn_none, avg_name, avg_addr = row

        cursor.execute(
            f"SELECT RECOMMENDATION, COUNT(*) FROM {table} GROUP BY RECOMMENDATION"
        )
        rec_counts = {r[0]: r[1] for r in cursor.fetchall() if r[0]}

        stats = {
            'total_records': int(total or 0),
            'recommendations': rec_counts,
            'avg_name_score': round(float(avg_name or 0), 1),
            'avg_address_score': round(float(avg_addr or 0), 1),
            'ssn_perfect_matches': int(ssn_perfect or 0),
            'ssn_partial_matches': int(ssn_partial or 0),
            'ssn_no_match': int(ssn_none or 0),
            'rec_config': _load_ba_config(),
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 3: Update `/api/staging_count` to use SQL**

Replace `staging_count()` with:

```python
@app.route('/api/staging_count')
def staging_count():
    """Return the number of records eligible for staging."""
    try:
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE UPPER(RECOMMENDATION) = 'APPROVED' "
            f"AND HOW_TO_PROCESS IS NOT NULL AND TRIM(HOW_TO_PROCESS) != ''"
        )
        count = int(cursor.fetchone()[0])
        return jsonify({'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Update `/api/reload` to invalidate cache**

Replace `reload_data()` with:

```python
@app.route('/api/reload', methods=['POST'])
def reload_data():
    """Invalidate the bucket cache so the next request reloads from Snowflake."""
    try:
        _invalidate_cache()
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        total = int(cursor.fetchone()[0])
        return jsonify({
            'success': True,
            'records': total,
            'message': f'Cache cleared. {total:,} total records in Snowflake.',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 5: Verify import — smoke test**

```bash
cd /c/ClaudeMain/BA_Review_App && python -c "import app; print('app imports OK')"
```
Expected: `app imports OK`

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: update /api/matches to use hybrid BucketCache + SQL fallback; stats and counts via SQL"
```

---

## Task 8: Replace all save endpoints with immediate writes

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Replace `/api/update` with immediate write**

Find and replace the entire `update_record()` function with:

```python
@app.route('/api/update', methods=['POST'])
def update_record():
    """Update a single field on a record — writes immediately to Snowflake."""
    try:
        data = request.json
        row_id = data.get('row_id')        # Snowflake id column value
        record_id = data.get('id', row_id) # prefer explicit 'id' if sent
        source_id = data.get('source_id', '')
        source_ssn = data.get('source_ssn', '')
        field = data.get('field')
        value = data.get('value')
        old_value = data.get('old_value', '')

        if record_id is None or not field:
            return jsonify({'error': 'Missing required fields'}), 400

        allowed_fields = {
            'recommendation', 'source_name', 'source_address_recomend',
            'source_city', 'source_state', 'source_zip', 'address_reason',
            'jib', 'rev', 'vendor', 'how_to_process', 'memo'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        if field in ('jib', 'rev', 'vendor'):
            value = int(value)

        # Block edits on STAGED records — check via quick SQL lookup
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        cursor.execute(f'SELECT RECOMMENDATION FROM {table} WHERE ID = %s', (record_id,))
        row = cursor.fetchone()
        if row and str(row[0] or '').upper() == 'STAGED':
            return jsonify({'error': 'Cannot modify a STAGED record'}), 403

        user_id, user_name = _get_user_identity()
        save_record_immediately(
            DATA_CONFIG, record_id, source_id, source_ssn,
            {field: (old_value, value)},
            user_id=user_id, user_name=user_name,
        )

        # Update hot cache row in-place
        with _bucket_cache_lock:
            if _bucket_cache is not None:
                _bucket_cache.update_row(row_id=record_id, field=field, value=value)

        return jsonify({'success': True, 'message': 'Saved'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Replace `/api/bulk_update` with immediate write**

Find and replace the entire `bulk_update()` function with:

```python
@app.route('/api/bulk_update', methods=['POST'])
def bulk_update():
    """Bulk update recommendation for multiple records — writes immediately."""
    try:
        data = request.json
        records_in = data.get('records', [])  # new: list of {id, source_id, source_ssn, old_recommendation}
        # Legacy shape: row_ids list (for backward compat with frontend during transition)
        row_ids = data.get('row_ids', [])
        new_recommendation = data.get('recommendation', 'APPROVED')
        process_values = data.get('process_values', {})

        if not records_in and not row_ids:
            return jsonify({'error': 'No records provided'}), 400

        # Normalise to records_in shape
        if not records_in and row_ids:
            # Legacy: look up source_id/source_ssn from cache or DB
            records_in = []
            for rid in row_ids:
                rec = {'id': rid, 'source_id': '', 'source_ssn': '', 'old_recommendation': ''}
                if _bucket_cache is not None:
                    mask = _bucket_cache.df['id'] == rid
                    if mask.any():
                        rec['source_id'] = str(_bucket_cache.df.loc[mask, 'source_id'].values[0])
                        rec['source_ssn'] = str(_bucket_cache.df.loc[mask, 'source_ssn'].values[0])
                        rec['old_recommendation'] = str(_bucket_cache.df.loc[mask, 'recommendation'].values[0])
                records_in.append(rec)

        # Build batch records
        batch = []
        for rec in records_in:
            rid = rec.get('id')
            fields = {'recommendation': (rec.get('old_recommendation', ''), new_recommendation)}
            pv = process_values.get(str(rid)) or process_values.get(rid)
            if pv:
                fields['how_to_process'] = ('', pv)
            batch.append({
                'record_id': rid,
                'source_id': rec.get('source_id', ''),
                'source_ssn': rec.get('source_ssn', ''),
                'fields': fields,
            })

        # Filter out STAGED records
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        ids_to_check = [b['record_id'] for b in batch]
        if ids_to_check:
            conn = get_snowflake_connection(DATA_CONFIG)
            cursor = conn.cursor()
            placeholders = ', '.join(['%s'] * len(ids_to_check))
            cursor.execute(
                f"SELECT ID FROM {table} WHERE ID IN ({placeholders}) "
                f"AND UPPER(RECOMMENDATION) = 'STAGED'",
                ids_to_check,
            )
            staged_ids = {row[0] for row in cursor.fetchall()}
            batch = [b for b in batch if b['record_id'] not in staged_ids]

        if not batch:
            return jsonify({'success': True, 'updated': 0})

        user_id, user_name = _get_user_identity()
        affected = save_records_batch(DATA_CONFIG, batch, user_id=user_id, user_name=user_name)

        # Update hot cache
        with _bucket_cache_lock:
            if _bucket_cache is not None:
                for b in batch:
                    _bucket_cache.update_row(b['record_id'], 'recommendation', new_recommendation)

        return jsonify({'success': True, 'updated': len(batch)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 3: Replace `/api/bulk_field_update` with immediate write**

Find and replace the entire `bulk_field_update()` function with:

```python
@app.route('/api/bulk_field_update', methods=['POST'])
def bulk_field_update():
    """Bulk update a single field for multiple records — writes immediately."""
    try:
        data = request.json
        records_in = data.get('records', [])
        row_ids = data.get('row_ids', [])  # legacy
        field = data.get('field')
        value = data.get('value')

        if not field:
            return jsonify({'error': 'Missing field'}), 400

        allowed_fields = {
            'recommendation', 'source_name', 'source_address_recomend',
            'source_city', 'source_state', 'source_zip', 'address_reason',
            'jib', 'rev', 'vendor', 'how_to_process', 'memo'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        if field in ('jib', 'rev', 'vendor'):
            value = int(value)

        # Normalise legacy shape
        if not records_in and row_ids:
            records_in = [{'id': rid, 'source_id': '', 'source_ssn': '', 'old_value': ''} for rid in row_ids]

        batch = [
            {
                'record_id': rec.get('id'),
                'source_id': rec.get('source_id', ''),
                'source_ssn': rec.get('source_ssn', ''),
                'fields': {field: (rec.get('old_value', ''), value)},
            }
            for rec in records_in
        ]

        user_id, user_name = _get_user_identity()
        affected = save_records_batch(DATA_CONFIG, batch, user_id=user_id, user_name=user_name)

        with _bucket_cache_lock:
            if _bucket_cache is not None:
                for b in batch:
                    _bucket_cache.update_row(b['record_id'], field, value)

        return jsonify({'success': True, 'updated': affected})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Replace `/api/search_replace` with immediate write**

Find and replace the entire `search_replace()` function with:

```python
@app.route('/api/search_replace', methods=['POST'])
def search_replace():
    """Search and replace text in one or all text columns — writes immediately."""
    try:
        data = request.json
        search = data.get('search', '')
        replace = data.get('replace', '')
        column = data.get('column', 'all')
        case_sensitive = data.get('case_sensitive', False)
        mode = data.get('mode', 'find')

        if not search:
            return jsonify({'error': 'Search text is required'}), 400

        text_fields = {
            'source_name', 'source_address_recomend', 'source_city',
            'source_state', 'source_zip', 'recommendation',
            'how_to_process', 'memo', 'address_reason',
        }
        if column == 'all':
            cols_to_search = list(text_fields)
        elif column in text_fields:
            cols_to_search = [column]
        else:
            return jsonify({'error': f'Column "{column}" is not searchable'}), 400

        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()

        # Build ILIKE conditions
        ilike_op = 'LIKE' if case_sensitive else 'ILIKE'
        col_map = {f: _FIELD_TO_DB_COL.get(f, f.upper()) for f in cols_to_search}
        like_clauses = ' OR '.join(f'{v} {ilike_op} %s' for v in col_map.values())

        row_ids = data.get('row_ids')
        id_where = ''
        id_params: list = []
        if row_ids:
            placeholders = ', '.join(['%s'] * len(row_ids))
            id_where = f' AND ID IN ({placeholders})'
            id_params = list(row_ids)

        like_params = [f'%{search}%'] * len(cols_to_search)

        if mode == 'find':
            cursor.execute(
                f'SELECT COUNT(*) FROM {table} WHERE ({like_clauses}){id_where}',
                like_params + id_params,
            )
            count = int(cursor.fetchone()[0])
            return jsonify({'matches': count, 'rows': count})

        # Replace mode — use Snowflake REGEXP_REPLACE or REPLACE
        flag = '' if case_sensitive else '(?i)'
        import re as _re
        user_id, user_name = _get_user_identity()

        total_replaced = 0
        for field, db_col in col_map.items():
            if case_sensitive:
                replace_sql = f"REPLACE({db_col}, %s, %s)"
                col_params = [search, replace]
            else:
                replace_sql = f"REGEXP_REPLACE({db_col}, %s, %s, 1, 0, 'i')"
                col_params = [_re.escape(search), replace]

            cursor.execute(
                f"UPDATE {table} SET {db_col} = {replace_sql} "
                f"WHERE ({db_col} {ilike_op} %s){id_where} "
                f"AND UPPER(RECOMMENDATION) != 'STAGED'",
                col_params + [f'%{search}%'] + id_params,
            )
            total_replaced += cursor.rowcount

            # Update hot cache for modified rows
            with _bucket_cache_lock:
                if _bucket_cache is not None:
                    cache_col = field  # pandas column name
                    if cache_col in _bucket_cache.df.columns:
                        ser = _bucket_cache.df[cache_col].astype(str).fillna('')
                        if case_sensitive:
                            mask = ser.str.contains(search, case=True, na=False, regex=False)
                            _bucket_cache.df.loc[mask, cache_col] = ser[mask].str.replace(
                                search, replace, regex=False
                            )
                        else:
                            mask = ser.str.contains(search, case=False, na=False, regex=False)
                            _bucket_cache.df.loc[mask, cache_col] = ser[mask].str.replace(
                                _re.escape(search), replace, case=False, regex=True
                            )

        conn.commit()
        return jsonify({'replaced': total_replaced, 'rows': total_replaced})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

Also add this import near the top of `app.py` (after the existing imports):

```python
from data_loader import _FIELD_TO_DB_COL
```

- [ ] **Step 5: Replace `/api/import_ids` with immediate write**

Find and replace the entire `import_ids()` function with:

```python
@app.route('/api/import_ids', methods=['POST'])
def import_ids():
    """Import Source IDs from file — writes immediately to Snowflake."""
    try:
        data = request.json
        field = data.get('field')
        source_ids = data.get('source_ids', data.get('canvas_ids', []))

        if field not in ('jib', 'rev', 'vendor'):
            return jsonify({'error': 'Invalid field'}), 400
        if not source_ids:
            return jsonify({'error': 'No Source IDs provided'}), 400

        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        db_col = field.upper()
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()

        source_ids_str = [str(s).strip() for s in source_ids]
        placeholders = ', '.join(['%s'] * len(source_ids_str))

        # Find matching records not already set to 1
        cursor.execute(
            f"SELECT ID, SOURCE_ID, SOURCE_SSN FROM {table} "
            f"WHERE SOURCE_ID IN ({placeholders}) AND {db_col} != 1",
            source_ids_str,
        )
        rows_to_update = cursor.fetchall()

        if not rows_to_update:
            return jsonify({'success': True, 'updated': 0,
                            'message': 'No new matches found.'})

        batch = [
            {
                'record_id': row[0],
                'source_id': str(row[1]),
                'source_ssn': str(row[2]),
                'fields': {field: ('0', 1)},
            }
            for row in rows_to_update
        ]

        user_id, user_name = _get_user_identity()
        save_records_batch(DATA_CONFIG, batch, user_id=user_id, user_name=user_name)

        # Update hot cache
        with _bucket_cache_lock:
            if _bucket_cache is not None:
                for b in batch:
                    _bucket_cache.update_row(b['record_id'], field, 1)

        return jsonify({
            'success': True,
            'updated': len(batch),
            'total_in_file': len(source_ids_str),
            'message': f'Set {field.upper()} for {len(batch)} records',
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 6: Replace `/api/save_changes` with no-op stub**

Find and replace the `save_changes()` function with:

```python
@app.route('/api/save_changes', methods=['POST'])
def save_changes():
    """No-op stub — all saves are now immediate. Kept for backward compatibility."""
    return jsonify({'success': True, 'saved': 0, 'pending_count': 0,
                    'message': 'All changes are saved immediately'})
```

- [ ] **Step 7: Update `/api/stage_approved` to remove pending-changes guard**

In `stage_approved()`, remove these lines:

```python
        if _pending_changes:
            return jsonify({
                'error': 'Save your pending changes before staging'
            }), 400
```

And change `load_cached_data(force_reload=True)` to `_invalidate_cache()`:

```python
        _invalidate_cache()
```

Also, `stage_approved_records()` currently takes `df` as a parameter. Since we no longer have a full in-memory df, we need to pass it the conn and let it run SQL directly. For now, replace the `stage_approved_records` call with the SQL it needs. Find this block:

```python
        df = load_cached_data()
        staged = stage_approved_records(DATA_CONFIG, df)
```

Replace with:

```python
        staged = stage_approved_records(DATA_CONFIG, df=None)
```

Then update `stage_approved_records` in `data_loader.py` to accept `df=None` and when `df` is None, build the eligible list via SQL. Add this at the top of `stage_approved_records`:

```python
    if df is None:
        # Load eligible records from Snowflake directly
        conn = get_snowflake_connection(config)
        cursor_check = conn.cursor()
        cursor_check.execute(
            f"SELECT SOURCE_ID, SOURCE_SSN FROM {table} "
            f"WHERE UPPER(RECOMMENDATION) = 'APPROVED' "
            f"AND HOW_TO_PROCESS IS NOT NULL AND TRIM(HOW_TO_PROCESS) != ''"
        )
        rows = cursor_check.fetchall()
        if not rows:
            return 0
        import pandas as _pd
        df = _pd.DataFrame(rows, columns=['source_id', 'source_ssn'])
```

- [ ] **Step 8: Smoke test**

```bash
cd /c/ClaudeMain/BA_Review_App && python -c "import app; print('app imports OK')"
```
Expected: `app imports OK`

- [ ] **Step 9: Commit**

```bash
git add app.py data_loader.py
git commit -m "feat: replace all save endpoints with immediate Snowflake writes; remove _pending_changes"
```

---

## Task 9: Add new endpoints — bucket counts, cache status, user identity

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add `/api/bucket-counts` endpoint**

Add after the `reload_data()` route:

```python
@app.route('/api/bucket-counts')
def bucket_counts():
    """Return record count per recommendation bucket."""
    try:
        counts = get_bucket_counts(DATA_CONFIG)
        return jsonify(counts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cache-status')
def cache_status():
    """Return current cache state for the mode badge."""
    import datetime
    with _bucket_cache_lock:
        if _bucket_cache is None:
            return jsonify({'mode': 'sql', 'bucket': None, 'row_count': 0,
                            'load_time': None, 'fresh': False})
        return jsonify({
            'mode': 'cached',
            'bucket': _bucket_cache.bucket,
            'row_count': _bucket_cache.row_count,
            'load_time': _bucket_cache.load_time.isoformat(),
            'fresh': _bucket_cache.is_fresh(CACHE_TTL_SECONDS),
        })


@app.route('/api/user-info')
def user_info():
    """Return the current user's identity from cookies."""
    user_id, user_name = _get_user_identity()
    return jsonify({
        'user_id': user_id,
        'user_name': user_name or '',
        'is_new': user_id is None,
    })


@app.route('/api/set-username', methods=['POST'])
def set_username():
    """Acknowledge a username change (client sets cookie itself)."""
    data = request.json or {}
    name = str(data.get('user_name', '')).strip()[:50]
    if not name:
        return jsonify({'error': 'Name cannot be empty'}), 400
    return jsonify({'success': True, 'user_name': name})
```

- [ ] **Step 2: Smoke test**

```bash
cd /c/ClaudeMain/BA_Review_App && python -c "import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add /api/bucket-counts, /api/cache-status, /api/user-info, /api/set-username endpoints"
```

---

## Task 10: Frontend — update save AJAX calls to include `id`, `source_id`, `source_ssn`, `old_value`

**Files:**
- Modify: `static/js/app.js`

This task updates every AJAX call that posts to `/api/update` or `/api/bulk_update` to include the new required fields. The row data object (`params.data` in AG Grid) already contains `id`, `source_id`, and `source_ssn`.

- [ ] **Step 1: Find all `/api/update` call sites and add `id`, `source_id`, `source_ssn`, `old_value`**

There are several call sites. For each, the change is the same pattern:

**Old pattern (every `/api/update` call):**
```javascript
data: JSON.stringify({ row_id: <row_id>, field: <field>, value: <value> }),
```

**New pattern:**
```javascript
data: JSON.stringify({ row_id: <row_id>, id: <id>, source_id: <source_id>, source_ssn: <source_ssn>, field: <field>, value: <value>, old_value: <old_value> }),
```

Open `static/js/app.js`. Find each `/api/update` call and apply the pattern. The key is where to get `id`, `source_id`, `source_ssn`, and `old_value` for each call site:

**Call site 1 — AG Grid cell edit (around line 582):**
The `params` object has `params.data` with all row fields.
```javascript
// Change:
data: JSON.stringify({ row_id: params.data._row_id, field: fld, value: params.newValue || '' }),
// To:
data: JSON.stringify({
    row_id: params.data._row_id,
    id: params.data.id,
    source_id: params.data.source_id,
    source_ssn: params.data.source_ssn,
    field: fld,
    value: params.newValue || '',
    old_value: params.oldValue || '',
}),
```

**Call site 2 — process-select change (around line 863, uses `rowId` and `rowData`):**
The code that calls `updateField(rowId, field, value)` — update the `updateField` helper function itself. Find the `updateField` function definition and add the extra fields. The function likely looks up row data from the grid. Add a `rowData` parameter:
```javascript
// Change the updateField helper to accept and pass rowData:
function updateField(rowId, field, value, rowData, oldValue) {
    rowData = rowData || {};
    $.ajax({
        url: '/api/update', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({
            row_id: rowId,
            id: rowData.id || rowId,
            source_id: rowData.source_id || '',
            source_ssn: rowData.source_ssn || '',
            field: field,
            value: value,
            old_value: oldValue || '',
        }),
        success: function(data) { updateSaveBtn && updateSaveBtn(); },
        error: function(xhr) { showToast('Save failed: ' + (xhr.responseJSON && xhr.responseJSON.error || 'Unknown error'), 'danger'); }
    });
}
```

Then update every call to `updateField(rowId, field, value)` to pass the row data. For calls inside AG Grid callbacks, get the row data with:
```javascript
var node = gridApi.getRowNode(String(rowId));
var rowData = node ? node.data : {};
```

**Call site 3 — edit modal save (around line 1247):**
The modal stores `d._row_id` in `#editRowId`. Also store `d.id`, `d.source_id`, `d.source_ssn` in hidden fields:
```javascript
// In the modal open code (around line 1186), add:
$('#editRecordId').val(d.id);
$('#editSourceId').val(d.source_id);
$('#editSourceSsn').val(d.source_ssn);
```
Then in the modal save handler:
```javascript
data: JSON.stringify({
    row_id: rowId,
    id: $('#editRecordId').val(),
    source_id: $('#editSourceId').val(),
    source_ssn: $('#editSourceSsn').val(),
    field: field,
    value: value,
    old_value: oldValue,
}),
```

**Call site 4 — quick approve button (around line 1284):**
```javascript
// Change:
data: JSON.stringify({ row_id: rowId, field: 'recommendation', value: 'APPROVED' }),
// To (rowData from grid node):
var approveNode = gridApi.getRowNode(String(rowId));
var approveData = approveNode ? approveNode.data : {};
data: JSON.stringify({
    row_id: rowId, id: approveData.id, source_id: approveData.source_id,
    source_ssn: approveData.source_ssn, field: 'recommendation',
    value: 'APPROVED', old_value: approveData.recommendation || '',
}),
```

**Call site 5 — undo/redo (around line 1008):**
Each undo change has `ch.rowId`. Get the row data from the grid:
```javascript
var undoNode = gridApi.getRowNode(String(ch.rowId));
var undoData = undoNode ? undoNode.data : {};
data: JSON.stringify({
    row_id: ch.rowId, id: undoData.id, source_id: undoData.source_id,
    source_ssn: undoData.source_ssn, field: ch.field,
    value: val, old_value: (direction === 'undo' ? ch.newValue : ch.oldValue),
}),
```

- [ ] **Step 2: Update `/api/bulk_update` calls to include record identity**

Find the bulk approve call (around line 1316):
```javascript
// Change:
data: JSON.stringify({ row_ids: Array.from(selectedRows), recommendation: 'APPROVED', process_values: processValues }),
// To:
var bulkRecords = [];
gridApi.forEachNode(function(node) {
    if (node.data && selectedRows.has(node.data._row_id)) {
        bulkRecords.push({
            id: node.data.id,
            source_id: node.data.source_id,
            source_ssn: node.data.source_ssn,
            old_recommendation: node.data.recommendation || '',
        });
    }
});
data: JSON.stringify({ records: bulkRecords, recommendation: 'APPROVED', process_values: processValues }),
```

- [ ] **Step 3: Remove `pendingCount` and `updateSaveBtn` references**

Find the `pendingCount` variable declaration and `updateSaveBtn` function. Remove them. Replace every `pendingCount = data.pending_count || 0; updateSaveBtn();` with a comment `// immediate save — no pending state`.

- [ ] **Step 4: Add a `showToast()` helper if not already present**

Check whether `showToast` already exists in `app.js`. If not, add:

```javascript
function showToast(message, type) {
    type = type || 'success';
    var toast = $('<div class="toast align-items-center text-bg-' + type + ' border-0 show" role="alert" aria-live="assertive" aria-atomic="true" style="position:fixed;bottom:1rem;right:1rem;z-index:9999;min-width:250px;">' +
        '<div class="d-flex"><div class="toast-body">' + message + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>');
    $('body').append(toast);
    setTimeout(function() { toast.remove(); }, 3000);
}
```

- [ ] **Step 5: Update the success callback on every save to show a toast**

For `/api/update` success callbacks, change:
```javascript
success: function(data) { pendingCount = data.pending_count || 0; updateSaveBtn(); },
```
to:
```javascript
success: function(data) { showToast('Saved', 'success'); },
error: function(xhr) { showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); },
```

- [ ] **Step 6: Commit**

```bash
git add static/js/app.js
git commit -m "feat: update all save calls to include id/source_id/source_ssn; remove pending state tracking"
```

---

## Task 11: Frontend — user identity UI (banner, username modal, nav display)

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: Add hidden fields for modal record identity and user identity elements to `index.html`**

In the edit modal (`#editModal`), inside the modal body, add hidden inputs after `<input type="hidden" id="editRowId">`:

```html
<input type="hidden" id="editRecordId">
<input type="hidden" id="editSourceId">
<input type="hidden" id="editSourceSsn">
```

Add the first-visit identity banner just below the opening `<body>` tag (or just before the main navbar):

```html
<!-- User identity banner — hidden after name is set -->
<div id="identityBanner" class="alert alert-info alert-dismissible mb-0 py-2 px-3 rounded-0 d-none" role="alert">
  You're reviewing as <strong id="identityDisplayName">Guest</strong>.
  <a href="#" id="setNameLink" class="alert-link ms-2">Set your name</a>
  <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
</div>
```

Add the username modal (place near other modals at end of body):

```html
<!-- Username Modal -->
<div class="modal fade" id="usernameModal" tabindex="-1" aria-labelledby="usernameModalLabel" aria-hidden="true">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="usernameModalLabel">Set your display name</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <input type="text" id="usernameInput" class="form-control" placeholder="Your name" maxlength="50">
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-primary" id="saveUsernameBtn">Save</button>
      </div>
    </div>
  </div>
</div>
```

Add a small name display to the navbar (in `<nav>`, near the end of the nav items):

```html
<span class="navbar-text ms-3 text-muted small" id="navUserName"></span>
```

- [ ] **Step 2: Add user identity JavaScript to `app.js`**

Add at the top of the document-ready block (`$(function() {`):

```javascript
// --- User identity ---
function getCookie(name) {
    var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return match ? decodeURIComponent(match[1]) : null;
}
function setCookie(name, value, days) {
    var expires = new Date(Date.now() + days * 864e5).toUTCString();
    document.cookie = name + '=' + encodeURIComponent(value) + '; expires=' + expires + '; path=/; SameSite=Lax';
}

function initUserIdentity() {
    var userId = getCookie('user_id');
    var userName = getCookie('user_name');

    if (!userId) {
        // Generate a UUID and set it (server also sets it on page load,
        // but set client-side as a fallback)
        userId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
        setCookie('user_id', userId, 365);
    }

    if (!userName) {
        $('#identityBanner').removeClass('d-none');
        $('#identityDisplayName').text('Guest');
    } else {
        $('#navUserName').text(userName);
        $('#identityDisplayName').text(userName);
    }
}

$('#setNameLink').on('click', function(e) {
    e.preventDefault();
    $('#usernameInput').val(getCookie('user_name') || '');
    new bootstrap.Modal(document.getElementById('usernameModal')).show();
});

$('#saveUsernameBtn').on('click', function() {
    var name = $('#usernameInput').val().trim().slice(0, 50);
    if (!name) return;
    setCookie('user_name', name, 365);
    $('#navUserName').text(name);
    $('#identityDisplayName').text(name);
    $('#identityBanner').addClass('d-none');
    bootstrap.Modal.getInstance(document.getElementById('usernameModal')).hide();
    showToast('Name saved: ' + name, 'success');
});

initUserIdentity();
```

- [ ] **Step 3: Commit**

```bash
git add templates/index.html static/js/app.js
git commit -m "feat: add user identity banner, username modal, and nav display"
```

---

## Task 12: Frontend — bucket count badges, mode badge, loading spinner

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: Add count badge spans to recommendation filter buttons in `index.html`**

Find the recommendation filter buttons in the HTML (they look like `REVIEW`, `AUTO_MERGE`, etc.). Add a `<span>` badge inside each button. Example:

```html
<!-- Change existing button text from e.g.: -->
<button ... data-value="REVIEW">REVIEW</button>
<!-- To: -->
<button ... data-value="REVIEW">REVIEW <span class="badge bg-secondary bucket-count" data-bucket="REVIEW"></span></button>
```

Apply the same pattern to all recommendation filter buttons.

- [ ] **Step 2: Add mode badge and loading indicator to the toolbar**

In the toolbar area (near the search input or filter controls), add:

```html
<span id="cacheModeBadge" class="badge bg-info text-dark ms-2" title="Data source mode" style="display:none;"></span>
<span id="cacheLoadingBadge" class="badge bg-warning text-dark ms-2" style="display:none;">
  <span class="spinner-border spinner-border-sm me-1" role="status"></span>Loading…
</span>
```

- [ ] **Step 3: Add bucket count polling and mode badge update to `app.js`**

Add this function and call it on page load:

```javascript
function refreshBucketCounts() {
    $.get('/api/bucket-counts', function(counts) {
        $('.bucket-count').each(function() {
            var bucket = $(this).data('bucket');
            var count = counts[bucket];
            $(this).text(count !== undefined ? count.toLocaleString() : '');
        });
    });
}

function refreshCacheStatus() {
    $.get('/api/cache-status', function(status) {
        var badge = $('#cacheModebadge, #cacheModeBadge');
        if (status.mode === 'cached') {
            badge.text('Cached').removeClass('bg-secondary').addClass('bg-info text-dark').show();
        } else {
            badge.text('Live query').removeClass('bg-info text-dark').addClass('bg-secondary').show();
        }
    });
}

// Initial load
refreshBucketCounts();
refreshCacheStatus();

// Refresh counts every 5 minutes
setInterval(refreshBucketCounts, 5 * 60 * 1000);
setInterval(refreshCacheStatus, 60 * 1000);
```

Also refresh bucket counts after every save:
```javascript
// In the save success callback:
success: function(data) { showToast('Saved', 'success'); refreshBucketCounts(); },
```

- [ ] **Step 4: Show loading spinner on bucket switch**

Find where recommendation filter buttons trigger a grid reload. Add show/hide of `#cacheLoadingBadge`:

```javascript
// When recommendation filter button is clicked:
$('#cacheLoadingBadge').show();
// After grid data loads (in the DataTables / AG Grid data callback):
$('#cacheLoadingBadge').hide();
refreshCacheStatus();
```

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/js/app.js
git commit -m "feat: add bucket count badges, cache mode badge, and loading spinner"
```

---

## Task 13: Frontend — remove Save All button and pending-count UI

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: Remove Save All button and pending-count indicator from `index.html`**

Find and remove the "Save All Changes" button and any `id="pendingCount"` or similar unsaved-changes counter elements from the HTML.

- [ ] **Step 2: Add a Refresh button**

In the toolbar, add a Refresh button:

```html
<button id="refreshCacheBtn" class="btn btn-outline-secondary btn-sm" title="Reload current bucket from Snowflake">
  <i class="fas fa-sync-alt"></i> Refresh
</button>
```

- [ ] **Step 3: Wire up Refresh button in `app.js`**

```javascript
$('#refreshCacheBtn').on('click', function() {
    var btn = $(this);
    btn.prop('disabled', true);
    $('#cacheLoadingBadge').show();
    $.ajax({
        url: '/api/reload', method: 'POST', contentType: 'application/json',
        success: function(data) {
            showToast('Refreshed — ' + (data.records || 0).toLocaleString() + ' total records', 'success');
            // Reload the grid
            if (typeof gridApi !== 'undefined') { gridApi.purgeInfiniteCache ? gridApi.purgeInfiniteCache() : gridApi.refreshInfiniteCache(); }
            refreshBucketCounts();
            refreshCacheStatus();
        },
        error: function() { showToast('Refresh failed', 'danger'); },
        complete: function() { btn.prop('disabled', false); $('#cacheLoadingBadge').hide(); }
    });
});
```

- [ ] **Step 4: Remove any `updateSaveBtn()` function definition and all calls to it**

Search `app.js` for `updateSaveBtn` and `pendingCount` — delete all occurrences.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/js/app.js
git commit -m "feat: remove Save All button; add Refresh button; auto-refresh bucket counts"
```

---

## Task 14: End-to-end verification

**Files:**
- Read: `tests/unit/` — run all unit tests
- Read: Playwright tests — run key smoke tests

- [ ] **Step 1: Run all unit tests**

```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/unit/ -v
```
Expected: all `PASSED`

- [ ] **Step 2: Run existing Playwright smoke tests against the running app**

Start the app in one terminal:
```bash
cd /c/ClaudeMain/BA_Review_App && python app.py
```

In another terminal:
```bash
cd /c/ClaudeMain/BA_Review_App && python -m pytest tests/test_01_page_load.py tests/test_02_filtering.py tests/test_15_save_changes.py -v
```
Expected: `test_15_save_changes` tests that check for "Save All" button may fail — update them to remove that assertion (the button no longer exists). All other tests should pass.

- [ ] **Step 3: Fix any failing Playwright tests caused by removed Save All button**

In `tests/test_15_save_changes.py`, remove or update assertions that check for the Save All button or pending count badge. Replace with assertions that verify the toast message appears after a save.

- [ ] **Step 4: Final commit**

```bash
git add tests/
git commit -m "test: update save tests for immediate-write behavior; all tests passing"
```
