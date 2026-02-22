"""
BA Deduplication Review Application
Web interface for reviewing and updating canvas_dec_matches data from multiple sources
"""
from flask import Flask, render_template, request, jsonify, send_file, Response
import pandas as pd
import sqlite3
import threading
import json
from pathlib import Path
from datetime import datetime
from data_loader import load_data, save_data

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

# Load data source configurations
DATASOURCES_FILE = Path(__file__).parent / 'datasources.json'
if not DATASOURCES_FILE.exists():
    # Fallback to old config.json if datasources.json doesn't exist
    CONFIG_FILE = Path('config.json')
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            DATA_CONFIG = json.load(f)
        _active_source = 'default'
        _datasources = {'default': DATA_CONFIG}
    else:
        raise FileNotFoundError("Neither datasources.json nor config.json found")
else:
    with open(DATASOURCES_FILE, 'r') as f:
        _ds_config = json.load(f)
        _datasources = _ds_config.get('datasources', {})
        _active_source = _ds_config.get('active', list(_datasources.keys())[0])
        DATA_CONFIG = _datasources.get(_active_source, {})

# Legacy DB path for update_log (still using SQLite for audit trail)
DB_PATH = r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\ba_dedup.db'

# In-memory cache to avoid re-reading data source on every request
_df_cache = None
_df_cache_time = None

# Track unsaved jib/rev/vendor changes: {row_id: {field: new_value, ...}, ...}
_pending_changes = {}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_excel_data(force_reload=False):
    """Load data from configured source, cached in memory"""
    global _df_cache, _df_cache_time

    if _df_cache is None or force_reload:
        _df_cache = load_data(DATA_CONFIG)
        _df_cache_time = datetime.now()

    return _df_cache


def save_excel_data(df):
    """Save DataFrame back to configured data source and update cache"""
    global _df_cache
    _df_cache = df
    # Write to data source in background thread so the API response returns immediately
    df_copy = df.copy()
    config_copy = DATA_CONFIG.copy()
    threading.Thread(target=lambda: save_data(df_copy, config_copy), daemon=True).start()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/recommendations')
def get_recommendations():
    """Get distinct recommendation values from the data"""
    try:
        df = load_excel_data()
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
        df = load_excel_data()

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
            'ssn_match', 'name_score', 'address_score', 'recommendation',
            'canvas_name', 'canvas_address', 'canvas_city', 'canvas_id',
            'dec_name', 'dec_address', 'dec_city', 'dec_hdrcode',
            'jib', 'rev', 'vendor'
        }
        if order_col is not None:
            col_data = request.args.get(f'columns[{order_col}][data]', default=None)
            if col_data in sortable_fields:
                df_filtered = df_filtered.sort_values(
                    col_data, ascending=(order_dir == 'asc'), na_position='last'
                )

        # Paginate (-1 means all)
        df_page = df_filtered.iloc[start:] if length == -1 else df_filtered.iloc[start:start + length]

        # Build response — inject row IDs via the index, then fast-serialize
        df_out = df_page.fillna('')
        df_out['_row_id'] = df_page.index
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
        df = load_excel_data()
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
        return jsonify(stats)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/record/<int:row_id>')
