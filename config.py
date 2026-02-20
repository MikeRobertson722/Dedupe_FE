"""
Configuration file for BA Review App
Edit these paths to match your environment
"""
from pathlib import Path

# Path to the Excel file containing match data
EXCEL_FILE = Path(r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\output\canvas_dec_matches.xlsx')

# Path to the SQLite database
DB_PATH = r'C:\ClaudeMain\BA_Dedup2\BA_Dedup2\ba_dedup.db'

# Flask configuration
SECRET_KEY = 'dev-secret-key-change-in-production'
DEBUG = True
HOST = '0.0.0.0'
PORT = 5000

# DataTables configuration
DEFAULT_PAGE_LENGTH = 25
MAX_PAGE_LENGTH = 500
