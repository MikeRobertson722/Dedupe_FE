import pandas as pd
import re
import openpyxl

def separate_address_components(address):
    """
    Separate non-address information from the actual address.
    Returns: (additional_info, clean_address)

    Patterns to extract:
    - FBO (For Benefit Of)
    - C/O (Care Of)
    - DBA (Doing Business As)
    - ATTN (Attention)
    - TRUSTEE/TTEE references
    - AGENT references
    - Company names before addresses
    """
    if pd.isna(address) or str(address).strip() == '':
        return '', address

    address = str(address).strip()
    additional_info_parts = []
    remaining = address

    # Pattern 1: FBO (For Benefit Of) - extract everything before the actual address
    match = re.match(r'^FBO\s+(.+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(f"FBO {match.group(1).strip()}")
        remaining = match.group(2).strip()

    # Pattern 2: C/O (Care Of)
    match = re.match(r'^C/O\s+(.+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(f"C/O {match.group(1).strip()}")
        remaining = match.group(2).strip()

    # Pattern 3: DBA (Doing Business As)
    match = re.match(r'^DBA\s+(.+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(f"DBA {match.group(1).strip()}")
        remaining = match.group(2).strip()

    # Pattern 4: ATTN (Attention)
    match = re.match(r'^ATTN:?\s+(.+?)\s{2,}(.+)$', remaining)
    if match:
        additional_info_parts.append(f"ATTN {match.group(1).strip()}")
        remaining = match.group(2).strip()

    # Pattern 5: Company/Person name with AGENT
    match = re.match(r'^(.+?\s+(?:AGENT|CO\s+AGENT))\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 6: Trustee references
    match = re.match(r'^(.+?\s+(?:TRUSTEE|TTEE))\s{2,}(.+)$', remaining, re.IGNORECASE)
    if match:
        additional_info_parts.append(match.group(1).strip())
        remaining = match.group(2).strip()

    # Pattern 7: General account or company name before address (multiple spaces indicate separation)
    # This catches patterns like "GENERAL ACCOUNT  PO BOX 4242"
    match = re.match(r'^([A-Z][A-Z\s&\.,\(\)]+?)\s{2,}((?:PO\s+BOX|P\s*O\s+BOX|P\s*\.?\s*O\s*\.?\s*BOX|\d+).+)$', remaining)
    if match:
        company_name = match.group(1).strip()
        # Only add if it looks like a company name (not part of address)
        if not re.match(r'^\d', company_name):
            additional_info_parts.append(company_name)
            remaining = match.group(2).strip()

    # Pattern 8: Catch any remaining multiple spaces that might indicate separation
    match = re.match(r'^([^,]+?)\s{3,}(.+)$', remaining)
    if match:
        potential_info = match.group(1).strip()
        potential_addr = match.group(2).strip()
        # Check if the first part doesn't look like an address
        if not re.match(r'^\d', potential_info) and not re.search(r'\bSUITE\b|\bAPT\b|\bRM\b|\bBOX\b', potential_info, re.IGNORECASE):
            additional_info_parts.append(potential_info)
            remaining = potential_addr

    # Combine all additional info
    additional_info = ' | '.join(additional_info_parts) if additional_info_parts else ''

    return additional_info, remaining

# Main processing
try:
    # Try to read as Excel first
    try:
        df = pd.read_excel('SOURCE_ADDRS.xlsx')
        print("Read from Excel file")
    except:
        # Try CSV
        df = pd.read_csv('SOURCE_ADDRS.csv', encoding='utf-8-sig')
        print("Read from CSV file")

    print(f"Loaded {len(df)} rows")
    print(f"Columns: {df.columns.tolist()}")

    # Process each address
    processed_data = []
    for idx, row in df.iterrows():
        source_addr = row['SOURCE_ADDRESS']
        current_additional = row.get('ADDITION_ADDR_INFO', '')

        # Extract additional info from address
        extracted_info, clean_addr = separate_address_components(source_addr)

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
        if idx < 10:
            print(f"\nRow {idx + 1}:")
            print(f"  Original: {source_addr}")
            print(f"  Clean: {clean_addr}")
            print(f"  Info: {final_additional}")

    # Create new dataframe
    df_processed = pd.DataFrame(processed_data)

    # Save to Excel
    df_processed.to_excel('SOURCE_ADDRS_PROCESSED.xlsx', index=False)
    print(f"\n✓ Processed {len(df_processed)} addresses")
    print(f"✓ Saved to: SOURCE_ADDRS_PROCESSED.xlsx")

    # Show summary statistics
    info_count = df_processed['ADDITION_ADDR_INFO'].notna().sum()
    non_empty_info = (df_processed['ADDITION_ADDR_INFO'] != '').sum()
    print(f"\n Summary:")
    print(f"  - Total addresses: {len(df_processed)}")
    print(f"  - Addresses with additional info extracted: {non_empty_info}")
    print(f"  - Percentage: {non_empty_info/len(df_processed)*100:.1f}%")

except FileNotFoundError as e:
    print(f"Error: Could not find input file. Please ensure SOURCE_ADDRS.xlsx or SOURCE_ADDRS.csv exists.")
    print(f"Details: {e}")
except Exception as e:
    print(f"Error processing file: {e}")
    import traceback
    traceback.print_exc()
