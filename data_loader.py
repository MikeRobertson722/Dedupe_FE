"""
Data Source Abstraction Layer
Supports loading data from Snowflake
"""
import os
import time
import logging
import threading
import datetime
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


# Persistent Snowflake connection — avoids repeated SSO browser popups
_sf_conn = None
_sf_config_hash = None
_sf_conn_verified_at = 0  # timestamp of last successful health check
_SF_CONN_TTL = 600        # seconds to trust a connection without re-checking

import re as _re
_VALID_IDENTIFIER = _re.compile(r'^[A-Z0-9_]+$')


def _safe_table(name: str) -> str:
    """Validate and return an uppercase Snowflake identifier (prevents SQL injection via table name)."""
    upper = name.upper()
    if not _VALID_IDENTIFIER.match(upper):
        raise ValueError(f"Invalid table identifier: {name!r}")
    return upper


# Thread safety for connection management
_conn_lock = threading.Lock()

# BucketCache configuration
BUCKET_CACHE_MAX_ROWS = 100_000


def _build_conn_params(config: Dict[str, Any]) -> dict:
    """Build Snowflake connection parameters from config + env vars."""
    authenticator = os.environ.get('SNOWFLAKE_AUTHENTICATOR', config.get('authenticator', ''))

    conn_params = {
        'account': os.environ.get('SNOWFLAKE_ACCOUNT', config.get('account', '')),
        'user': os.environ.get('SNOWFLAKE_USER', config.get('user', '')),
        'database': os.environ.get('SNOWFLAKE_DATABASE', config.get('database', '')),
        'schema': os.environ.get('SNOWFLAKE_SCHEMA', config.get('schema', '')),
    }

    if authenticator:
        conn_params['authenticator'] = authenticator
        conn_params['client_store_temporary_credential'] = True
        conn_params['client_session_keep_alive'] = True
    else:
        conn_params['password'] = os.environ.get('SNOWFLAKE_PASSWORD', config.get('password', ''))

    wh = os.environ.get('SNOWFLAKE_WAREHOUSE', config.get('warehouse'))
    if wh:
        conn_params['warehouse'] = wh
    role = os.environ.get('SNOWFLAKE_ROLE', config.get('role'))
    if role:
        conn_params['role'] = role

    return conn_params


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
            age = time.time() - _sf_conn_verified_at
            if age < _SF_CONN_TTL:
                return _sf_conn
            try:
                _sf_conn.cursor().execute("SELECT 1")
                _sf_conn_verified_at = time.time()
                logger.debug("Snowflake connection health check passed (age %.0fs)", age)
                return _sf_conn
            except Exception as e:
                logger.warning("Snowflake connection health check failed (age %.0fs): %s", age, e)
                try:
                    _sf_conn.close()
                except Exception:
                    pass
                _sf_conn = None

        logger.info("Creating new Snowflake connection (authenticator=%s)",
                     conn_params.get('authenticator', 'password'))
        _sf_conn = connector.connect(**conn_params)
        _sf_config_hash = config_hash
        _sf_conn_verified_at = time.time()
        logger.info("Snowflake connection established successfully")
        return _sf_conn