def get_record(row_id):
    try:
        df = load_excel_data()
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
    """Update a single field on a record. JIB/Rev/Vendor are deferred (in-memory only until Save)."""
    global _pending_changes
    try:
        data = request.json
        row_id = data.get('row_id')
        field = data.get('field')
        value = data.get('value')

        if row_id is None or not field:
            return jsonify({'error': 'Missing required fields'}), 400

        allowed_fields = {
            'recommendation', 'dec_hdrcode', 'dec_name', 'dec_address',
            'dec_city', 'dec_state', 'dec_zip', 'dec_contact', 'address_reason',
            'jib', 'rev', 'vendor'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        df = load_excel_data()
        if row_id >= len(df):
            return jsonify({'error': 'Invalid row_id'}), 400

        # For jib/rev/vendor: update in-memory only, track as pending
        if field in ('jib', 'rev', 'vendor'):
            df.at[row_id, field] = int(value)
            if row_id not in _pending_changes:
                _pending_changes[row_id] = {}
            _pending_changes[row_id][field] = int(value)
            return jsonify({
                'success': True,
                'pending_count': len(_pending_changes),
                'message': 'Updated (unsaved)'
            })

        # For other fields: immediate save to DB + Excel
        record = df.iloc[row_id]
        old_value = str(record.get(field, ''))
        canvas_id = str(record.get('canvas_id', ''))
        canvas_ssn = str(record.get('canvas_ssn', ''))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE canvas_dec_matches SET {field} = ? WHERE canvas_id = ? AND canvas_ssn = ?",
            (value, canvas_id, canvas_ssn)
        )
        cursor.execute("""
            INSERT INTO update_log (canvas_id, canvas_ssn, field_name, old_value, new_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (canvas_id, canvas_ssn, field, old_value, value, datetime.now()))
        conn.commit()
        conn.close()

        df.at[row_id, field] = value
        save_excel_data(df)

        return jsonify({
            'success': True,
            'pending_count': len(_pending_changes),
            'message': 'Record updated'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bulk_update', methods=['POST'])
def bulk_update():
    """Bulk update recommendation for multiple records"""
    try:
        data = request.json
        row_ids = data.get('row_ids', [])
        new_recommendation = data.get('recommendation', 'APPROVED')

        if not row_ids:
            return jsonify({'error': 'No row IDs provided'}), 400

        df = load_excel_data()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now()

        success_count = 0
        errors = []

        for row_id in row_ids:
            try:
                if row_id >= len(df):
                    errors.append(f"Invalid row_id: {row_id}")
                    continue

                record = df.iloc[row_id]
                canvas_id = str(record.get('canvas_id', ''))
                canvas_ssn = str(record.get('canvas_ssn', ''))
                old_rec = str(record.get('recommendation', ''))

                cursor.execute(
                    "UPDATE canvas_dec_matches SET recommendation = ? WHERE canvas_id = ? AND canvas_ssn = ?",
                    (new_recommendation, canvas_id, canvas_ssn)
                )
                cursor.execute("""
                    INSERT INTO update_log (canvas_id, canvas_ssn, field_name, old_value, new_value, updated_at)
                    VALUES (?, ?, 'recommendation', ?, ?, ?)
                """, (canvas_id, canvas_ssn, old_rec, new_recommendation, now))

                df.at[row_id, 'recommendation'] = new_recommendation
                success_count += 1

            except Exception as e:
                errors.append(f"Row {row_id}: {str(e)}")

        conn.commit()
        conn.close()
        save_excel_data(df)

        return jsonify({
            'success': True,
            'updated': success_count,
            'errors': errors
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export_selected')
def export_selected():
    """Export only selected rows with JIB/Rev/Vendor columns"""
    try:
        row_ids_str = request.args.get('row_ids', '')
        if not row_ids_str:
            return jsonify({'error': 'No row IDs provided'}), 400

        row_ids = [int(x) for x in row_ids_str.split(',')]
        df = load_excel_data()
        df_selected = df.iloc[row_ids].copy()

        export_path = Path('temp_export_selected.xlsx')
        df_selected.to_excel(export_path, index=False)

        return send_file(
            export_path,
            as_attachment=True,
            download_name=f'selected_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dev_notes')
def dev_notes():
    notes_path = Path('Things to consider.docx').resolve()
    if not notes_path.exists():
        return jsonify({'error': 'Dev notes file not found'}), 404
    import os
    os.startfile(str(notes_path))
    return jsonify({'message': 'Opened in Word'})


@app.route('/api/export')
def export_data():
    try:
        df = load_excel_data()

        recommendation_filter = request.args.get('recommendation', default='')
        if recommendation_filter:
            rec_values = [v.strip() for v in recommendation_filter.split(',') if v.strip()]
            if rec_values:
                df = df[df['recommendation'].isin(rec_values)]

        export_path = Path('temp_export.xlsx')
        df.to_excel(export_path, index=False)

        return send_file(
            export_path,
            as_attachment=True,
            download_name=f'matches_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

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

        df = load_excel_data()

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

        # Track as pending
        for rid in row_ids:
            if rid not in _pending_changes:
                _pending_changes[rid] = {}
            _pending_changes[rid][field] = 1

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
    """Persist all pending jib/rev/vendor changes to DB and Excel"""
    global _pending_changes
    try:
        if not _pending_changes:
            return jsonify({'success': True, 'saved': 0, 'pending_count': 0,
                            'message': 'Nothing to save'})

        df = load_excel_data()
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now()

        update_params = []  # [(value, canvas_id, canvas_ssn)]
        log_params = []

        for row_id, fields in _pending_changes.items():
            cid = str(df.at[row_id, 'canvas_id'])
            ssn = str(df.at[row_id, 'canvas_ssn'])
            for field, new_val in fields.items():
                update_params.append((new_val, field, cid, ssn))
                log_params.append((cid, ssn, field, str(1 - new_val), str(new_val), now))

        # Batch update DB — group by field for executemany
        by_field = {}
        for new_val, field, cid, ssn in update_params:
            by_field.setdefault(field, []).append((new_val, cid, ssn))

        for field, params in by_field.items():
            cursor.executemany(
                f"UPDATE canvas_dec_matches SET {field} = ? WHERE canvas_id = ? AND canvas_ssn = ?",
                params
            )

        # Batch insert audit log
        cursor.executemany(
            "INSERT INTO update_log (canvas_id, canvas_ssn, field_name, old_value, new_value, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            log_params
        )

        conn.commit()
        conn.close()

        save_excel_data(df)

        saved_count = len(_pending_changes)
        _pending_changes = {}

        return jsonify({
            'success': True,
            'saved': saved_count,
            'pending_count': 0,
            'message': f'Saved {saved_count} record(s) to database'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reload', methods=['POST'])
def reload_data():
    """Force reload data from the configured source (clears in-memory cache)"""
    try:
        df = load_excel_data(force_reload=True)
        return jsonify({
            'success': True,
            'records': len(df),
            'message': f'Reloaded {len(df):,} records from {DATA_CONFIG.get("name", DATA_CONFIG.get("source_type", "source"))}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/update_log')
def get_update_log():
    """View recent update history"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM update_log ORDER BY updated_at DESC LIMIT 100
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/datasources')
def get_datasources():
    """Get list of available data sources"""
    try:
        if not DATASOURCES_FILE.exists():
            return jsonify({'error': 'datasources.json not found'}), 404

        with open(DATASOURCES_FILE, 'r') as f:
            ds_config = json.load(f)

        datasources_list = []
        for key, config in ds_config.get('datasources', {}).items():
            datasources_list.append({
                'id': key,
                'name': config.get('name', key),
                'type': config.get('source_type', 'unknown')
            })

        return jsonify({
            'datasources': datasources_list,
            'active': ds_config.get('active', '')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/switch_datasource', methods=['POST'])
def switch_datasource():
    """Switch to a different data source"""
    global DATA_CONFIG, _active_source, _df_cache

    try:
        data = request.json
        source_id = data.get('source_id')
        file_path = data.get('file_path')  # optional: override file path for excel

        if not source_id:
            return jsonify({'error': 'source_id is required'}), 400

        if not DATASOURCES_FILE.exists():
            return jsonify({'error': 'datasources.json not found'}), 404

        # Read current config
        with open(DATASOURCES_FILE, 'r') as f:
            ds_config = json.load(f)

        # Validate source exists
        if source_id not in ds_config.get('datasources', {}):
            return jsonify({'error': f'Data source "{source_id}" not found'}), 404

        # If a file_path was provided (Excel file picker), update the config
        if file_path and ds_config['datasources'][source_id].get('source_type') == 'excel':
            ds_config['datasources'][source_id]['file_path'] = file_path

        # Update active source
        ds_config['active'] = source_id

        # Save updated config
        with open(DATASOURCES_FILE, 'w') as f:
            json.dump(ds_config, f, indent=2)

        # Update runtime config
        _active_source = source_id
        DATA_CONFIG = ds_config['datasources'][source_id]

        # Clear cache to force reload
        _df_cache = None

        # Load new data to verify it works
        df = load_excel_data(force_reload=True)

        return jsonify({
            'success': True,
            'active': source_id,
            'name': DATA_CONFIG.get('name', source_id),
            'records': len(df),
            'message': f'Switched to {DATA_CONFIG.get("name", source_id)}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/browse_excel')
def browse_excel():
    """Open a native file dialog to pick an Excel file"""
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
            title='Select Excel File',
            initialdir=default_dir,
            filetypes=[('Excel files', '*.xlsx *.xls'), ('CSV files', '*.csv'), ('All files', '*.*')]
        )

        root.destroy()

        if not file_path:
            return jsonify({'cancelled': True})

        return jsonify({'file_path': file_path})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS update_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canvas_id TEXT,
            canvas_ssn TEXT,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            updated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add jib/rev/vendor columns to canvas_dec_matches if missing
    cursor.execute("PRAGMA table_info(canvas_dec_matches)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    for col in ('jib', 'rev', 'vendor'):
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE canvas_dec_matches ADD COLUMN {col} INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()

    print('\n' + '='*60)
    print('  BA DEDUPLICATION REVIEW APPLICATION')
    print('='*60)

    # Display data source configuration
    source_type = DATA_CONFIG.get('source_type', 'unknown').upper()
    print(f'  Data Source: {source_type}')

    if source_type == 'EXCEL':
        print(f'  File: {DATA_CONFIG.get("file_path")}')
    elif source_type == 'SQLITE':
        print(f'  Database: {DATA_CONFIG.get("db_path")}')
        print(f'  Table: {DATA_CONFIG.get("table_name")}')
    elif source_type == 'SNOWFLAKE':
        print(f'  Account: {DATA_CONFIG.get("account")}')
        print(f'  Database: {DATA_CONFIG.get("database")}.{DATA_CONFIG.get("schema")}.{DATA_CONFIG.get("table")}')

    print(f'  Audit Log: {DB_PATH}')

    df = load_excel_data()
    print(f'  Records loaded: {len(df):,}')
    if not df.empty and 'recommendation' in df.columns:
        print(f'  Recommendations: {df["recommendation"].value_counts().to_dict()}')

    print(f'\n  Open: http://localhost:5000')
    print(f'  Press Ctrl+C to stop')
    print('='*60 + '\n')

    app.run(debug=True, host='0.0.0.0', port=5000)
