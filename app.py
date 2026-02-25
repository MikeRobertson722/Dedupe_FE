"""
BA Deduplication Review Application
Web interface for reviewing and updating import_merge_matches data via Snowflake
"""
from flask import Flask, render_template, request, jsonify, Response
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env file (must be before any config reads os.environ)
load_dotenv(Path(__file__).parent / '.env')

from data_loader import (
    load_data, get_snowflake_connection, merge_changes_to_snowflake,
    write_audit_log_to_snowflake, read_audit_log_from_snowflake,
    ensure_snowflake_schema
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
}

if not DATA_CONFIG['account']:
    raise ValueError("SNOWFLAKE_ACCOUNT not set. Check your .env file.")

# In-memory cache to avoid re-reading Snowflake on every request
_df_cache = None
_df_cache_time = None

# Track unsaved changes: {row_id: {field: (old_value, new_value), ...}, ...}
_pending_changes = {}

# Cached ba_config score ranges (loaded once at first stats call)
_ba_config_cache = None


def load_cached_data(force_reload=False):
    """Load data from Snowflake, cached in memory"""
    global _df_cache, _df_cache_time

    if _df_cache is None or force_reload:
        _df_cache = load_data(DATA_CONFIG)
        _df_cache_time = datetime.now()

    return _df_cache


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


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/recommendations')
def get_recommendations():
    """Get distinct recommendation values from the data"""
    try:
        df = load_cached_data()
        if df.empty:
            return jsonify([])
        values = sorted(df['recommendation'].dropna().unique().tolist())
        return jsonify(values)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/matches')
def get_matches():
    """Server-side DataTables endpoint"""
    try:
        df = load_cached_data()

        if df.empty:
            return jsonify({'data': [], 'recordsTotal': 0, 'recordsFiltered': 0})

        records_total = len(df)

        # DataTables parameters
        draw = request.args.get('draw', type=int, default=1)
        start = request.args.get('start', type=int, default=0)
        length = request.args.get('length', type=int, default=25)
        search_value = request.args.get('search[value]', default='')

        # Custom filters
        recommendation_filter = request.args.get('recommendation', default='')
        ssn_filter = request.args.get('ssn_match', default='')
        min_name_score = request.args.get('min_name_score', type=float, default=None)
        max_name_score = request.args.get('max_name_score', type=float, default=None)
        min_addr_score = request.args.get('min_addr_score', type=float, default=None)
        max_addr_score = request.args.get('max_addr_score', type=float, default=None)

        # Apply filters
        mask = pd.Series(True, index=df.index)

        if recommendation_filter:
            rec_values = [v.strip() for v in recommendation_filter.split(',') if v.strip()]
            if rec_values:
                mask &= df['recommendation'].isin(rec_values)

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

        # Global search across all columns (vectorized per-column, much faster than row-wise apply)
        if search_value:
            search_mask = pd.Series(False, index=df_filtered.index)
            for col in df_filtered.columns:
                search_mask |= df_filtered[col].astype(str).str.contains(
                    search_value, case=False, na=False
                )
            df_filtered = df_filtered[search_mask]

        records_filtered = len(df_filtered)

        # Sorting (use column data name so it works after ColReorder drag)
        order_col = request.args.get('order[0][column]', type=int, default=None)
        order_dir = request.args.get('order[0][dir]', default='asc')

        sortable_fields = {
            'id', 'ssn_match', 'name_score', 'address_score', 'recommendation',
            'canvas_name', 'canvas_address', 'canvas_city', 'canvas_id',
            'dec_name', 'dec_address', 'dec_city', 'dec_hdrcode', 'dec_address_looked_up',
            'jib', 'rev', 'vendor', 'how_to_process', 'memo'
        }
        if order_col is not None:
            col_data = request.args.get(f'columns[{order_col}][data]', default=None)
            if col_data in sortable_fields:
                df_filtered = df_filtered.sort_values(
                    col_data, ascending=(order_dir == 'asc'), na_position='last'
                )

        # Paginate (-1 means all)
        df_page = df_filtered.iloc[start:] if length == -1 else df_filtered.iloc[start:start + length]

        # Only send columns the frontend needs (skip internal/unused fields)
        needed_cols = [
            'id', 'ssn_match', 'name_score', 'address_score', 'nameaddrscore', 'recommendation',
            'how_to_process', 'canvas_id', 'canvas_addrseq', 'canvas_name',
            'canvas_address', 'canvas_city', 'canvas_state', 'canvas_zip', 'canvas_ssn',
            'dec_name', 'dec_address', 'dec_city', 'dec_state', 'dec_zip',
            'dec_hdrcode', 'dec_addrsubcode', 'dec_contact', 'dec_address_looked_up',
            'address_reason', 'jib', 'rev', 'vendor', 'memo', 'is_trust'
        ]
        available = [c for c in needed_cols if c in df_page.columns]
        df_out = df_page[available].fillna('')
        df_out = df_out.copy()
        df_out['_row_id'] = df_page.index

        # Fast-serialize: use to_dict + json.dumps
        data = df_out.to_dict('records')

        result = json.dumps({
            'draw': draw,
            'recordsTotal': records_total,
            'recordsFiltered': records_filtered,
            'data': data
        }, ensure_ascii=False, default=str)
        return Response(result, mimetype='application/json')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    try:
        df = load_cached_data()
        if df.empty:
            return jsonify({'error': 'No data available'}), 404

        stats = {
            'total_records': len(df),
            'recommendations': df['recommendation'].value_counts().to_dict(),
            'avg_name_score': round(float(df['name_score'].mean()), 1),
            'avg_address_score': round(float(df['address_score'].mean()), 1),
            'ssn_perfect_matches': int((df['ssn_match'] == 100).sum()),
            'ssn_partial_matches': int(((df['ssn_match'] > 0) & (df['ssn_match'] < 100)).sum()),
            'ssn_no_match': int((df['ssn_match'] == 0).sum()),
        }

        stats['rec_config'] = _load_ba_config()

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
            'recommendation', 'canvas_name', 'canvas_address',
            'canvas_city', 'canvas_state', 'canvas_zip', 'address_reason',
            'jib', 'rev', 'vendor', 'how_to_process', 'memo'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        df = load_cached_data()
        if row_id >= len(df):
            return jsonify({'error': 'Invalid row_id'}), 400

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

                old_rec = str(df.at[row_id, 'recommendation'] or '')
                df.at[row_id, 'recommendation'] = new_recommendation

                if row_id not in _pending_changes:
                    _pending_changes[row_id] = {}
                if 'recommendation' not in _pending_changes[row_id]:
                    _pending_changes[row_id]['recommendation'] = (old_rec, new_recommendation)
                else:
                    orig_old = _pending_changes[row_id]['recommendation'][0]
                    _pending_changes[row_id]['recommendation'] = (orig_old, new_recommendation)

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