class DataSource:
    """Data source that returns consistent DataFrame structure"""

    @staticmethod
    def load_from_snowflake(config: Dict[str, Any]) -> pd.DataFrame:
        """
        Load data from Snowflake.

        Args:
            config: Dict with account, user, password, database, schema, table, warehouse keys

        Returns:
            DataFrame with import_merge_matches data
        """
        table = config.get('table', 'import_merge_matches')
        conn = get_snowflake_connection(config)
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            # Snowflake uppercases column names by default — normalize to lowercase
            df.columns = df.columns.str.lower()
            return DataSource._normalize_dataframe(df)
        except Exception as e:
            print(f"Error loading from Snowflake: {e}")
            return pd.DataFrame()

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure consistent column names, data types, and required columns.
        Handles column mapping for tables with different schemas (e.g. dec_ba_master).
        """
        # Detect dec_ba_master schema and map columns to expected grid structure
        if 'hdrcode' in df.columns and 'source_id' not in df.columns:
            column_map = {
                'hdrcode': 'dec_hdrcode',
                'ssn': 'source_ssn',
                'hdrname': 'dec_name',
                'addrcontact': 'dec_contact',
                'addraddress': 'dec_address',
                'addrcity': 'dec_city',
                'addrstate': 'dec_state',
                'addrzipcode': 'dec_zip',
                'addrsubcode': 'dec_addrsubcode',
            }
            df = df.rename(columns=column_map)

            for col in ('source_id', 'source_name', 'source_address',
                        'source_city', 'source_state', 'source_zip'):
                if col not in df.columns:
                    df[col] = ''

            if 'ssn_match' not in df.columns:
                df['ssn_match'] = 0
            if 'name_score' not in df.columns:
                df['name_score'] = 0
            if 'address_score' not in df.columns:
                df['address_score'] = 0
            if 'recommendation' not in df.columns:
                df['recommendation'] = ''
            if 'address_reason' not in df.columns:
                df['address_reason'] = ''

        # Ensure jib, rev, vendor columns exist (defaulting to 0)
        for col in ('jib', 'rev', 'vendor'):
            if col not in df.columns:
                df[col] = 0

        # Convert boolean columns to int if needed
        for col in ('jib', 'rev', 'vendor'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

        if 'how_to_process' not in df.columns:
            df['how_to_process'] = ''

        if 'memo' not in df.columns:
            df['memo'] = ''

        # Ensure numeric columns are properly typed
        numeric_cols = ['ssn_match', 'name_score', 'address_score', 'nameaddrscore']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df


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

    @property
    def row_count(self) -> int:
        return len(self.df)

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


def ensure_snowflake_schema(config: Dict[str, Any]) -> None:
    """
    Ensure Snowflake tables have all required columns and the UPDATE_LOG table exists.
    """
    table = config.get('table', 'import_merge_matches').upper()
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()

    # Check existing columns on main table
    cursor.execute(f"DESCRIBE TABLE {table}")
    existing_cols = {row[0].lower() for row in cursor.fetchall()}

    # Rename CANVAS_* → SOURCE_* columns (one-time migration, safe to re-run)
    canvas_to_source = {
        'CANVAS_ID': 'SOURCE_ID',
        'CANVAS_SSN': 'SOURCE_SSN',
        'CANVAS_NAME': 'SOURCE_NAME',
        'CANVAS_ADDRESS': 'SOURCE_ADDRESS',
        'CANVAS_CITY': 'SOURCE_CITY',
        'CANVAS_STATE': 'SOURCE_STATE',
        'CANVAS_ZIP': 'SOURCE_ZIP',
        'CANVAS_ADDRSEQ': 'SOURCE_ADDRSEQ',
    }
    for old_col, new_col in canvas_to_source.items():
        if old_col.lower() in existing_cols and new_col.lower() not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}")
                existing_cols.discard(old_col.lower())
                existing_cols.add(new_col.lower())
            except Exception as e:
                print(f"  Column rename {old_col}→{new_col} skipped: {e}")

    # Add missing columns
    needed = {
        'jib': 'NUMBER DEFAULT 0',
        'rev': 'NUMBER DEFAULT 0',
        'vendor': 'NUMBER DEFAULT 0',
        'memo': "VARCHAR DEFAULT ''",
        'how_to_process': "VARCHAR DEFAULT ''",
    }
    for col, col_type in needed.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col.upper()} {col_type}")

    # Ensure UPDATE_LOG table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS UPDATE_LOG (
            ID NUMBER AUTOINCREMENT,
            SOURCE_ID VARCHAR,
            SOURCE_SSN VARCHAR,
            FIELD_NAME VARCHAR,
            OLD_VALUE VARCHAR,
            NEW_VALUE VARCHAR,
            UPDATED_AT TIMESTAMP_NTZ,
            CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)

    # Rename UPDATE_LOG columns (one-time migration, safe to re-run)
    try:
        cursor.execute("DESCRIBE TABLE UPDATE_LOG")
        log_cols = {row[0].lower() for row in cursor.fetchall()}
        if 'canvas_id' in log_cols and 'source_id' not in log_cols:
            cursor.execute("ALTER TABLE UPDATE_LOG RENAME COLUMN CANVAS_ID TO SOURCE_ID")
        if 'canvas_ssn' in log_cols and 'source_ssn' not in log_cols:
            cursor.execute("ALTER TABLE UPDATE_LOG RENAME COLUMN CANVAS_SSN TO SOURCE_SSN")
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
    except Exception as e:
        print(f"  UPDATE_LOG column rename skipped: {e}")

    # Ensure GRID_SETTINGS table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS GRID_SETTINGS (
            SETTING_KEY   VARCHAR(100)   NOT NULL,
            SETTING_VALUE VARCHAR(65535) NOT NULL,
            UPDATED_AT    TIMESTAMP_NTZ  DEFAULT CURRENT_TIMESTAMP(),
            CONSTRAINT PK_GRID_SETTINGS PRIMARY KEY (SETTING_KEY)
        )
    """)

    # Ensure IMPORT_MERGE_STAGING table exists (mirrors source + metadata)
    staging_table = table.replace('MATCHES', 'STAGING')
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {staging_table} LIKE {table}
    """)
    # Add staging metadata columns if missing
    cursor.execute(f"DESCRIBE TABLE {staging_table}")
    staging_cols = {row[0].lower() for row in cursor.fetchall()}
    staging_meta = {
        'STAGED_AT': 'TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()',
        'STAGED_BY': 'VARCHAR',
        'SOURCE_TABLE': f"VARCHAR DEFAULT '{table}'",
    }
    for col, col_type in staging_meta.items():
        if col.lower() not in staging_cols:
            try:
                cursor.execute(f"ALTER TABLE {staging_table} ADD COLUMN {col} {col_type}")
                print(f"  Added {col} to {staging_table}")
            except Exception as e:
                print(f"  Adding {col} to {staging_table} skipped: {e}")

    conn.commit()


def get_bucket_counts(config: Dict[str, Any]) -> Dict[str, int]:
    """
    Return a dict of {recommendation_value: row_count} for all buckets.
    Uses a single GROUP BY query — fast even on 2M rows.
    """
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    try:
        table = _safe_table(config.get('table', 'import_merge_matches'))
        cursor.execute(
            f"SELECT RECOMMENDATION, COUNT(*) AS CNT "
            f"FROM {table} "
            f"GROUP BY RECOMMENDATION"
        )
        return {row[0]: int(row[1]) for row in cursor.fetchall() if row[0] is not None}
    finally:
        cursor.close()


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

# Columns safe to sort by (prevents SQL injection via ORDER BY).
# 'master' is the computed window-function alias added in query_snowflake_page;
# the outer SELECT sees it as a column and can sort on it.
_SORTABLE_COLS = {
    'id', 'ssn_match', 'name_score', 'address_score', 'nameaddrscore',
    'recommendation', 'source_name', 'source_address', 'source_city',
    'source_state', 'source_zip', 'source_id', 'source_addrseq',
    'dec_name', 'dec_address', 'dec_city', 'dec_state', 'dec_zip',
    'dec_hdrcode', 'dec_address_looked_up', 'jib', 'rev', 'vendor',
    'how_to_process', 'memo', 'address_reason', 'run_id', 'master',
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
    table = _safe_table(config.get('table', 'import_merge_matches'))
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    try:
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

        # NOTE: previously we excluded STAGED rows when the user hadn't picked
        # an explicit recommendation filter ("hide_staged" default). That was
        # misleading — the dropdown said "All" but the result wasn't all, and
        # when every row in the table happens to be STAGED (e.g. right after
        # a big stage-approved batch) the grid went blank with no explanation.
        # "All" now literally means all. Users who want to hide STAGED can
        # check the non-STAGED recommendation values in the rec filter dropdown.

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

        if length == -1:
            limit_sql = f'LIMIT {BUCKET_CACHE_MAX_ROWS} OFFSET {int(start)}'
        else:
            limit_sql = f'LIMIT {int(length)} OFFSET {int(start)}'

        # MASTER is a derived survivor flag: per DEC_HDRCODE group, the row with
        # the highest NAMEADDRSCORE (ties: lowest ID) is TRUE; the rest FALSE.
        # Rows with empty DEC_HDRCODE have no duplicates by definition → TRUE.
        # Computed in an inner SELECT so the partitioning sees the whole table,
        # not the filtered set — MASTER is globally stable across filter changes.
        master_expr = (
            "CASE "
            "WHEN NULLIF(DEC_HDRCODE, '') IS NULL THEN TRUE "
            "WHEN ROW_NUMBER() OVER ("
            "PARTITION BY DEC_HDRCODE "
            "ORDER BY NAMEADDRSCORE DESC NULLS LAST, ID ASC"
            ") = 1 THEN TRUE "
            "ELSE FALSE END AS MASTER"
        )

        cursor.execute(
            f'SELECT * FROM ('
            f' SELECT {col_list}, {master_expr} FROM {table}'
            f') sub {where_sql} {order_sql} {limit_sql}',
            params,
        )
        col_names = [desc[0].lower() for desc in cursor.description]
        rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]

        return rows, total_count, filtered_count
    finally:
        cursor.close()


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

    table = _safe_table(config.get('table', 'import_merge_matches'))
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
    try:
        cursor.execute(sql, set_params)

        # Audit log — use execute() per entry so cursor.execute is visible to callers
        now = datetime.datetime.now()
        for field, change in fields.items():
            old_val, new_val = change if isinstance(change, tuple) else ('', change)
            cursor.execute(
                """INSERT INTO UPDATE_LOG
                   (SOURCE_ID, SOURCE_SSN, FIELD_NAME, OLD_VALUE, NEW_VALUE, UPDATED_AT,
                    USER_ID, USER_NAME)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (str(source_id), str(source_ssn), field,
                 str(old_val), str(new_val), now, user_id, user_name),
            )
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


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

    from collections import defaultdict
    groups: Dict[frozenset, List[dict]] = defaultdict(list)
    for rec in records:
        key = frozenset(rec['fields'].keys())
        groups[key].append(rec)

    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    table = _safe_table(config.get('table', 'import_merge_matches'))
    total_affected = 0
    now = datetime.datetime.now()
    all_log_entries = []

    try:
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

            value_sets = set()
            for rec in group:
                vals = tuple(
                    (rec['fields'][f][1] if isinstance(rec['fields'][f], tuple)
                     else rec['fields'][f])
                    for f in fields_list
                )
                value_sets.add(vals)

            if len(value_sets) == 1:
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
                for rec in group:
                    affected = save_record_immediately(
                        config, rec['record_id'], rec['source_id'], rec['source_ssn'],
                        rec['fields'], user_id=user_id, user_name=user_name,
                    )
                    total_affected += affected
                continue

            for rec in group:
                for field, change in rec['fields'].items():
                    old_val, new_val = change if isinstance(change, tuple) else ('', change)
                    all_log_entries.append((
                        str(rec['source_id']), str(rec['source_ssn']), field,
                        str(old_val), str(new_val), now, user_id, user_name,
                    ))

        if all_log_entries:
            cursor.executemany(
                "INSERT INTO UPDATE_LOG "
                "(SOURCE_ID, SOURCE_SSN, FIELD_NAME, OLD_VALUE, NEW_VALUE, UPDATED_AT, USER_ID, USER_NAME) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                all_log_entries,
            )
        conn.commit()
        return total_affected
    finally:
        cursor.close()


