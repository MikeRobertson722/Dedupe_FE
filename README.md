# BA Deduplication Review Application

Web-based interface for reviewing and updating Business Associate deduplication match records.

## Features

- **Interactive Data Table**: View and sort 31,695+ match records with real-time search
- **Smart Filtering**: Filter by recommendation type, SSN match quality
- **Edit Records**: Update DEC (match) information and recommendations
- **Bulk Operations**: Select multiple records and approve in one click
- **Live Statistics**: Dashboard showing match quality metrics
- **Export Capability**: Export filtered data to Excel
- **Audit Trail**: All updates are logged to the database with timestamps

## Installation

1. **Install Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure File Paths** (if different from defaults):
   Edit `app.py` and update these paths:
   ```python
   EXCEL_FILE = Path(r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\output\canvas_dec_matches.xlsx')
   DB_PATH = r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\ba_dedup.db'
   ```

## Running the Application

1. **Start the server**:
   ```bash
   python app.py
   ```

2. **Open your browser** to:
   ```
   http://localhost:5000
   ```

3. **Stop the server**: Press `Ctrl+C` in the terminal

## Usage Guide

### Dashboard

The main dashboard displays:
- **Total Records**: Total number of match records
- **Perfect SSN Matches**: Records with 100% SSN match
- **Average Name Score**: Average name similarity across all matches
- **Average Address Score**: Average address similarity across all matches

### Filtering

Use the filter panel to narrow down records:
- **Recommendation**: Filter by AUTO_MERGE, REVIEW, NO_MATCH, or APPROVED
- **SSN Match**: Filter by perfect (100) or imperfect (<100) matches

### Viewing Records

The main table shows:
- **Score Badges**: Color-coded scores (green=100, yellow=90+, orange=75+, red=<75)
- **Recommendation Badges**: Current match recommendation status
- **Canvas Data**: Source system information
- **DEC Data**: Matched system information

### Editing Records

1. Click the **Edit** button (pencil icon) on any row
2. Modal dialog opens with:
   - Canvas data (read-only)
   - DEC data (editable fields)
   - Match scores and recommendation
3. Make changes and click **Save Changes**
4. Changes are saved to both database and Excel file

### Quick Approve

Click the **green checkmark** button to instantly approve a match without opening the edit dialog.

### Bulk Operations

1. Check the boxes next to records you want to approve
2. Click **Bulk Approve Selected**
3. All selected records will be updated to "APPROVED" status

### Export

Click **Export Current View** to download the currently filtered data as an Excel file.

## Database Schema

The application uses two main tables:

### canvas_dec_matches
Stores all match records with scores and recommendations.

### update_log (created automatically)
Tracks all changes made through the interface:
- canvas_id
- canvas_ssn
- field_name
- old_value
- new_value
- updated_at

## Data Model

### Match Record Fields

**Canvas (Source)**:
- canvas_name, canvas_address, canvas_city, canvas_state, canvas_zip
- canvas_id, canvas_ssn

**DEC (Match)**:
- dec_hdrcode, dec_name, dec_address, dec_city, dec_state, dec_zip, dec_contact

**Scores**:
- ssn_match: SSN similarity (0-100)
- name_score: Name similarity (0-100)
- address_score: Address similarity (0-100)
- address_reason: Explanation of address match quality

**Status**:
- recommendation: AUTO_MERGE | REVIEW | NO_MATCH | APPROVED
- dec_match_count: Number of potential DEC matches found
- Number_possible_address_matches: Address match candidates

## Technical Details

### Frontend Stack
- Bootstrap 5.3 - UI framework
- DataTables 1.13 - Interactive table with server-side processing
- jQuery 3.7 - DOM manipulation
- Font Awesome 6.4 - Icons

### Backend Stack
- Flask 3.0 - Web framework
- Pandas 2.1 - Data manipulation
- SQLite3 - Database
- openpyxl 3.1 - Excel file handling

### Performance
- Server-side pagination: Only loads visible records
- Optimized queries: Fast even with 30K+ records
- Async operations: Smooth UI with no blocking

## Troubleshooting

### Port Already in Use
If port 5000 is already in use, edit `app.py` and change:
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Use different port
```

### Excel File Not Found
Check that the `EXCEL_FILE` path in `app.py` points to the correct location.

### Database Connection Error
Ensure the `DB_PATH` in `app.py` points to your SQLite database file.

### Changes Not Saving
Check the terminal for error messages. The update_log table is created automatically, but ensure the database file has write permissions.

## Security Notes

- This app is for **local development only** (debug=True)
- For production deployment:
  - Set `debug=False`
  - Change the SECRET_KEY
  - Add authentication
  - Use HTTPS
  - Implement proper input validation

## Future Enhancements

Potential improvements:
- User authentication and role-based access
- Advanced search with multiple criteria
- Batch import/export capabilities
- Match conflict resolution workflow
- Integration with external address validation APIs
- Automated backup before bulk operations
- Undo functionality for changes

## Support

For issues or questions, refer to the main BA_Dedup2 project documentation.

## License

Internal use only - not for distribution.
