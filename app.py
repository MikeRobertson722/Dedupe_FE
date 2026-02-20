"""
BA Deduplication Review Application
Web interface for reviewing and updating canvas_dec_matches.xlsx data
"""
from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'

# Configuration
EXCEL_FILE = Path(r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\output\canvas_dec_matches.xlsx')
DB_PATH = r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\ba_dedup.db'

# In-memory cache to avoid re-reading Excel on every request
_df_cache = None
_df_cache_time = None


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_excel_data(force_reload=False):
    """Load data from Excel file, cached in memory"""
    global _df_cache, _df_cache_time

    if not EXCEL_FILE.exists():
        return pd.DataFrame()

    if _df_cache is None or force_reload:
        _df_cache = pd.read_excel(EXCEL_FILE)
        _df_cache_time = datetime.now()

    return _df_cache


def save_excel_data(df):
    """Save DataFrame back to Excel and update cache"""
    global _df_cache
    df.to_excel(EXCEL_FILE, index=False)
    _df_cache = df


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
        min_addr_score = request.args.get('min_addr_score', type=float, default=None)

        # Apply filters
        mask = pd.Series(True, index=df.index)

        if recommendation_filter:
            mask &= df['recommendation'] == recommendation_filter

        if ssn_filter == 'yes':
            mask &= df['ssn_match'] == 100
        elif ssn_filter == 'no':
            mask &= df['ssn_match'] == 0
        elif ssn_filter == 'partial':
            mask &= (df['ssn_match'] > 0) & (df['ssn_match'] < 100)

        if min_name_score is not None:
            mask &= df['name_score'] >= min_name_score

        if min_addr_score is not None:
            mask &= df['address_score'] >= min_addr_score

        df_filtered = df[mask]

        # Global search across all string columns
        if search_value:
            search_mask = df_filtered.astype(str).apply(
                lambda row: row.str.contains(search_value, case=False, na=False).any(),
                axis=1
            )
            df_filtered = df_filtered[search_mask]

        records_filtered = len(df_filtered)

        # Sorting
        order_col = request.args.get('order[0][column]', type=int, default=None)
        order_dir = request.args.get('order[0][dir]', default='asc')

        col_map = {
            1: 'ssn_match', 2: 'name_score', 3: 'address_score',
            4: 'recommendation', 5: 'canvas_name', 8: 'dec_name'
        }
        if order_col in col_map:
            df_filtered = df_filtered.sort_values(
                col_map[order_col], ascending=(order_dir == 'asc'), na_position='last'
            )

        # Paginate
        df_page = df_filtered.iloc[start:start + length]

        # Build response
        data = df_page.fillna('').to_dict('records')
        for idx, (orig_idx, _) in enumerate(df_page.iterrows()):
            data[idx]['_row_id'] = int(orig_idx)

        return jsonify({
            'draw': draw,
            'recordsTotal': records_total,
            'recordsFiltered': records_filtered,
            'data': data
        })

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
    """Update a single field on a record in both DB and Excel"""
    try:
        data = request.json
        row_id = data.get('row_id')
        field = data.get('field')
        value = data.get('value')

        if row_id is None or not field:
            return jsonify({'error': 'Missing required fields'}), 400

        allowed_fields = {
            'recommendation', 'dec_hdrcode', 'dec_name', 'dec_address',
            'dec_city', 'dec_state', 'dec_zip', 'dec_contact', 'address_reason'
        }
        if field not in allowed_fields:
            return jsonify({'error': f'Field "{field}" cannot be updated'}), 400

        df = load_excel_data()
        if row_id >= len(df):
            return jsonify({'error': 'Invalid row_id'}), 400

        record = df.iloc[row_id]
        old_value = str(record.get(field, ''))
        canvas_id = str(record.get('canvas_id', ''))
        canvas_ssn = str(record.get('canvas_ssn', ''))

        # Update database
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            f"UPDATE canvas_dec_matches SET {field} = ? WHERE canvas_id = ? AND canvas_ssn = ?",
            (value, canvas_id, canvas_ssn)
        )

        # Log the change
        cursor.execute("""
            INSERT INTO update_log (canvas_id, canvas_ssn, field_name, old_value, new_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (canvas_id, canvas_ssn, field, old_value, value, datetime.now()))

        conn.commit()
        db_rows_affected = cursor.rowcount
        conn.close()

        # Update cached DataFrame and save Excel
        df.at[row_id, field] = value
        save_excel_data(df)

        return jsonify({
            'success': True,
            'db_updated': db_rows_affected > 0,
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


@app.route('/api/export')
def export_data():
    try:
        df = load_excel_data()

        recommendation_filter = request.args.get('recommendation', default='')
        if recommendation_filter:
            df = df[df['recommendation'] == recommendation_filter]

        export_path = Path('temp_export.xlsx')
        df.to_excel(export_path, index=False)

        return send_file(
            export_path,
            as_attachment=True,
            download_name=f'matches_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

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
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_database()

    print('\n' + '='*60)
    print('  BA DEDUPLICATION REVIEW APPLICATION')
    print('='*60)
    print(f'  Excel: {EXCEL_FILE}')
    print(f'  Database: {DB_PATH}')
    df = load_excel_data()
    print(f'  Records loaded: {len(df):,}')
    print(f'  Recommendations: {df["recommendation"].value_counts().to_dict()}')
    print(f'\n  Open: http://localhost:5000')
    print(f'  Press Ctrl+C to stop')
    print('='*60 + '\n')

    app.run(debug=True, host='0.0.0.0', port=5000)