def merge_changes_to_snowflake(
    config: Dict[str, Any],
    pending_changes: Dict[int, Dict[str, Any]],
    df: pd.DataFrame,
    cursor=None
) -> int:
    """
    Persist pending changes to Snowflake via a single MERGE statement.

    Args:
        config: Snowflake connection config
        pending_changes: {row_id: {field: (old_value, new_value), ...}, ...}
        df: Current in-memory DataFrame (to look up source_id/source_ssn)
        cursor: Optional shared cursor (caller manages commit)

    Returns:
        Number of rows affected
    """
    if not pending_changes:
        return 0

    table = config.get('table', 'import_merge_matches').upper()

    # Map in-memory field names to Snowflake column names where they differ
    field_to_db_col = {
        'source_address_recomend': 'source_address',
    }

    # Collect all fields being updated across all rows
    all_fields = set()
    for fields in pending_changes.values():
        all_fields.update(fields.keys())
    all_fields = sorted(all_fields)

    # Integer fields (booleans stored as 0/1); everything else is VARCHAR.
    # CASTs go directly into the VALUES row placeholders so Snowflake can type
    # every column even when all values for that column happen to be NULL
    # (error "invalid data type [unknown]" occurs when type can't be inferred).
    db_cols = [field_to_db_col.get(f, f).upper() for f in all_fields]
    int_db_cols = {'JIB', 'REV', 'VENDOR'}

    def _cast_ph(db_col: str) -> str:
        return 'CAST(%s AS INTEGER)' if db_col in int_db_cols else 'CAST(%s AS VARCHAR)'

    def _coerce(value, db_col: str):
        """Normalise Python/pandas values to types the Snowflake connector handles."""
        import math
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0 if db_col in int_db_cols else ''
        if db_col in int_db_cols:
            return int(value)
        return str(value)

    # Build value rows and flat params for a single MERGE
    placeholders = []
    params: list = []
    for row_id, fields in pending_changes.items():
        cid = str(df.at[row_id, 'source_id'])
        ssn = str(df.at[row_id, 'source_ssn'])
        row_ph = ['CAST(%s AS VARCHAR)', 'CAST(%s AS VARCHAR)']
        params.extend([cid, ssn])
        for f, c in zip(all_fields, db_cols):
            entry = fields.get(f)
            if isinstance(entry, tuple):
                raw = entry[1]
            elif entry is not None:
                raw = entry
            else:
                raw = df.at[row_id, f] if f in df.columns else None
            params.append(_coerce(raw, c))
            row_ph.append(_cast_ph(c))
        placeholders.append('(' + ', '.join(row_ph) + ')')

    own_cursor = cursor is None
    if own_cursor:
        conn = get_snowflake_connection(config)
        cursor = conn.cursor()

    # Single MERGE: all rows in one statement
    src_cols = ['CID', 'SSN'] + db_cols
    select_clause = ', '.join(f'column{i + 1} AS {c}' for i, c in enumerate(src_cols))
    values_block = ', '.join(placeholders)
    set_clause = ', '.join(f't.{c} = s.{c}' for c in db_cols)

    sql = (
        f"MERGE INTO {table} t USING ("
        f"SELECT {select_clause} "
        f"FROM VALUES {values_block}"
        f") s ON t.SOURCE_ID = s.CID AND t.SOURCE_SSN = s.SSN "
        f"WHEN MATCHED THEN UPDATE SET {set_clause}"
    )

    cursor.execute(sql, params)
    affected = cursor.rowcount
    if own_cursor:
        conn.commit()
    return affected


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


