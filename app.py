"""
BA Deduplication Review Application
Web interface for reviewing and updating import_merge_matches data via Snowflake
"""
from flask import Flask, render_template, request, jsonify, Response, make_response
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import uuid as _uuid_module
import threading as _threading

# Load .env file (must be before any config reads os.environ)
load_dotenv(Path(__file__).parent / '.env')

from data_loader import (
    load_data, get_snowflake_connection, merge_changes_to_snowflake,
    write_audit_log_to_snowflake, read_audit_log_from_snowflake,
    ensure_snowflake_schema, count_staging_eligible, stage_approved_records,
    save_grid_setting, load_grid_setting,
    get_bucket_counts, query_snowflake_page,
    save_record_immediately, save_records_batch,
    DataSource, BucketCache, BUCKET_CACHE_MAX_ROWS,
    _FIELD_TO_DB_COL,  # noqa: F401 — used in Task 8 search_replace endpoint
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True


@app.after_request
def add_no_cache_headers(response):
    """Prevent browser from caching API responses"""
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# Build Snowflake config from .env (all connection info lives in environment variables)
DATA_CONFIG = {
    'source_type': 'snowflake',
    'name': 'Snowflake (Cloud)',
    'account': os.environ.get('SNOWFLAKE_ACCOUNT', ''),
    'user': os.environ.get('SNOWFLAKE_USER', ''),
    'password': os.environ.get('SNOWFLAKE_PASSWORD', ''),
    'database': os.environ.get('SNOWFLAKE_DATABASE', 'dgo_ma'),
    'schema': os.environ.get('SNOWFLAKE_SCHEMA', 'ba_process'),
    'warehouse': os.environ.get('SNOWFLAKE_WAREHOUSE', ''),
    'table': os.environ.get('SNOWFLAKE_TABLE', 'import_merge_matches'),
    'source_company_name': os.environ.get('SOURCE_COMPANY_NAME', 'Source'),
}

if not DATA_CONFIG['account']:
    raise ValueError("SNOWFLAKE_ACCOUNT not set. Check your .env file.")

# Single active BucketCache — shared across all users
_bucket_cache = None
_bucket_cache_lock = _threading.Lock()
CACHE_TTL_SECONDS = 300  # 5 minutes

# Cached ba_config score ranges (loaded once at first stats call)
_ba_config_cache = None

# Hardcoded defaults for ba_config values — used by the Config editor "Revert to Defaults" feature
DEFAULT_BA_CONFIG = {
    # API
    'API_BATCH_SIZE':                           '20',
    'API_MODEL':                                'claude-sonnet-4-5-20250929',
    'API_SCORE_MAX':                            '70.0',
    'API_SCORE_MIN':                            '15.0',
    'USE_API_OVERRIDE':                         'false',
    # BUCKETS
    'EXISTING_BA_EXISTING_ADDR_MAX_ADDR_SCORE': '100',
    'EXISTING_BA_EXISTING_ADDR_MAX_NAME_SCORE': '100',
    'EXISTING_BA_EXISTING_ADDR_MIN_ADDR_SCORE': '100',
    'EXISTING_BA_EXISTING_ADDR_MIN_NAME_SCORE': '100',
    'EXISTING_BA_NEW_ADDR_MAX_ADDR_SCORE':      '0',
    'EXISTING_BA_NEW_ADDR_MAX_NAME_SCORE':      '100',
    'EXISTING_BA_NEW_ADDR_MIN_ADDR_SCORE':      '0',
    'EXISTING_BA_NEW_ADDR_MIN_NAME_SCORE':      '100',
    'NEW_BA_NEW_ADDR_MAX_ADDR_SCORE':           '0',
    'NEW_BA_NEW_ADDR_MAX_NAME_SCORE':           '0',
    'NEW_BA_NEW_ADDR_MIN_ADDR_SCORE':           '0',
    'NEW_BA_NEW_ADDR_MIN_NAME_SCORE':           '0',
    # GENERAL
    'SOURCE_COMPANY_NAME':                      'CANVAS_TEST',
    # GOOGLE
    'GOOGLE_ADDR_SCORE_MAX':                    '110',
    'GOOGLE_ADDR_SCORE_MIN':                    '110',
    # NAME_MATCHING
    'ACRONYM_MATCH_SCORE':                      '0.95',
    'FUZZY_TOKEN_JW_THRESHOLD':                 '0.92',
    'FUZZY_TOKEN_MIN_LENGTH':                   '4',
    'NAME_MATCH_THRESHOLD':                     '0.85',
    'SUPP_NAME_BOOST_CAP':                      '0.95',
    # SCORING
    'CITY_WEIGHT':                              '0.4',
    'SAME_ADDR_CITY_SIM':                       '0.85',
    'SAME_ADDR_STREET_SIM':                     '0.9',
    'STREET_WEIGHT':                            '0.6',
    'ZIP_BONUS':                                '0.05',
    'ZIP_MUST_MATCH':                           'false',
    'ZIP_PENALTY_MULT':                         '0.75',
}



def _load_ba_config():
    """Load ba_config score ranges from Snowflake, cached after first successful call."""
    global _ba_config_cache
    if _ba_config_cache:
        return _ba_config_cache
    try:
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT CONFIG_KEY, CONFIG_VALUE FROM BA_CONFIG WHERE CATEGORY = 'BUCKETS'")
        rows = {r[0]: r[1] for r in cursor.fetchall()}
        print(f"  BA_CONFIG loaded: {len(rows)} score params")
        _ba_config_cache = {
            'NEW BA AND NEW ADDRESS': {
                'min_name': rows.get('NEW_BA_NEW_ADDR_MIN_NAME_SCORE', ''),
                'max_name': rows.get('NEW_BA_NEW_ADDR_MAX_NAME_SCORE', ''),
                'min_addr': rows.get('NEW_BA_NEW_ADDR_MIN_ADDR_SCORE', ''),
                'max_addr': rows.get('NEW_BA_NEW_ADDR_MAX_ADDR_SCORE', ''),
            },
            'EXISTING BA ADD NEW ADDRESS': {
                'min_name': rows.get('EXISTING_BA_NEW_ADDR_MIN_NAME_SCORE', ''),
                'max_name': rows.get('EXISTING_BA_NEW_ADDR_MAX_NAME_SCORE', ''),
                'min_addr': rows.get('EXISTING_BA_NEW_ADDR_MIN_ADDR_SCORE', ''),
                'max_addr': rows.get('EXISTING_BA_NEW_ADDR_MAX_ADDR_SCORE', ''),
            },
            'EXISTING BA AND EXISTING ADDRESS': {
                'min_name': rows.get('EXISTING_BA_EXISTING_ADDR_MIN_NAME_SCORE', ''),
                'max_name': rows.get('EXISTING_BA_EXISTING_ADDR_MAX_NAME_SCORE', ''),
                'min_addr': rows.get('EXISTING_BA_EXISTING_ADDR_MIN_ADDR_SCORE', ''),
                'max_addr': rows.get('EXISTING_BA_EXISTING_ADDR_MAX_ADDR_SCORE', ''),
            },
        }
    except Exception as e:
        print(f"  BA_CONFIG error: {e}")
        _ba_config_cache = None
    return _ba_config_cache or {}


def _get_source_company_name():
    """Read SOURCE_COMPANY_NAME from BA_CONFIG (GENERAL), fall back to env var."""
    try:
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT CONFIG_VALUE FROM BA_CONFIG "
            "WHERE CATEGORY = 'GENERAL' AND CONFIG_KEY = 'SOURCE_COMPANY_NAME' LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return DATA_CONFIG.get('source_company_name', 'Source')


def _get_or_load_bucket_cache(bucket: str, force: bool = False):
    """
    Return the active BucketCache for the given bucket.
    Loads from Snowflake if the cache is empty, stale, or for a different bucket.
    Returns None if the bucket has more than BUCKET_CACHE_MAX_ROWS rows (SQL mode).
    """
    global _bucket_cache

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
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        conn = get_snowflake_connection(DATA_CONFIG)
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
    """Clear the active bucket cache (call after writes that change recommendation values)."""
    global _bucket_cache
    with _bucket_cache_lock:
        _bucket_cache = None


def _get_user_identity():
    """
    Return (user_id, user_name) from request cookies.
    """
    user_id = request.cookies.get('user_id')
    user_name = request.cookies.get('user_name')
    return user_id, user_name


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


@app.route('/api/recommendations')
def get_recommendations():
    """Get distinct recommendation values from the data"""
    try:
        counts = get_bucket_counts(DATA_CONFIG)
        values = sorted(counts.keys())
        return jsonify(values)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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

        # Decide mode: hot cache only for single-bucket filter with no global search
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
                df_page = (df_filtered.iloc[start:]
                           if length == -1
                           else df_filtered.iloc[start:start + length])

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
            data = [{k: ('' if v is None else v) for k, v in r.items()} for r in rows]
            for row in data:
                row['_row_id'] = row.get('id')

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


@app.route('/api/record/<int:row_id>')
def get_record(row_id):
    try:
        df = load_cached_data()
        if row_id >= len(df):
            return jsonify({'error': 'Invalid row_id'}), 404

        record = df.iloc[row_id].to_dict()
        record = {k: (None if pd.isna(v) else v) for k, v in record.items()}
        record['_row_id'] = row_id
        return jsonify(record)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/db_record/<int:uid>')
def get_db_record(uid):
    """Query Snowflake directly by UID (id column) to verify persisted data."""
    try:
        table = DATA_CONFIG.get('table', 'import_merge_matches').upper()
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM {table} WHERE ID = %s", (uid,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': f'No record with ID={uid}'}), 404
        cols = [desc[0].lower() for desc in cursor.description]
        record = dict(zip(cols, row))
        record = {k: (None if v is None else v) for k, v in record.items()}
        return jsonify(record)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/update', methods=['POST'])
def update_record():
    """Update a single field on a record. All changes are deferred until Save."""
    global _pending_changes
    try:
        data = request.json
        row_id = data.get('row_id')
        field = data.get('field')
        value = data.get('value')

        if row_id is None or not field:
            return jsonify({'error': 'Missing required fields'}), 400

        allowed_fields = {
            'recommendation', 'source_name', 'source_address_recomend',
            'source_city', 'source_state', 'source_zip', 'address_reason',
            'jib', 'rev', 'vendor', 'how_to_process', 'memo'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        df = load_cached_data()
        if row_id >= len(df):
            return jsonify({'error': 'Invalid row_id'}), 400

        # Block edits on STAGED records
        if str(df.at[row_id, 'recommendation'] or '').upper() == 'STAGED':
            return jsonify({'error': 'Cannot modify a STAGED record'}), 403

        # Coerce value types
        if field in ('jib', 'rev', 'vendor'):
            value = int(value)

        # Capture old value before updating
        old_value = df.at[row_id, field]

        # Update in-memory DataFrame
        df.at[row_id, field] = value

        # Track as pending with (old_value, new_value)
        if row_id not in _pending_changes:
            _pending_changes[row_id] = {}
        # Only store the first old_value (the original before any edits this session)
        if field not in _pending_changes[row_id]:
            _pending_changes[row_id][field] = (str(old_value), value)
        else:
            orig_old = _pending_changes[row_id][field][0]
            if str(value) == str(orig_old):
                # Value reverted to original — no longer pending
                del _pending_changes[row_id][field]
                if not _pending_changes[row_id]:
                    del _pending_changes[row_id]
            else:
                _pending_changes[row_id][field] = (orig_old, value)

        return jsonify({
            'success': True,
            'pending_count': len(_pending_changes),
            'message': 'Updated (unsaved)'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bulk_update', methods=['POST'])
def bulk_update():
    """Bulk update recommendation for multiple records (deferred until Save)."""
    global _pending_changes
    try:
        data = request.json
        row_ids = data.get('row_ids', [])
        new_recommendation = data.get('recommendation', 'APPROVED')
        # Optional map of {row_id: how_to_process} to persist alongside the rec change.
        # Keys may be strings (JSON object keys are always strings).
        process_values = {int(k): v for k, v in data.get('process_values', {}).items() if v}

        if not row_ids:
            return jsonify({'error': 'No row IDs provided'}), 400

        df = load_cached_data()
        success_count = 0
        errors = []

        for row_id in row_ids:
            try:
                if row_id >= len(df):
                    errors.append(f"Invalid row_id: {row_id}")
                    continue

                # Skip STAGED records — they cannot be modified
                if str(df.at[row_id, 'recommendation'] or '').upper() == 'STAGED':
                    continue

                if row_id not in _pending_changes:
                    _pending_changes[row_id] = {}

                old_rec = str(df.at[row_id, 'recommendation'] or '')
                df.at[row_id, 'recommendation'] = new_recommendation
                if 'recommendation' not in _pending_changes[row_id]:
                    _pending_changes[row_id]['recommendation'] = (old_rec, new_recommendation)
                else:
                    orig_old = _pending_changes[row_id]['recommendation'][0]
                    _pending_changes[row_id]['recommendation'] = (orig_old, new_recommendation)

                # Persist process value if provided (captures client-side pre-fills)
                if row_id in process_values:
                    new_process = process_values[row_id]
                    old_process = str(df.at[row_id, 'how_to_process'] or '')
                    df.at[row_id, 'how_to_process'] = new_process
                    if 'how_to_process' not in _pending_changes[row_id]:
                        _pending_changes[row_id]['how_to_process'] = (old_process, new_process)
                    else:
                        orig_old_p = _pending_changes[row_id]['how_to_process'][0]
                        _pending_changes[row_id]['how_to_process'] = (orig_old_p, new_process)

                success_count += 1

            except Exception as e:
                errors.append(f"Row {row_id}: {str(e)}")

        return jsonify({
            'success': True,
            'updated': success_count,
            'errors': errors,
            'pending_count': len(_pending_changes)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bulk_field_update', methods=['POST'])
def bulk_field_update():
    """Bulk update a single field for multiple records (deferred until Save)."""
    global _pending_changes
    try:
        data = request.json
        row_ids = data.get('row_ids', [])
        field = data.get('field')
        value = data.get('value')

        if not row_ids or not field:
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

        df = load_cached_data()
        success_count = 0

        for row_id in row_ids:
            if row_id >= len(df):
                continue
            old_value = df.at[row_id, field]
            df.at[row_id, field] = value
            if row_id not in _pending_changes:
                _pending_changes[row_id] = {}
            if field not in _pending_changes[row_id]:
                _pending_changes[row_id][field] = (str(old_value), value)
            else:
                orig_old = _pending_changes[row_id][field][0]
                _pending_changes[row_id][field] = (orig_old, value)
            success_count += 1

        return jsonify({
            'success': True,
            'updated': success_count,
            'pending_count': len(_pending_changes)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches_all')
def get_matches_all():
    """Return full dataset as JSON for AG Grid client-side processing"""
    try:
        df = load_cached_data()
        if df.empty:
            return Response('[]', mimetype='application/json')

        needed_cols = [
            'id', 'ssn_match', 'name_score', 'address_score', 'nameaddrscore', 'recommendation',
            'how_to_process', 'source_id', 'source_addrseq', 'source_name',
            'source_address', 'source_city', 'source_state', 'source_zip', 'source_ssn',
            'source_address_recomend',
            'dec_ssn', 'dec_name', 'dec_address', 'dec_city', 'dec_state', 'dec_zip',
            'dec_hdrcode', 'dec_addrsubcode', 'dec_contact', 'dec_address_looked_up',
            'address_reason', 'jib', 'rev', 'vendor', 'memo', 'is_trust', 'run_id',
            'name_normal_detail', 'address_normal_detail', 'name_match_detail', 'addr_match_detail'
        ]
        available = [c for c in needed_cols if c in df.columns]
        df_out = df[available].fillna('').copy()
        df_out['_row_id'] = df.index.tolist()
        result = df_out.to_json(orient='records', default_handler=str)
        return Response(result, mimetype='application/json')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dev_notes')
def dev_notes():
    notes_path = Path('Things to consider.docx').resolve()
    if not notes_path.exists():
        return jsonify({'error': 'Dev notes file not found'}), 404
    import subprocess
    type_def = (
        'using System; using System.Runtime.InteropServices; '
        'public class Win32 { '
        '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); '
        '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); '
        '}'
    )
    ps_cmd = (
        f'Start-Process "{notes_path}";'
        ' Start-Sleep -Milliseconds 1500;'
        f" Add-Type -TypeDefinition '{type_def}' -ErrorAction SilentlyContinue;"
        ' $p = Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -First 1;'
        ' if ($p) {'
        ' [Win32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null;'   # SW_RESTORE
        ' [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null'
        ' }'
    )
    subprocess.Popen(
        ['powershell', '-WindowStyle', 'Hidden', '-Command', ps_cmd],
        creationflags=0x08000000
    )
    return jsonify({'message': 'Opened in Word'})




@app.route('/api/ba_config/all')
def ba_config_all():
    """Return all rows in ba_config grouped by category."""
    try:
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT CATEGORY, CONFIG_KEY, CONFIG_VALUE FROM BA_CONFIG ORDER BY CATEGORY, CONFIG_KEY")
        rows = [{'category': r[0], 'config_key': r[1], 'config_value': r[2]} for r in cursor.fetchall()]
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ba_config/defaults')
def ba_config_defaults():
    """Return hardcoded default values for ba_config keys."""
    return jsonify(DEFAULT_BA_CONFIG)


@app.route('/api/ba_config/update', methods=['POST'])
def ba_config_update():
    """Update a single CONFIG_VALUE in ba_config."""
    global _ba_config_cache
    try:
        data = request.json
        category = data.get('category', '').strip()
        config_key = data.get('config_key', '').strip()
        config_value = data.get('config_value', '').strip()
        if not category or not config_key:
            return jsonify({'error': 'category and config_key are required'}), 400
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE BA_CONFIG SET CONFIG_VALUE = %s WHERE CATEGORY = %s AND CONFIG_KEY = %s",
            (config_value, category, config_key)
        )
        conn.commit()
        _ba_config_cache = None  # invalidate so next load re-fetches
        return jsonify({'message': 'Updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/grid_settings')
def get_grid_settings():
    try:
        col = load_grid_setting(DATA_CONFIG, 'column_state')
        flt = load_grid_setting(DATA_CONFIG, 'filter_state')
        return jsonify({
            'column_state': json.loads(col) if col else None,
            'filter_state': json.loads(flt) if flt else None,
        })
    except Exception as e:
        print(f"grid_settings load error: {e}")
        return jsonify({'column_state': None, 'filter_state': None})


@app.route('/api/grid_settings', methods=['POST'])
def post_grid_settings():
    try:
        data = request.json
        key = data.get('key', '').strip()
        value = data.get('value')
        if key not in {'column_state', 'filter_state'}:
            return jsonify({'error': f'Unknown key: {key}'}), 400
        if value is None:
            return jsonify({'error': 'value required'}), 400
        save_grid_setting(DATA_CONFIG, key, json.dumps(value))
        return jsonify({'success': True})
    except Exception as e:
        print(f"grid_settings save error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/search_replace', methods=['POST'])
def search_replace():
    """Search and replace text in one or all text columns (deferred until Save)."""
    global _pending_changes
    try:
        data = request.json
        search = data.get('search', '')
        replace = data.get('replace', '')
        column = data.get('column', 'all')
        case_sensitive = data.get('case_sensitive', False)
        mode = data.get('mode', 'find')  # 'find' or 'replace'

        if not search:
            return jsonify({'error': 'Search text is required'}), 400

        text_fields = {
            'source_name', 'source_address_recomend', 'source_city', 'source_state', 'source_zip',
            'recommendation', 'how_to_process', 'memo', 'address_reason'
        }

        if column == 'all':
            cols_to_search = list(text_fields)
        elif column in text_fields:
            cols_to_search = [column]
        else:
            return jsonify({'error': f'Column "{column}" is not searchable'}), 400

        df_full = load_cached_data()
        if df_full.empty:
            return jsonify({'matches': 0, 'rows': 0})

        # Restrict to visible/filtered rows if provided
        row_ids = data.get('row_ids')
        if row_ids is not None:
            df = df_full.loc[df_full.index.isin(row_ids)]
        else:
            df = df_full

        # Count matches
        match_count = 0
        match_rows = set()
        for col in cols_to_search:
            if col not in df.columns:
                continue
            series = df[col].astype(str).fillna('')
            if case_sensitive:
                mask = series.str.contains(search, case=True, na=False, regex=False)
            else:
                mask = series.str.contains(search, case=False, na=False, regex=False)
            hits = mask.sum()
            match_count += hits
            match_rows.update(df.index[mask].tolist())

        if mode == 'find':
            return jsonify({'matches': int(match_count), 'rows': len(match_rows)})

        # Replace mode
        if not match_rows:
            return jsonify({'replaced': 0, 'rows': 0, 'pending_count': len(_pending_changes)})

        # Exclude STAGED rows from replacements
        match_rows = {
            idx for idx in match_rows
            if str(df_full.at[idx, 'recommendation'] or '').upper() != 'STAGED'
        }

        replaced_count = 0
        replaced_rows = set()
        for col in cols_to_search:
            if col not in df.columns:
                continue
            for idx in list(match_rows):
                old_val = str(df_full.at[idx, col]) if pd.notna(df_full.at[idx, col]) else ''
                if case_sensitive:
                    if search not in old_val:
                        continue
                    new_val = old_val.replace(search, replace)
                else:
                    # Case-insensitive replace
                    import re
                    new_val = re.sub(re.escape(search), replace, old_val, flags=re.IGNORECASE)
                    if new_val == old_val:
                        continue

                df_full.at[idx, col] = new_val
                replaced_count += 1
                replaced_rows.add(idx)

                # Track in pending changes
                if idx not in _pending_changes:
                    _pending_changes[idx] = {}
                if col not in _pending_changes[idx]:
                    _pending_changes[idx][col] = (old_val, new_val)
                else:
                    orig_old = _pending_changes[idx][col][0]
                    _pending_changes[idx][col] = (orig_old, new_val)

        return jsonify({
            'replaced': replaced_count,
            'rows': len(replaced_rows),
            'pending_count': len(_pending_changes)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/import_ids', methods=['POST'])
def import_ids():
    """Import Source IDs from file — updates in-memory only (pending until Save)"""
    global _pending_changes
    try:
        data = request.json
        field = data.get('field')
        source_ids = data.get('source_ids', data.get('canvas_ids', []))

        if field not in ('jib', 'rev', 'vendor'):
            return jsonify({'error': 'Invalid field'}), 400
        if not source_ids:
            return jsonify({'error': 'No Source IDs provided'}), 400

        df = load_cached_data()

        # Convert source_id column to string for matching
        df_source_str = df['source_id'].astype(str).str.strip()
        source_ids_str = [str(cid).strip() for cid in source_ids]

        # Find matching rows (only those not already checked)
        mask = df_source_str.isin(source_ids_str) & (df[field] != 1)
        row_ids = df.index[mask].tolist()

        if not row_ids:
            total_found = int(df_source_str.isin(source_ids_str).sum())
            return jsonify({
                'success': True,
                'updated': 0,
                'pending_count': len(_pending_changes),
                'message': f'No new matches. {total_found} already checked.'
            })

        # Update in-memory DataFrame only (vectorized)
        df.loc[row_ids, field] = 1

        # Track as pending with (old_value, new_value)
        for rid in row_ids:
            if rid not in _pending_changes:
                _pending_changes[rid] = {}
            if field not in _pending_changes[rid]:
                _pending_changes[rid][field] = ('0', 1)
            else:
                orig_old = _pending_changes[rid][field][0]
                _pending_changes[rid][field] = (orig_old, 1)

        return jsonify({
            'success': True,
            'updated': len(row_ids),
            'total_in_file': len(source_ids_str),
            'pending_count': len(_pending_changes),
            'message': f'Checked {field.upper()} for {len(row_ids)} records (unsaved)'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/save_changes', methods=['POST'])
def save_changes():
    """Persist all pending changes to Snowflake"""
    global _pending_changes
    try:
        if not _pending_changes:
            return jsonify({'success': True, 'saved': 0, 'pending_count': 0,
                            'message': 'Nothing to save'})

        df = load_cached_data()
        now = datetime.now()

        # Build audit log entries from pending changes
        log_entries = []
        for row_id, fields in _pending_changes.items():
            cid = str(df.at[row_id, 'source_id'])
            ssn = str(df.at[row_id, 'source_ssn'])
            for field, change in fields.items():
                if isinstance(change, tuple):
                    old_val, new_val = change
                else:
                    old_val, new_val = '', change
                log_entries.append((cid, ssn, field, str(old_val), str(new_val), now))

        # Single connection + single commit for both operations
        conn = get_snowflake_connection(DATA_CONFIG)
        cursor = conn.cursor()
        affected = merge_changes_to_snowflake(DATA_CONFIG, _pending_changes, df, cursor=cursor)
        write_audit_log_to_snowflake(DATA_CONFIG, log_entries, cursor=cursor)
        conn.commit()

        saved_count = len(_pending_changes)
        _pending_changes = {}

        return jsonify({
            'success': True,
            'saved': saved_count,
            'pending_count': 0,
            'message': f'Saved {saved_count} record(s) to Snowflake ({affected} rows updated)'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


@app.route('/api/stage_approved', methods=['POST'])
def stage_approved():
    """Copy eligible APPROVED records to staging table and flag as STAGED."""
    global _pending_changes
    try:
        if _pending_changes:
            return jsonify({
                'error': 'Save your pending changes before staging'
            }), 400

        df = load_cached_data()
        staged = stage_approved_records(DATA_CONFIG, df)

        if staged == 0:
            return jsonify({
                'success': True,
                'staged': 0,
                'message': 'No eligible records to stage'
            })

        # Force-reload from Snowflake so in-memory state reflects STAGED flags
        load_cached_data(force_reload=True)

        return jsonify({
            'success': True,
            'staged': staged,
            'message': f'Staged {staged} record(s) to staging table'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


@app.route('/api/update_log')
def get_update_log():
    """View recent update history from Snowflake"""
    try:
        rows = read_audit_log_from_snowflake(DATA_CONFIG, limit=100)
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/datasources')
def get_datasources():
    """Return the active Snowflake data source info"""
    return jsonify({
        'datasources': [{
            'id': 'snowflake',
            'name': DATA_CONFIG.get('name', 'Snowflake'),
            'type': 'snowflake'
        }],
        'active': 'snowflake'
    })


if __name__ == '__main__':
    # In debug mode Flask spawns two processes; only initialise in the worker
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            ensure_snowflake_schema(DATA_CONFIG)
            print("  Snowflake schema verified")
        except Exception as e:
            print(f"  WARNING: Could not verify Snowflake schema: {e}")

        print('\n' + '='*60)
        print('  BA DEDUPLICATION REVIEW APPLICATION')
        print('='*60)
        print(f'  Data Source: SNOWFLAKE')
        print(f'  Account: {DATA_CONFIG.get("account")}')
        print(f'  Database: {DATA_CONFIG.get("database")}.{DATA_CONFIG.get("schema")}.{DATA_CONFIG.get("table")}')

        df = load_cached_data()
        print(f'  Records loaded: {len(df):,}')
        if not df.empty and 'recommendation' in df.columns:
            print(f'  Recommendations: {df["recommendation"].value_counts().to_dict()}')

        print(f'\n  Open: http://localhost:5000')
        print(f'  Press Ctrl+C to stop')
        print('='*60 + '\n')

    app.run(debug=True, host='0.0.0.0', port=5000)
