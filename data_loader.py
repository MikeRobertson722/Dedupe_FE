"""
Data Source Abstraction Layer
Supports loading data from Snowflake
"""
import os
import time
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple


# Persistent Snowflake connection — avoids repeated SSO browser popups
_sf_conn = None
_sf_config_hash = None
_sf_conn_verified_at = 0  # timestamp of last successful health check
_SF_CONN_TTL = 60         # seconds to trust a connection without re-checking


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

    # Reuse existing connection if same config
    if _sf_conn is not None and _sf_config_hash == config_hash:
        # Skip health check if recently verified
        if (time.time() - _sf_conn_verified_at) < _SF_CONN_TTL:
            return _sf_conn
        # Otherwise verify with SELECT 1
        try:
            _sf_conn.cursor().execute("SELECT 1")
            _sf_conn_verified_at = time.time()
            return _sf_conn
        except Exception:
            # Connection is dead — reconnect
            try:
                _sf_conn.close()
            except Exception:
                pass
            _sf_conn = None

    _sf_conn = connector.connect(**conn_params)
    _sf_config_hash = config_hash
    _sf_conn_verified_at = time.time()
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
        if 'hdrcode' in df.columns and 'canvas_id' not in df.columns:
            column_map = {
                'hdrcode': 'dec_hdrcode',
                'ssn': 'canvas_ssn',
                'hdrname': 'dec_name',
                'addrcontact': 'dec_contact',
                'addraddress': 'dec_address',
                'addrcity': 'dec_city',
                'addrstate': 'dec_state',
                'addrzipcode': 'dec_zip',
                'addrsubcode': 'dec_addrsubcode',
            }
            df = df.rename(columns=column_map)

            for col in ('canvas_id', 'canvas_name', 'canvas_address',
                        'canvas_city', 'canvas_state', 'canvas_zip'):
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
            CANVAS_ID VARCHAR,
            CANVAS_SSN VARCHAR,
            FIELD_NAME VARCHAR,
            OLD_VALUE VARCHAR,
            NEW_VALUE VARCHAR,
            UPDATED_AT TIMESTAMP_NTZ,
            CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    conn.commit()


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
        df: Current in-memory DataFrame (to look up canvas_id/canvas_ssn)
        cursor: Optional shared cursor (caller manages commit)

    Returns:
        Number of rows affected
    """
    if not pending_changes:
        return 0

    table = config.get('table', 'import_merge_matches').upper()

    # Collect all fields being updated across all rows
    all_fields = set()
    for fields in pending_changes.values():
        all_fields.update(fields.keys())
    all_fields = sorted(all_fields)

    # Build value rows and flat params for a single MERGE
    placeholders = []
    params: list = []
    for row_id, fields in pending_changes.items():
        cid = str(df.at[row_id, 'canvas_id'])
        ssn = str(df.at[row_id, 'canvas_ssn'])
        row_ph = ['%s', '%s']
        params.extend([cid, ssn])
        for f in all_fields:
            entry = fields.get(f)
            if isinstance(entry, tuple):
                params.append(entry[1])
            elif entry is not None:
                params.append(entry)
            else:
                params.append(None)
            row_ph.append('%s')
        placeholders.append('(' + ', '.join(row_ph) + ')')

    own_cursor = cursor is None
    if own_cursor:
        conn = get_snowflake_connection(config)
        cursor = conn.cursor()

    # Single MERGE: all rows in one statement
    src_cols = ['CID', 'SSN'] + [f.upper() for f in all_fields]
    values_block = ', '.join(placeholders)
    set_clause = ', '.join(f't.{f.upper()} = s.{f.upper()}' for f in all_fields)

    sql = (
        f"MERGE INTO {table} t USING ("
        f"SELECT {', '.join('column' + str(i+1) + ' AS ' + c for i, c in enumerate(src_cols))} "
        f"FROM VALUES {values_block}"
        f") s ON t.CANVAS_ID = s.CID AND t.CANVAS_SSN = s.SSN "
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

    Args:
        config: Snowflake connection config
        log_entries: List of (canvas_id, canvas_ssn, field_name, old_value, new_value, updated_at)
        cursor: Optional shared cursor (caller manages commit)
    """
    if not log_entries:
        return

    own_cursor = cursor is None
    if own_cursor:
        conn = get_snowflake_connection(config)
        cursor = conn.cursor()
    cursor.executemany(
        """INSERT INTO UPDATE_LOG (CANVAS_ID, CANVAS_SSN, FIELD_NAME, OLD_VALUE, NEW_VALUE, UPDATED_AT)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        log_entries
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