def read_audit_log_from_snowflake(config: Dict[str, Any], limit: int = 100) -> list:
    """Read recent audit log entries from Snowflake."""
    from snowflake import connector as sf_connector
    conn = get_snowflake_connection(config)
    cursor = conn.cursor(sf_connector.DictCursor)
    cursor.execute(f"SELECT * FROM UPDATE_LOG ORDER BY UPDATED_AT DESC LIMIT {limit}")
    rows = cursor.fetchall()
    # Lowercase keys for consistency with frontend expectations
    return [{k.lower(): v for k, v in row.items()} for row in rows]


def count_staging_eligible(df: pd.DataFrame) -> int:
    """Count records eligible for staging (APPROVED with a Process value set,
    excluding 'Manual Review - DNP' which is intentionally not staged)."""
    mask = (
        (df['recommendation'].fillna('').str.upper() == 'APPROVED') &
        (df['how_to_process'].fillna('').str.strip() != '') &
        (df['how_to_process'] != 'Manual Review - DNP')
    )
    return int(mask.sum())


# ─────────────────────────────────────────────────────────────────────────────
# Staging column-length validation
# ─────────────────────────────────────────────────────────────────────────────
# STG_BA_MASTER columns are declared VARCHAR(N) in Snowflake. The N values are
# discovered at runtime via INFORMATION_SCHEMA — we never hardcode them in
# this file because the source of truth is the DDL. The functions below feed
# both:
#   1. Frontend cell-highlighting / pre-flight modal
#   2. The hard-block WHERE clause in stage_approved_records that physically
#      prevents an oversize value from reaching the staging table.

