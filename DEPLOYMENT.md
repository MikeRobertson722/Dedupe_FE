# BA Deduplication Review Application - Deployment Guide

## Application Overview

The BA Deduplication Review Application is an internal web tool for reviewing and processing Business Associate import/merge match records. It provides a data grid interface backed by Snowflake for viewing, filtering, editing, approving, and staging deduplicated BA records.

**Stack:** Python/Flask backend, AG Grid v32 frontend, Snowflake data warehouse

---

## Prerequisites

### System Requirements

- **Python** 3.10 or higher
- **Web browser** (Chrome, Edge, or Firefox - modern version)
- **Network access** to Snowflake cloud (`*.snowflakecomputing.com`)
- **Network access** to CDN assets (jsdelivr.net, cdnjs.cloudflare.com, code.jquery.com) OR locally-hosted copies of these libraries

### Snowflake Requirements

- A Snowflake account with an active warehouse
- A database and schema containing the `IMPORT_MERGE_MATCHES` table
- A Snowflake role with the following permissions:
  - `SELECT`, `UPDATE`, `INSERT` on `IMPORT_MERGE_MATCHES`
  - `CREATE TABLE` (for first-run schema setup of `UPDATE_LOG` and `IMPORT_MERGE_STAGING`)
  - `ALTER TABLE` (for first-run column migrations)
  - `SELECT`, `INSERT` on `UPDATE_LOG` (audit log)
  - `SELECT`, `INSERT` on `IMPORT_MERGE_STAGING` (staging table)
  - `SELECT` on `BA_CONFIG` (score configuration)
- Authentication method: either **password-based** or **SSO (externalbrowser)** via Microsoft identity provider

### Snowflake Tables

The application expects/creates these tables in the configured schema:

| Table | Purpose | Created By |
|-------|---------|------------|
| `IMPORT_MERGE_MATCHES` | Primary data table with BA match records | Must exist before deployment |
| `UPDATE_LOG` | Audit log for all field changes | Auto-created on first startup |
| `IMPORT_MERGE_STAGING` | Staging table for approved records | Auto-created on first startup (cloned from MATCHES) |
| `BA_CONFIG` | Score range configuration (BUCKETS category) | Must exist if score auto-fill is needed |

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/MikeRobertson722/Dedupe_FE.git
cd Dedupe_FE
```

### 2. Create a Python Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies:**
| Package | Version | Purpose |
|---------|---------|---------|
| flask | 3.0.0 | Web framework |
| pandas | 2.1.4 | Data manipulation and in-memory cache |
| openpyxl | 3.1.2 | Excel export support |
| python-dotenv | 1.0.1 | Environment variable loading from .env |
| snowflake-connector-python | 3.12.3 | Snowflake database connectivity |

### 4. Configure Environment Variables

Copy the example environment file and fill in your Snowflake credentials:

```bash
cp .env.example .env
```

Edit `.env` with your deployment values:

```env
# Required
SNOWFLAKE_ACCOUNT=your_account_identifier
SNOWFLAKE_USER=your_username
SNOWFLAKE_DATABASE=dgo_ma
SNOWFLAKE_SCHEMA=ba_process
SNOWFLAKE_TABLE=import_merge_matches

# Authentication - choose ONE method:

# Option A: Password-based authentication
SNOWFLAKE_PASSWORD=your_password_here

# Option B: SSO/External browser authentication
# SNOWFLAKE_AUTHENTICATOR=externalbrowser

# Optional
SNOWFLAKE_WAREHOUSE=your_warehouse
SNOWFLAKE_ROLE=your_role
```

**Important:** The `.env` file contains credentials and is excluded from version control via `.gitignore`. Never commit this file.

#### Authentication Methods

| Method | Config | Use Case |
|--------|--------|----------|
| Password | Set `SNOWFLAKE_PASSWORD` | Service accounts, automated deployments |
| External Browser (SSO) | Set `SNOWFLAKE_AUTHENTICATOR=externalbrowser` | Interactive use with corporate SSO (Microsoft) |
| Key Pair | Requires custom `data_loader.py` changes | Headless production servers |

**Note:** SSO authentication (`externalbrowser`) opens a browser window on first connection for user login. This is suitable for desktop/interactive deployments but **not suitable for headless servers**. For headless production, use password or key-pair authentication.

---

## Running the Application

### Development Mode (Built-in Flask Server)

```bash
python app.py
```

The application will:
1. Connect to Snowflake (SSO will open a browser for authentication)
2. Verify/create the schema (UPDATE_LOG, IMPORT_MERGE_STAGING tables)
3. Load all records from `IMPORT_MERGE_MATCHES` into an in-memory cache
4. Start the Flask development server on `http://0.0.0.0:5000`

**Console output on successful startup:**
```
  Snowflake schema verified

============================================================
  BA DEDUPLICATION REVIEW APPLICATION
============================================================
  Data Source: SNOWFLAKE
  Account: your_account_identifier
  Database: dgo_ma.ba_process.import_merge_matches
  Records loaded: 31,695

  Open: http://localhost:5000
  Press Ctrl+C to stop
============================================================
```