@app.route('/api/matches_all')
def get_matches_all():
    """Return full dataset as JSON for AG Grid client-side processing"""
    try:
        df = load_cached_data()
        if df.empty:
            return Response('[]', mimetype='application/json')

        needed_cols = [
            'id', 'ssn_match', 'name_score', 'address_score', 'nameaddrscore', 'recommendation',
            'how_to_process', 'canvas_id', 'canvas_addrseq', 'canvas_name',
            'canvas_address', 'canvas_city', 'canvas_state', 'canvas_zip', 'canvas_ssn',
            'dec_name', 'dec_address', 'dec_city', 'dec_state', 'dec_zip',
            'dec_hdrcode', 'dec_addrsubcode', 'dec_contact', 'dec_address_looked_up',
            'address_reason', 'jib', 'rev', 'vendor', 'memo', 'is_trust'
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
    subprocess.Popen(
        ['powershell', '-WindowStyle', 'Hidden', '-Command',
         f'Start-Process "{notes_path}";'
         ' Start-Sleep -Milliseconds 500;'
         ' (New-Object -ComObject WScript.Shell).AppActivate("Word")'],
        creationflags=0x08000000
    )
    return jsonify({'message': 'Opened in Word'})




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
            'canvas_name', 'canvas_address', 'canvas_city', 'canvas_state', 'canvas_zip',
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
    """Import Canvas IDs from file — updates in-memory only (pending until Save)"""
    global _pending_changes
    try:
        data = request.json
        field = data.get('field')
        canvas_ids = data.get('canvas_ids', [])

        if field not in ('jib', 'rev', 'vendor'):
            return jsonify({'error': 'Invalid field'}), 400
        if not canvas_ids:
            return jsonify({'error': 'No Canvas IDs provided'}), 400

        df = load_cached_data()

        # Convert canvas_id column to string for matching
        df_canvas_str = df['canvas_id'].astype(str).str.strip()
        canvas_ids_str = [str(cid).strip() for cid in canvas_ids]

        # Find matching rows (only those not already checked)
        mask = df_canvas_str.isin(canvas_ids_str) & (df[field] != 1)
        row_ids = df.index[mask].tolist()

        if not row_ids:
            total_found = int(df_canvas_str.isin(canvas_ids_str).sum())
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
            'total_in_file': len(canvas_ids_str),
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
            cid = str(df.at[row_id, 'canvas_id'])
            ssn = str(df.at[row_id, 'canvas_ssn'])
            for field, change in fields.items():
                if isinstance(change, tuple):
                    old_val, new_val = change
                else:
                    old_val, new_val = '', change
                log_entries.append((cid, ssn, field, str(old_val), str(new_val), now))

        # Write changes to Snowflake via MERGE
        affected = merge_changes_to_snowflake(DATA_CONFIG, _pending_changes, df)

        # Write audit log to Snowflake
        write_audit_log_to_snowflake(DATA_CONFIG, log_entries)

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


@app.route('/api/reload', methods=['POST'])
def reload_data():
    """Force reload data from the configured source (clears in-memory cache)"""
    try:
        df = load_cached_data(force_reload=True)
        return jsonify({
            'success': True,
            'records': len(df),
            'message': f'Reloaded {len(df):,} records from {DATA_CONFIG.get("name", DATA_CONFIG.get("source_type", "source"))}'
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


@app.route('/api/browse_excel')
def browse_excel():
    """Open a native file dialog to pick a CSV/Excel file for Canvas ID import"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        default_dir = r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\output'
        if not Path(default_dir).exists():
            default_dir = str(Path(__file__).parent)

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        file_path = filedialog.askopenfilename(
            title='Select File for Import',
            initialdir=default_dir,
            filetypes=[('Excel files', '*.xlsx *.xls'), ('CSV files', '*.csv'), ('All files', '*.*')]
        )

        root.destroy()

        if not file_path:
            return jsonify({'cancelled': True})

        return jsonify({'file_path': file_path})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Ensure Snowflake tables have required schema
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