# Process-local cache of {STG_BA_MASTER_COL_NAME: CHARACTER_MAXIMUM_LENGTH}.
# Staging DDL is static during a session, so one lookup per process is enough.
_STAGING_LENGTHS_CACHE: Optional[Dict[str, int]] = None


def _build_column_specs() -> List[Tuple[str, str]]:
    """
    Return the (staging_col, select_expression) pairs that define how source
    rows in IMPORT_MERGE_MATCHES populate STG_BA_MASTER.

    Single source of truth used by both the INSERT in stage_approved_records
    and the LENGTH() hard-block predicates derived in get_source_field_limits
    and get_staging_overflows.

    For any base column whose `<base>_2` sibling exists in STG_BA_MASTER and
    isn't already explicitly mapped here, the same expression is mirrored into
    the _2 column at INSERT time (auto-mirror loop in stage_approved_records).
    SSN_2 is intentionally specified explicitly with its own digits-only
    transform, so the auto-mirror skips it.
    """
    return [
        ('ADDRADDRESS',     "NULLIF(SOURCE_ADDRESS_RECOMEND, '')"),
        ('ADDRCITY',        "NULLIF(SOURCE_CITY, '')"),
        ('ADDRCONTACT',     "NULLIF(SOURCE_NAME, '')"),
        ('ADDRCOUNTRY',     "'US'"),
        ('ADDRSEQ',         "NULLIF(DEC_ADDRSUBCODE, '')"),
        ('ADDRSEQ_SOURCE',  "NULLIF(SOURCE_ADDRSEQ, '')"),
        ('ADDRSTATE',       "NULLIF(SOURCE_STATE, '')"),
        # ADDRUNKNOWN is a VARCHAR(1) flag in staging: '1' when the source
        # VALID_ADDRESS is FALSE, '0' otherwise (incl. NULL/TRUE).
        # ADDRUNKNOWN_2 is auto-mirrored from this expression.
        ('ADDRUNKNOWN',     "CASE WHEN VALID_ADDRESS = FALSE THEN '1' ELSE '0' END"),
        ('ADDRZIPCODE',     "NULLIF(SOURCE_ZIP, '')"),
        ('ECODE',           "CASE WHEN HOW_TO_PROCESS IN ('Merge BA and address',\n"
                            "                                          'Add address to existing BA')\n"
                            "                     THEN NULLIF(DEC_HDRCODE, '')\n"
                            "                     ELSE NULL END"),
        ('ENTITY_LIST_NAME', "NULLIF(SOURCE_NAME, '')"),
        ('ENTTAXNAME',      "NULLIF(SOURCE_NAME, '')"),
        ('ETYPE',           "'BusAssoc'"),
        ('ID',              'DGO_MA.MA_STAGING.BA_MASTER_SQ.NEXTVAL'),
        ('IS_VENDOR',       'CASE WHEN VENDOR = 1 THEN TRUE ELSE NULL END'),
        ('JIBOWNER',        'TRUE'),
        ('LANDOWNER',       'TRUE'),
        ('LEGACY_ID',       "NULLIF(SOURCE_ID, '')"),
        ('LOAD_ME',         'TRUE'),
        ('MATCH_BY_ADDRESS', "CASE WHEN HOW_TO_PROCESS = 'Merge BA and address'\n"
                             "                     THEN TRUE ELSE FALSE END"),
        ('MATCH_BY_ENERTIA', "CASE WHEN HOW_TO_PROCESS IN ('Merge BA and address',\n"
                             "                                          'Add address to existing BA')\n"
                             "                     THEN TRUE ELSE FALSE END"),
        ('REVOWNER',        'TRUE'),
        ('SOURCESYSTEM',    "(SELECT CONFIG_VALUE FROM BA_CONFIG\n"
                            "                 WHERE CATEGORY = 'GENERAL' AND CONFIG_KEY = 'SOURCE_COMPANY_NAME')"),
        ('SOURCETABLE',     "(SELECT CONFIG_VALUE FROM BA_CONFIG\n"
                            "                 WHERE CATEGORY = 'GENERAL' AND CONFIG_KEY = 'SOURCE_COMPANY_NAME')"),
        ('SSN',             "NULLIF(SOURCE_SSN, '')"),
        ('SSN_2',           "NULLIF(REGEXP_REPLACE(SOURCE_SSN, '[^A-Za-z0-9]', ''), '')"),
        ('VALIDATION',      "'IMPORT_MERGE_MATCHES.ID = ' || CAST(ID AS VARCHAR)"),
        ('VENDOR',          'CASE WHEN VENDOR = 1 THEN TRUE ELSE FALSE END'),
    ]


