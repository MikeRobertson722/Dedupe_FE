"""
This script creates the SOURCE_ADDRS.csv file from the document data provided.
Run this first, then run clean_addresses.py to process it.
"""

# Note: You should paste the full CSV content from your document into a file named SOURCE_ADDRS.csv
# Or, if you have it in Excel format already, just save it as SOURCE_ADDRS.xlsx

print("Please save your address data as either:")
print("  - SOURCE_ADDRS.xlsx (Excel format)")
print("  - SOURCE_ADDRS.csv (CSV format)")
print("\nThen run: python clean_addresses.py")
print("\nThe script will:")
print("  1. Read your SOURCE_ADDRESS column")
print("  2. Extract non-address info (FBO, C/O, DBA, ATTN, Agent names, etc.)")
print("  3. Place extracted info in ADDITION_ADDR_INFO column")
print("  4. Save cleaned version to SOURCE_ADDRS_CLEANED.xlsx")
