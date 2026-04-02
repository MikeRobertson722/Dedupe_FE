"""
Address Cleaning Script
Separates non-address information from SOURCE_ADDRESS column into ADDITION_ADDR_INFO column

Usage: python clean_addresses.py [input_file] [output_file]
Example: python clean_addresses.py SOURCE_ADDRS.xlsx SOURCE_ADDRS_CLEANED.xlsx
"""

import pandas as pd
import re
import sys
import os

def separate_address_components(address):
    """
    Separate non-address information from the actual address.
    Returns: (additional_info, clean_address)
    """
    if pd.isna(address) or str(address).strip() == '':
        return '', address

    original = str(address).strip()
    additional_info_parts = []
    remaining = original

    # Try each pattern in sequence
    patterns_found = True
    while patterns_found:
        patterns_found = False
        old_remaining = remaining

        # Pattern: FBO (For Benefit Of)
        match = re.match(r'^(FBO\s+[^,]+?)\s{2,}(.+)$', remaining)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: C/O (Care Of)
        match = re.match(r'^(C/O\s+[^,]+?)\s{2,}(.+)$', remaining)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: DBA (Doing Business As)
        match = re.match(r'^(DBA\s+[^,]+?)\s{2,}(.+)$', remaining)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: ATTN (Attention)
        match = re.match(r'^(ATTN:?\s+[^,]+?)\s{2,}(.+)$', remaining, re.IGNORECASE)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: % references (e.g., "%LORENZO T COLLINS  PO BOX 1781")
        match = re.match(r'^(%[^,]+?)\s{2,}(.+)$', remaining)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: AGENT references (must come before address)
        match = re.match(r'^(.+?\s+(?:CO\s+)?AGENT)\s{2,}(.+)$', remaining, re.IGNORECASE)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: TRUSTEE/TTEE references
        match = re.match(r'^(.+?\s+(?:TRUSTEE|TTEE|TRUST\s+DEPT))\s{2,}(.+)$', remaining, re.IGNORECASE)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: MANAGER references
        match = re.match(r'^(.+?\s+MANAGER[^,]*?)\s{2,}(.+)$', remaining, re.IGNORECASE)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: Department references before address
        match = re.match(r'^((?:BILLING|JOINT\s+INTEREST|GAS\s+BALANCING|REVENUE)\s+(?:DEPT|DEPARTMENT)[^,]*?)\s{2,}(.+)$', remaining, re.IGNORECASE)
        if match:
            additional_info_parts.append(match.group(1).strip())
            remaining = match.group(2).strip()
            patterns_found = True
            continue

        # Pattern: General pattern - company/org name followed by 2+ spaces then address
        # Only if the address part starts with typical address indicators
        match = re.match(r'^([^,]{5,}?)\s{2,}((?:P\s*\.?\s*O\s*\.?\s*BOX|PO\s+BOX|DEPT|\d+\s+[A-Z]).+)$', remaining)
        if match:
            company_part = match.group(1).strip()
            address_part = match.group(2).strip()

            # Check if company part doesn't look like an address
            if not re.match(r'^\d', company_part) and \
               not re.search(r'\b(?:STREET|ST|AVENUE|AVE|ROAD|RD|DRIVE|DR|LANE|LN|SUITE|STE|APT|COURT|CT|CIRCLE|CIR|WAY|BLVD|PARKWAY|PKWY)\b',
                           company_part, re.IGNORECASE):
                additional_info_parts.append(company_part)
                remaining = address_part
                patterns_found = True
                continue

    # Return results
    final_additional_info = ' | '.join(additional_info_parts) if additional_info_parts else ''
    return final_additional_info, remaining


def process_file(input_file, output_file=None):
    """Process the address file and separate components"""

    # Determine input file type
    file_extension = os.path.splitext(input_file)[1].lower()

    print(f"Reading: {input_file}")
    print("=" * 70)

    # Read the file
    try:
        if file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(input_file)
        elif file_extension == '.csv':
            df = pd.read_csv(input_file, encoding='utf-8-sig')
        else:
            print(f"Error: Unsupported file type '{file_extension}'")
            return

        print(f"✓ Loaded {len(df):,} rows")
        print(f"✓ Columns: {', '.join(df.columns.tolist())}\n")
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Verify required columns
    if 'SOURCE_ADDRESS' not in df.columns:
        print("Error: 'SOURCE_ADDRESS' column not found")
        print(f"Available columns: {df.columns.tolist()}")
        return

    # Process addresses
    processed_data = []
    stats = {
        'total': len(df),
        'extracted': 0,
        'unchanged': 0,
        'empty': 0
    }

    print("Processing addresses...\n")

    for idx, row in df.iterrows():
        source_addr = row['SOURCE_ADDRESS']

        if pd.isna(source_addr) or str(source_addr).strip() == '':
            stats['empty'] += 1
            processed_data.append({
                'SOURCE_ADDRESS': source_addr,
                'ADDITION_ADDR_INFO': ''
            })
            continue

        # Extract additional info from address
        extracted_info, clean_addr = separate_address_components(source_addr)

        if extracted_info:
            stats['extracted'] += 1
            # Show first 10 examples
            if stats['extracted'] <= 10:
                print(f"Example {stats['extracted']}:")
                print(f"  Original: {str(source_addr)[:75]}...")
                print(f"  Clean:    {str(clean_addr)[:75]}...")
                print(f"  Extracted: {extracted_info}")
                print()
        else:
            stats['unchanged'] += 1

        processed_data.append({
            'SOURCE_ADDRESS': clean_addr,
            'ADDITION_ADDR_INFO': extracted_info
        })

    # Create new dataframe
    df_processed = pd.DataFrame(processed_data)

    # Determine output file
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_CLEANED{ext}"

    # Save the result
    output_extension = os.path.splitext(output_file)[1].lower()
    if output_extension in ['.xlsx', '.xls']:
        df_processed.to_excel(output_file, index=False, engine='openpyxl')
    else:
        df_processed.to_csv(output_file, index=False, encoding='utf-8-sig')

    # Print summary
    print("=" * 70)
    print("✓ PROCESSING COMPLETE")
    print("=" * 70)
    print(f"  Total addresses:            {stats['total']:,}")
    print(f"  Info extracted from:        {stats['extracted']:,} ({stats['extracted']/stats['total']*100:.1f}%)")
    print(f"  Unchanged:                  {stats['unchanged']:,} ({stats['unchanged']/stats['total']*100:.1f}%)")
    print(f"  Empty:                      {stats['empty']:,}")
    print(f"\n  Input file:  {input_file}")
    print(f"  Output file: {output_file}")
    print("=" * 70)

    return df_processed


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
    else:
        # Look for SOURCE_ADDRS file
        if os.path.exists('SOURCE_ADDRS.xlsx'):
            input_file = 'SOURCE_ADDRS.xlsx'
        elif os.path.exists('SOURCE_ADDRS.csv'):
            input_file = 'SOURCE_ADDRS.csv'
        else:
            print("Error: No input file specified and SOURCE_ADDRS.xlsx/csv not found")
            print("\nUsage: python clean_addresses.py [input_file] [output_file]")
            sys.exit(1)

        output_file = None

    # Process the file
    process_file(input_file, output_file)