def _expand_with_auto_mirror(
    column_specs: List[Tuple[str, str]],
    all_staging_cols: set,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """For each base column, if `<base>_2` exists in staging and isn't already
    explicit, append the same SELECT expression for it. Returns (expanded_list,
    list_of_auto_mirrored_col_names)."""
    explicit = {col for col, _ in column_specs}
    expanded: List[Tuple[str, str]] = []
    auto_mirrored: List[str] = []
    for col, expr in column_specs:
        expanded.append((col, expr))
        sibling = col + '_2'
        if sibling in all_staging_cols and sibling not in explicit:
            expanded.append((sibling, expr))
            auto_mirrored.append(sibling)
    return expanded, auto_mirrored


def get_staging_column_lengths(config: Dict[str, Any]) -> Dict[str, int]:
    """
    Return {STG_BA_MASTER_COL_NAME: CHARACTER_MAXIMUM_LENGTH} for every string
    column of DGO_MA.MA_STAGING.STG_BA_MASTER. Cached for the process lifetime.

    Boolean / numeric / sequence columns return no entry — they have no
    declared character length and aren't subject to overflow.
    """
    global _STAGING_LENGTHS_CACHE
    if _STAGING_LENGTHS_CACHE is not None:
        return _STAGING_LENGTHS_CACHE

    conn = get_snowflake_connection(config)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
            FROM DGO_MA.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'MA_STAGING'
              AND TABLE_NAME = 'STG_BA_MASTER'
              AND DATA_TYPE IN ('TEXT', 'VARCHAR', 'CHAR', 'STRING')
        """)
        result = {row[0].upper(): int(row[1]) for row in cur.fetchall() if row[1] is not None}
    finally:
        cur.close()

    _STAGING_LENGTHS_CACHE = result
    return result


# Map of grid-side (lowercase) editable field names to the staging column(s)
# they ultimately populate. Used by /api/staging_limits to drive the
# light-red cell highlighting in the AG Grid. Only EDITABLE columns are
# listed; read-only overflow (SSN, SOURCE_ID, DEC_HDRCODE) is reported in the
# pre-flight modal but not as cell highlights — the user can't fix it from
# the grid.
SOURCE_TO_STAGING_FIELDS: Dict[str, List[str]] = {
    'source_name':             ['ADDRCONTACT'],
    'source_address_recomend': ['ADDRADDRESS'],
    'source_city':             ['ADDRCITY'],
    'source_state':            ['ADDRSTATE'],
    'source_zip':              ['ADDRZIPCODE'],
}


def get_source_field_limits(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build the {grid_field: {max, staging_columns}} dict consumed by the
    frontend.

    For each source field, the effective max is min(declared_length_of_target,
    declared_length_of_<target>_2) — if a `_2` sibling exists and is
    auto-mirrored, the stricter of the two limits applies (the same value is
    written to both, so it must fit in both).
    """
    lengths = get_staging_column_lengths(config)
    all_string_cols = set(lengths.keys())
    explicit_in_specs = {col for col, _ in _build_column_specs()}

    out: Dict[str, Dict[str, Any]] = {}
    for src_field, targets in SOURCE_TO_STAGING_FIELDS.items():
        # Include auto-mirrored _2 siblings: same value goes there too.
        all_targets = list(targets)
        for t in list(targets):
            sib = t + '_2'
            if sib in all_string_cols and sib not in explicit_in_specs:
                all_targets.append(sib)

        usable = [lengths[c] for c in all_targets if c in lengths]
        if not usable:
            continue
        out[src_field] = {
            'max': min(usable),
            'staging_columns': all_targets,
        }
    return out


def get_staging_overflows(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pre-flight enumerator: return one entry per eligible row whose mapped
    values would overflow at least one staging column.

    Each entry is:
      {
        'source_id': str, 'source_ssn': str,
        'violations': [
          {'column': 'source_name', 'staging': 'ADDRCONTACT',
           'max': 35, 'actual': 47, 'editable': True},
          ...
        ]
      }

    Checks ALL mapped string columns (editable AND read-only) so the modal
    can show every reason a row will be rejected — even ones the user must
    fix at the source rather than in the grid.
    """
    table = config.get('table', 'import_merge_matches').upper()
    table = _safe_table(table)

    column_specs = _build_column_specs()
    lengths = get_staging_column_lengths(config)

    # Map each mapped staging column back to (a) a source-side column name
    # the grid recognises and (b) whether it's editable from the grid.
    # Keys here are STAGING column names; values are the metadata used in
    # the violation entry returned to the frontend.
    staging_to_source = {
        'ADDRADDRESS':    {'column': 'source_address_recomend', 'editable': True},
        'ADDRCITY':       {'column': 'source_city',             'editable': True},
        'ADDRCONTACT':    {'column': 'source_name',             'editable': True},
        'ADDRSEQ':        {'column': 'dec_addrsubcode',         'editable': False},
        'ADDRSEQ_SOURCE': {'column': 'source_addrseq',          'editable': False},
        'ADDRSTATE':      {'column': 'source_state',            'editable': True},
        'ADDRZIPCODE':    {'column': 'source_zip',              'editable': True},
        'ECODE':          {'column': 'dec_hdrcode',             'editable': False},
        'LEGACY_ID':      {'column': 'source_id',               'editable': False},
        'SSN':            {'column': 'source_ssn',              'editable': False},
        'SSN_2':          {'column': 'source_ssn',              'editable': False},
    }

    # Build per-staging-column LENGTH() expressions and overflow predicates.
    # We reuse the SELECT expression from column_specs so SSN_2's digits-only
    # transform and ECODE's HOW_TO_PROCESS conditional are honored exactly.
    select_parts: List[str] = ["SOURCE_ID", "SOURCE_SSN"]
    overflow_terms: List[str] = []
    # Track which alias maps to which staging column for result parsing.
    alias_to_meta: List[Tuple[str, str, int]] = []  # (alias, staging_col, max_len)

    for staging_col, expr in column_specs:
        if staging_col not in staging_to_source:
            continue  # not a mapped string column we surface to the user
        max_len = lengths.get(staging_col)
        if max_len is None:
            continue
        # Snowflake column aliases must be valid identifiers.
        alias = f"L_{staging_col}"
        select_parts.append(f"LENGTH({expr}) AS {alias}")
        overflow_terms.append(f"LENGTH({expr}) > {max_len}")
        alias_to_meta.append((alias, staging_col, max_len))

    if not overflow_terms:
        return []

    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM {table} "
        f"WHERE UPPER(RECOMMENDATION) = 'APPROVED' "
        f"  AND HOW_TO_PROCESS IS NOT NULL AND TRIM(HOW_TO_PROCESS) <> '' "
        f"  AND HOW_TO_PROCESS <> 'Manual Review - DNP' "
        f"  AND ({' OR '.join(overflow_terms)})"
    )

    conn = get_snowflake_connection(config)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        col_names = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()

    # Build a name->index map once so per-row parsing is O(1).
    idx = {name: i for i, name in enumerate(col_names)}

    out: List[Dict[str, Any]] = []
    for row in rows:
        violations = []
        for alias, staging_col, max_len in alias_to_meta:
            actual = row[idx[alias]]
            if actual is None or actual <= max_len:
                continue
            meta = staging_to_source[staging_col]
            violations.append({
                'column':   meta['column'],
                'staging':  staging_col,
                'max':      max_len,
                'actual':   int(actual),
                'editable': meta['editable'],
            })
        if violations:
            out.append({
                'source_id':  row[idx['SOURCE_ID']],
                'source_ssn': row[idx['SOURCE_SSN']],
                'violations': violations,
            })
    return out


def stage_approved_records(config: Dict[str, Any], df=None) -> Dict[str, Any]:
    """
    Copy eligible records to DGO_MA.MA_STAGING.STG_BA_MASTER and flag them
    as STAGED in the source table, all within a single transaction.

    Records whose mapped values would overflow a destination VARCHAR column
    are excluded from BOTH the INSERT and the STAGED flag — they stay APPROVED
    so they remain visible in the grid for the user to fix. The pre-flight
    /api/staging_validate endpoint surfaces them ahead of time; this function
    is the defense-in-depth backstop and never inserts an oversized value.

    Returns:
        {'staged': int, 'rejected': int, 'rejected_rows': List[dict]}
    """
    table = config.get('table', 'import_merge_matches').upper()
    table = _safe_table(table)
    empty_result = {'staged': 0, 'rejected': 0, 'rejected_rows': []}

    if df is None:
        # Load eligible records from Snowflake directly. 'Manual Review - DNP'
        # rows are intentionally excluded — they're flagged for human review,
        # not for automated downstream processing.
        conn = get_snowflake_connection(config)
        cursor_check = conn.cursor()
        cursor_check.execute(
            f"SELECT SOURCE_ID, SOURCE_SSN FROM {table} "
            f"WHERE UPPER(RECOMMENDATION) = 'APPROVED' "
            f"AND HOW_TO_PROCESS IS NOT NULL AND TRIM(HOW_TO_PROCESS) != '' "
            f"AND HOW_TO_PROCESS <> 'Manual Review - DNP'"
        )
        rows = cursor_check.fetchall()
        cursor_check.close()
        if not rows:
            return empty_result
        eligible = pd.DataFrame(rows, columns=['source_id', 'source_ssn'])
    else:
        # Identify eligible rows from the DataFrame
        mask = (
            (df['recommendation'].str.upper() == 'APPROVED') &
            (df['how_to_process'].fillna('').str.strip() != '') &
            (df['how_to_process'] != 'Manual Review - DNP')
        )
        eligible = df[mask]
        if eligible.empty:
            return empty_result

    # Build WHERE clause using source_id + source_ssn pairs
    pairs = list(zip(
        eligible['source_id'].astype(str),
        eligible['source_ssn'].astype(str)
    ))
    pair_placeholders = ', '.join(['(%s, %s)'] * len(pairs))
    pair_params = [v for pair in pairs for v in pair]

    # 'Manual Review - DNP' is excluded from BOTH the INSERT into staging AND
    # the UPDATE that flags rows STAGED — DNP rows stay visible/APPROVED so
    # a human can revisit them.
    eligibility_where = (
        f"(SOURCE_ID, SOURCE_SSN) IN ({pair_placeholders}) "
        f"AND UPPER(RECOMMENDATION) = 'APPROVED' "
        f"AND HOW_TO_PROCESS IS NOT NULL AND TRIM(HOW_TO_PROCESS) != '' "
        f"AND HOW_TO_PROCESS <> 'Manual Review - DNP'"
    )

    conn = get_snowflake_connection(config)
    cursor = conn.cursor()

    try:
        # Single source of truth for the column mapping — also used by
        # get_source_field_limits / get_staging_overflows so all three paths
        # stay in lockstep.
        column_specs = _build_column_specs()

        # Discover what columns actually exist in STG_BA_MASTER so we only
        # reference _2 siblings that are real. Cheap: one DESCRIBE per stage op.
        cursor.execute("DESCRIBE TABLE DGO_MA.MA_STAGING.STG_BA_MASTER")
        all_staging_cols = {row[0].upper() for row in cursor.fetchall()}

        expanded, auto_mirrored = _expand_with_auto_mirror(column_specs, all_staging_cols)

        if auto_mirrored:
            print(f"  [STAGING] Auto-mirroring {len(auto_mirrored)} _2 column(s): "
                  f"{', '.join(auto_mirrored)}")

        # Hard-block: physically prevent any oversize value from reaching
        # staging by ANDing LENGTH(<expr>) <= <max> for every mapped string
        # column into the WHERE clause. NULL/empty values are kept valid
        # because LENGTH(NULL) IS NULL (the OR keeps them through the filter).
        # Same predicate is applied to the UPDATE-to-STAGED so a rejected row
        # stays APPROVED instead of being silently dropped.
        lengths = get_staging_column_lengths(config)
        length_predicates: List[str] = []
        for staging_col, expr in expanded:
            n = lengths.get(staging_col)
            if n is None:
                continue
            length_predicates.append(f"(({expr}) IS NULL OR LENGTH({expr}) <= {n})")
        length_where = " AND ".join(length_predicates) if length_predicates else "TRUE"
        full_where = f"({eligibility_where}) AND ({length_where})"

        # Capture the rejected rows BEFORE the INSERT so the response can
        # report exactly what was skipped and why. Restricted to this batch's
        # (SOURCE_ID, SOURCE_SSN) pairs so we don't pull unrelated overflows.
        cursor.execute(
            f"SELECT SOURCE_ID, SOURCE_SSN FROM {table} "
            f"WHERE ({eligibility_where}) AND NOT ({length_where})",
            pair_params,
        )
        rejected_pairs = cursor.fetchall()

        rejected_rows: List[Dict[str, Any]] = []
        if rejected_pairs:
            # Reuse the global enumerator to get the per-row violation list,
            # then keep only the entries that match this batch.
            batch_keys = {(str(p[0]), str(p[1])) for p in rejected_pairs}
            for entry in get_staging_overflows(config):
                key = (str(entry.get('source_id')), str(entry.get('source_ssn')))
                if key in batch_keys:
                    rejected_rows.append(entry)

        cols_sql = ',\n                '.join(c for c, _ in expanded)
        vals_sql = ',\n                '.join(e for _, e in expanded)

        cursor.execute(
            f"""
            INSERT INTO DGO_MA.MA_STAGING.STG_BA_MASTER (
                {cols_sql}
            )
            SELECT
                {vals_sql}
            FROM {table}
            WHERE {full_where}
            """,
            pair_params
        )
        staged_count = cursor.rowcount

        # UPDATE source: flag as STAGED — only the rows that were actually
        # inserted. Rejected rows stay APPROVED.
        cursor.execute(
            f"UPDATE {table} SET RECOMMENDATION = 'STAGED' "
            f"WHERE {full_where}",
            pair_params
        )

        conn.commit()
        return {
            'staged': staged_count,
            'rejected': len(rejected_rows),
            'rejected_rows': rejected_rows,
        }

    except Exception:
        conn.rollback()
        raise


def load_data(config: Dict[str, Any]) -> pd.DataFrame:
    """
    Load data based on configuration settings.

    Args:
        config: Dictionary containing data source configuration

    Example config:
        {'source_type': 'snowflake', 'account': '...', 'user': '...', ...}
    """
    source_type = config.get('source_type', 'snowflake').lower()

    if source_type == 'snowflake':
        return DataSource.load_from_snowflake(config)

    raise ValueError(f"Unknown source type: {source_type}. Supported: 'snowflake'")


def save_grid_setting(config: Dict[str, Any], key: str, value: str) -> None:
    """Upsert a single key/value row into GRID_SETTINGS."""
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    cursor.execute(
        """
        MERGE INTO GRID_SETTINGS t
        USING (SELECT %s AS k, %s AS v) s ON t.SETTING_KEY = s.k
        WHEN MATCHED THEN UPDATE SET
            t.SETTING_VALUE = s.v, t.UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (SETTING_KEY, SETTING_VALUE)
            VALUES (s.k, s.v)
        """,
        (key, value)
    )
    conn.commit()


def load_grid_setting(config: Dict[str, Any], key: str) -> Optional[str]:
    """Return the stored value for *key*, or None if not found."""
    conn = get_snowflake_connection(config)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT SETTING_VALUE FROM GRID_SETTINGS WHERE SETTING_KEY = %s", (key,)
    )
    row = cursor.fetchone()
    return row[0] if row else None
