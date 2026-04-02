import pandas as pd

# Read both files
original_df = pd.read_csv(r"c:\ClaudeMain\BA_Review_App\SOURCE_ADDRS.csv", encoding='utf-8-sig')
processed_df = pd.read_excel(r"c:\ClaudeMain\BA_Review_App\SOURCE_ADDRS_CLEANED.xlsx")

print("="*90)
print("SIDE-BY-SIDE COMPARISON: ORIGINAL vs PROCESSED")
print("="*90)

for idx in range(len(original_df)):
    orig_addr = original_df.iloc[idx]['SOURCE_ADDRESS']
    proc_addr = processed_df.iloc[idx]['SOURCE_ADDRESS']
    add_info = processed_df.iloc[idx]['ADDITION_ADDR_INFO']

    if add_info:  # Only show rows where info was extracted
        print(f"\nRow {idx + 1}:")
        print(f"  ORIGINAL: {orig_addr}")
        print(f"  CLEANED:  {proc_addr}")
        print(f"  EXTRACTED: {add_info}")
        print(f"  {'-'*86}")

print(f"\n{'='*90}")
print(f"STATISTICS:")
print(f"{'='*90}")
print(f"Total addresses: {len(processed_df)}")
print(f"Addresses with extracted info: {len(processed_df[processed_df['ADDITION_ADDR_INFO'] != ''])}")
print(f"Clean addresses (no extraction): {len(processed_df[processed_df['ADDITION_ADDR_INFO'] == ''])}")