### Production Deployment (WSGI Server)

The built-in Flask development server is **not recommended for production**. Use a production WSGI server:

#### Option A: Gunicorn (Linux/macOS)

```bash
pip install gunicorn

gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 120 app:app
```

**Important:** Use `--workers 1` (single worker). The application uses an in-memory DataFrame cache and pending changes dictionary that are not shared across processes. Multiple workers would cause data inconsistency.

#### Option B: Waitress (Windows/Cross-platform)

```bash
pip install waitress

waitress-serve --host=0.0.0.0 --port=5000 --threads=4 app:app
```

#### Startup Initialization

When using a WSGI server, the schema verification and data loading that normally happen in the `if __name__ == '__main__'` block will **not** execute automatically. You must either:

1. **Run the initialization manually before starting the WSGI server:**
   ```python
   # init_app.py
   from app import load_cached_data, DATA_CONFIG
   from data_loader import ensure_snowflake_schema

   ensure_snowflake_schema(DATA_CONFIG)
   load_cached_data()
   ```

2. **Or add initialization to a Flask `before_first_request` equivalent:**
   Add to `app.py`:
   ```python
   _initialized = False

   @app.before_request
   def initialize_once():
       global _initialized
       if not _initialized:
           ensure_snowflake_schema(DATA_CONFIG)
           load_cached_data()
           _initialized = True
   ```

---

## Architecture Notes

### In-Memory Data Model

The application loads the **entire dataset** from Snowflake into a pandas DataFrame at startup. All reads are served from this in-memory cache. This design means:

- **Fast reads** - No per-request database queries for grid data
- **Memory usage** - The server must have enough RAM to hold the full dataset (~31K records = ~50-100 MB depending on column widths)
- **Single process only** - The cache is a module-level global; multiple workers will have separate, inconsistent caches
- **Edits are deferred** - Changes are tracked in a `_pending_changes` dictionary and only written to Snowflake when the user clicks "Save Changes"
- **Data refresh** - Users can click "Refresh" to reload from Snowflake, which discards unsaved changes

### Connection Management

Snowflake connections are **persistent and cached** to avoid repeated SSO browser popups. A health check (`SELECT 1`) runs every 60 seconds. If the connection drops, it reconnects automatically.

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Main application page |
| `/api/matches_all` | GET | Full dataset as JSON (AG Grid client-side mode) |
| `/api/matches` | GET | Paginated/filtered data (legacy DataTables mode) |
| `/api/stats` | GET | Record counts and score statistics |
| `/api/recommendations` | GET | Distinct recommendation values |
| `/api/staging_count` | GET | Count of records eligible for staging |
| `/api/record/<row_id>` | GET | Single record by in-memory row index |
| `/api/db_record/<uid>` | GET | Single record direct from Snowflake by ID |
| `/api/update` | POST | Update a single field on a record (in-memory) |
| `/api/bulk_update` | POST | Bulk update recommendation (in-memory) |
| `/api/bulk_field_update` | POST | Bulk update any allowed field (in-memory) |
| `/api/save_changes` | POST | Persist all pending changes to Snowflake |
| `/api/search_replace` | POST | Find/replace text across columns |
| `/api/import_ids` | POST | Import Source IDs from file for flag matching |
| `/api/stage_approved` | POST | Copy approved records to staging table |
| `/api/reload` | POST | Force-reload data from Snowflake |
| `/api/update_log` | GET | Recent audit log entries |
| `/api/datasources` | GET | Active data source info |

---

## Security Considerations

### Application-Level

- **SECRET_KEY**: The Flask `SECRET_KEY` is hardcoded as `'dev-secret-key-change-in-production'` in `app.py`. **Change this** to a strong random value for production:
  ```python
  app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'generate-a-random-key-here')
  ```
  Or set `FLASK_SECRET_KEY` in your `.env` file.

- **No authentication**: The application has **no built-in user authentication or authorization**. Any user with network access to the server can view and modify data. In production, place it behind:
  - A reverse proxy with SSO/SAML authentication (e.g., nginx + OAuth2 Proxy)
  - A VPN or restricted network segment
  - Windows Integrated Authentication if deploying on IIS

- **CORS**: No CORS headers are configured. The application is designed to be accessed directly (same-origin). If embedding in another application, add CORS configuration.

- **Input validation**: The backend validates field names against an `allowed_fields` whitelist before accepting updates. SQL parameters are passed via parameterized queries (no SQL injection risk).

### Network

- **HTTPS**: Flask's built-in server does not support HTTPS. For production, terminate TLS at a reverse proxy (nginx, Apache, IIS).
- **CDN dependencies**: The frontend loads JavaScript/CSS from public CDNs (jsdelivr.net, cdnjs.cloudflare.com, code.jquery.com). For air-gapped environments, download these files and serve them locally:
  - Bootstrap 5.3.0 (CSS + JS bundle)
  - AG Grid Community 32 (CSS + JS)
  - Font Awesome 6.4.0 (CSS)
  - jQuery 3.7.0

