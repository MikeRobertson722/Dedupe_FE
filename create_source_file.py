import pandas as pd
import openpyxl

# Read the CSV content and create Excel file
# The user provided the data, so we'll read it from the CSV format

try:
    # The document shows CSV format, so let's try reading it
    # First, let's create a simple version from the provided data

    print("Creating SOURCE_ADDRS.xlsx from provided data...")

    # Try to find and read any existing address file
    import os

    # Check current directory
    files = os.listdir('.')
    print(f"Files in current directory: {[f for f in files if 'ADDR' in f.upper() or 'SOURCE' in f.upper()]}")

    # If we have the CSV from the document, read it
    if os.path.exists('SOURCE_ADDRS.csv'):
        df = pd.read_csv('SOURCE_ADDRS.csv', encoding='utf-8-sig')
        print(f"Found CSV file with {len(df)} rows")
    else:
        print("No source file found. Please provide the SOURCE_ADDRS.xlsx or .csv file")
        exit(1)

    # Save as Excel
    df.to_excel('SOURCE_ADDRS.xlsx', index=False)
    print(f"✓ Created SOURCE_ADDRS.xlsx with {len(df)} rows and {len(df.columns)} columns")
    print(f"  Columns: {df.columns.tolist()}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
