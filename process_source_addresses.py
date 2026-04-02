"""
Address Processing Script
Separates non-address information from SOURCE_ADDRESS column into ADDITION_ADDR_INFO column
"""

import pandas as pd
import re
import sys
import os

def separate_address_components(address):
    """
    Separate non-address information from the actual address.
    Returns: (additional_info, clean_address)

    Extracts patterns like:
    - FBO (For Benefit Of) + name
    - C/O (Care Of) + name/entity
    - DBA (Doing Business As) + business name
    - ATTN (Attention) + person name
    - TRUSTEE/TTEE + trustee name
    - AGENT + agent name
    - Company/organization names before addresses
    """
    if pd.isna(address) or str(address).strip() == '':
        return '', address

    address = str(address).strip()
    additional_info_parts = []
    remaining = address

    # Pattern 1: FBO (For Benefit Of)
    # Example: "FBO TIFFANY DAWN IRWIN  5100 N CLASSEN BLVD., STE 620"
    match = re.match(r'^(FBO\s+[^,]+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 2: C/O (Care Of)
    # Example: "C/O BANK OF TEXAS  306 W WALL STREET, SUITE 100"
    match = re.match(r'^(C/O\s+[^,]+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 3: DBA (Doing Business As)
    # Example: "DBA ALIAS CYBERSECURITY   4308 GRANT BOULEVARD, SUITE E/F"
    match = re.match(r'^(DBA\s+[^,]+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 4: ATTN (Attention)
    # Example: "ATTN:  CLINT GERACI - CREDIT PORTFOLIO ANALYST  909 FANNIN ST  STE 700"
    match = re.match(r'^(ATTN:?\s+[^,]+?)\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 5: Percentage sign references
    # Example: "%LORENZO T COLLINS  PO BOX 1781"
    match = re.match(r'^(%[^,]+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 6: AGENT references
    # Example: "FARMERS NATIONAL CO AGENT  6421 CAMP BOWIE BLVD STE 314"
    match = re.match(r'^(.+?\s+(?:AGENT|CO\s+AGENT))\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 7: TRUSTEE/TTEE references
    # Example: "REGIONS BANK TRUST DEPT  PO BOX 2020"
    match = re.match(r'^(.+?\s+(?:TRUSTEE|TTEE|TRUST\s+DEPT))\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 8: Manager references
    # Example: "MANAGER JOINT INTEREST OPERATIONS  CITATION OIL & GAS CORP  PO BOX 690688"
    match = re.match(r'^(MANAGER\s+[^,]+?)\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 9: General company/organization names before address
    # Look for multiple spaces followed by typical address starts
    match = re.match(r'^([^,]{3,}?)\s{2,}((?:PO\s+BOX|P\s*\.?\s*O\s*\.?\s*BOX|P\s+O\s+BOX|\d+\s+[A-Z]).+)$', remaining)
    if match:
        company_part = match.group(1).strip()
        address_part = match.group(2).strip()

        # Check if the company part doesn't look like an address itself
        # (i.e., doesn't start with a number and doesn't contain street indicators)
        if not re.match(r'^\d', company_part) and \
           not re.search(r'\b(?:STREET|ST|AVENUE|AVE|ROAD|RD|DRIVE|DR|LANE|LN|SUITE|STE|APT|COURT|CT)\b',
                        company_part, re.IGNORECASE):
            additional_info_parts.append(company_part)
            remaining = address_part

    # Combine all additional info
    final_additional_info = ' | '.join(additional_info_parts) if additional_info_parts else ''

    return final_additional_info, remaining


def main():
    # Check if input file exists
    input_file = None
    if os.path.exists('SOURCE_ADDRS.xlsx'):
        input_file = 'SOURCE_ADDRS.xlsx'
        file_type = 'excel'
    elif os.path.exists('SOURCE_ADDRS.csv'):
        input_file = 'SOURCE_ADDRS.csv'
        file_type = 'csv'
    else:
        print("Error: Could not find SOURCE_ADDRS.xlsx or SOURCE_ADDRS.csv")
        print("\nPlease ensure the input file exists in the current directory.")
        print(f"Current directory: {os.getcwd()}")
        return

    print(f"Processing: {input_file}")
    print("="* 60)

    # Read the file
    try:
        if file_type == 'excel':
            df = pd.read_excel(input_file)
        else:
            df = pd.read_csv(input_file, encoding='utf-8-sig')

        print(f"✓ Loaded {len(df)} rows")
        print(f"✓ Columns: {df.columns.tolist()}\n")
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Verify required columns
    if 'SOURCE_ADDRESS' not in df.columns:
        print("Error: 'SOURCE_ADDRESS' column not found in the file")
        print(f"Available columns: {df.columns.tolist()}")
        return

    # Process each address
    processed_data = []
    stats = {'extracted': 0, 'unchanged': 0}

    print("Processing addresses...")
    for idx, row in df.iterrows():
        source_addr = row['SOURCE_ADDRESS']
        current_additional = row.get('ADDITION_ADDR_INFO', '')

        # Extract additional info from address
        extracted_info, clean_addr = separate_address_components(source_addr)

        # Track stats
        if extracted_info:
            stats['extracted'] += 1
        else:
            stats['unchanged'] += 1

        # Combine with any existing additional info
        if pd.notna(current_additional) and str(current_additional).strip():
            if extracted_info:
                final_additional = f"{extracted_info} | {current_additional}"
            else:
                final_additional = current_additional
        else:
            final_additional = extracted_info

        processed_data.append({
            'SOURCE_ADDRESS': clean_addr,
            'ADDITION_ADDR_INFO': final_additional
        })

        # Show first few examples
        if idx < 15 and extracted_info:
            print(f"\nExample {stats['extracted']}:")
            print(f"  Before: {source_addr[:80]}...")
            print(f"  After:  {clean_addr[:80]}...")
            print(f"  Info:   {final_additional}")

    # Create new dataframe
    df_processed = pd.DataFrame(processed_data)

    # Save to Excel
    output_file = 'SOURCE_ADDRS_PROCESSED.xlsx'
    df_processed.to_excel(output_file, index=False, engine='openpyxl')

    print("\n" + "=" * 60)
    print("✓ PROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Total addresses processed: {len(df_processed):,}")
    print(f"  Addresses with info extracted: {stats['extracted']:,} ({stats['extracted']/len(df_processed)*100:.1f}%)")
    print(f"  Addresses unchanged: {stats['unchanged']:,} ({stats['unchanged']/len(df_processed)*100:.1f}%)")
    print(f"\n  Output file: {output_file}")
    print("=" * 60)

if __name__ == "__main__":
    main()