### Credential Management

- Never commit `.env` files to version control
- For SSO deployments, credential caching (`client_store_temporary_credential`) is enabled
- Consider using a secrets manager (Azure Key Vault, AWS Secrets Manager) instead of `.env` files in production

---

## Reverse Proxy Configuration

### nginx Example

```nginx
server {
    listen 443 ssl;
    server_name ba-review.yourcompany.com;

    ssl_certificate     /etc/ssl/certs/ba-review.crt;
    ssl_certificate_key /etc/ssl/private/ba-review.key;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Large responses for full dataset endpoint
        proxy_read_timeout 120s;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
    }
}
```

### IIS (Windows) with URL Rewrite

1. Install URL Rewrite module and ARR (Application Request Routing)
2. Create a reverse proxy rule pointing to `http://localhost:5000`
3. Enable Windows Authentication on the IIS site if needed

---

## Running Tests

The test suite uses Playwright for browser-based regression testing.

```bash
# Install test dependencies
pip install pytest playwright requests
python -m playwright install chromium

# Run tests (Flask server must be running or will auto-start)
pytest tests/ -v
```

Tests are organized by feature area:
- `test_01_page_load.py` - Application loads and grid renders
- `test_02_filtering.py` - Filter controls work correctly
- `test_03_table_controls.py` - Sorting, pagination, column operations
- `test_04_column_operations.py` - Show/hide, reorder columns
- `test_05_selection_copy.py` - Cell/row selection and clipboard
- `test_06_visual_indicators.py` - Score badges, trust highlights
- `test_07_row_actions.py` - Edit modal, quick approve
- `test_08_ba_type_flags.py` - JIB/Rev/Vendor toggles
- `test_09_export.py` - CSV/Excel export
- `test_12_search_replace.py` - Search & replace functionality
- `test_13_inline_editing.py` - In-grid cell editing
- `test_14_undo_redo.py` - Undo/redo stack
- `test_15_save_changes.py` - Persist to Snowflake
- `test_16_addr_score_filters.py` - Score range filtering
- `test_17_confirm_modal_grid_info.py` - Confirmation dialogs

---

## Monitoring and Troubleshooting

### Logs

The application logs to stdout/stderr. Key log messages:

| Message | Meaning |
|---------|---------|
| `Snowflake schema verified` | Schema check passed on startup |
| `Records loaded: N` | Data loaded successfully |
| `BA_CONFIG loaded: N score params` | Score configuration loaded |
| `[MERGE DEBUG] fields=..., rows=...` | Save operation details |
| `Adding STAGED_AT to ... skipped` | Non-critical schema migration warning |

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SNOWFLAKE_ACCOUNT not set` on startup | Missing or empty `.env` file | Create `.env` from `.env.example` with valid credentials |
| Browser popup on every restart | SSO authentication with `externalbrowser` | Normal behavior; authenticate once per session. For headless, switch to password auth |
| `snowflake-connector-python not installed` | Missing dependency | Run `pip install -r requirements.txt` |
| Empty grid / no data | Snowflake table is empty or connection failed | Check Flask console output for errors; verify table has data |
| Columns missing data | Column not in `needed_cols` whitelist in `app.py` | Add the column name to both `needed_cols` lists in `/api/matches` and `/api/matches_all` |
| Changes not persisting after restart | User didn't click "Save Changes" | Edits are in-memory until saved; remind users to save |
| High memory usage | Large dataset loaded into pandas DataFrame | Monitor with `len(df)` on startup; consider filtering data at the SQL level if dataset grows significantly |

### Health Check Endpoint

Use `/api/stats` as a health check endpoint. A 200 response with JSON data confirms the application is running and has loaded data.

```bash
curl http://localhost:5000/api/stats
```

---

## Backup and Recovery

- **Snowflake data** is the source of truth. The in-memory cache is ephemeral.
- **Audit trail**: All changes are logged to the `UPDATE_LOG` table with old/new values, timestamps, and Source ID/SSN.
- **Staging**: Approved records are copied to `IMPORT_MERGE_STAGING` before being flagged as `STAGED` in the source table. This is a one-way operation within a single transaction (atomic).
- **Unsaved changes**: If the server process crashes, any unsaved in-memory changes are lost. Users should save frequently.

---

## File Structure

```
BA_Review_App/
    app.py                  # Flask application (routes, API endpoints)
    data_loader.py          # Snowflake data layer (connection, queries, MERGE)
    requirements.txt        # Python dependencies
    .env.example            # Environment variable template
    .env                    # Local credentials (not in version control)
    .gitignore              # Git ignore rules
    templates/
        index.html          # Main HTML template (Bootstrap + AG Grid)
    static/
        css/
            style.css       # Application styles, AG Grid theme overrides
        js/
            app.js          # Frontend logic (grid config, editing, undo/redo)
    tests/
        conftest.py         # Pytest fixtures (server lifecycle, page helpers)
        helpers/            # Shared test utilities
        test_*.py           # Playwright regression tests
```
