# Snowflake Data Source

The BA Review Application loads data from **Snowflake**.

## Configuration

Connection credentials are configured via environment variables (`.env` file) or directly in `app.py`'s `DATA_CONFIG`.

### Environment Variables

```bash
SNOWFLAKE_ACCOUNT=your_account_identifier
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password_here
SNOWFLAKE_DATABASE=dgo_ma
SNOWFLAKE_SCHEMA=ba_process
SNOWFLAKE_WAREHOUSE=your_warehouse
SNOWFLAKE_TABLE=import_merge_matches
```

Copy `.env.example` to `.env` and fill in your credentials.

### JSON Config (Alternative)

```json
{
  "source_type": "snowflake",
  "account": "your_account",
  "user": "your_user",
  "password": "your_password",
  "database": "your_database",
  "schema": "your_schema",
  "table": "import_merge_matches",
  "warehouse": "your_warehouse"
}
```

---

## Data Requirements

The Snowflake table must provide a DataFrame with these columns:

### Required Columns:
- `canvas_id` - Canvas identifier
- `canvas_ssn` - Canvas SSN
- `canvas_name` - Canvas name
- `canvas_address` - Canvas address
- `canvas_city` - Canvas city
- `canvas_state` - Canvas state
- `canvas_zip` - Canvas zip
- `dec_hdrcode` - DEC header code
- `dec_name` - DEC name
- `dec_address` - DEC address
- `dec_city` - DEC city
- `dec_state` - DEC state
- `dec_zip` - DEC zip
- `dec_contact` - DEC contact
- `ssn_match` - SSN match score (0-100)
- `name_score` - Name match score (0-100)
- `address_score` - Address match score (0-100)
- `recommendation` - Match recommendation
- `address_reason` - Address reason

### Optional Columns:
- `jib` - JIB flag (0 or 1)
- `rev` - Rev flag (0 or 1)
- `vendor` - Vendor flag (0 or 1)

The data loader will automatically add missing `jib`, `rev`, and `vendor` columns with default value 0.

---

## Troubleshooting

### Snowflake Connection Error
```
Error loading from Snowflake: ...
```
**Solutions:**
1. Verify credentials in `.env` or `config.json`
2. Check that `snowflake-connector-python` is installed
3. Ensure your IP is whitelisted in Snowflake network policy
4. Verify warehouse is running

### Missing Columns
If your Snowflake table is missing required columns, the application will fail with a KeyError. Ensure your table has all required columns listed above.

---

## Security Notes

### Credentials
Never commit `.env` or `config.json` with real credentials to version control.

**Best practices:**
1. Both files are listed in `.gitignore`
2. Use `.env.example` and `config.example.json` as templates with placeholder values
3. Use environment variables for sensitive data

---

## Architecture

### Key Files
- `data_loader.py` - Data abstraction layer for Snowflake
- `app.py` - Flask application with `DATA_CONFIG` for Snowflake connection

### Key Points
1. **Abstraction Layer:** All data loading goes through `data_loader.load_data(config)`
2. **Caching:** In-memory DataFrame cache avoids repeated Snowflake queries
3. **Saving:** All saves use `merge_changes_to_snowflake()` via a single MERGE statement
4. **Audit Log:** Uses Snowflake `UPDATE_LOG` table for change tracking
