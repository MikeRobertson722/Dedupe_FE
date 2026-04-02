import pandas as pd
import re

def extract_non_address_info(address):
    """
    Extract non-address information from addresses that have 2+ spaces separating
    non-address info from the actual address. Handles multiple layers of non-address info.

    Returns: (cleaned_address, additional_info)
    """
    if pd.isna(address) or not address or str(address).strip() == '':
        return address, ""

    address = str(address).strip()
    extracted_parts = []
    remaining = address

    # Keep extracting layers separated by 2+ spaces
    max_iterations = 5  # Prevent infinite loops
    for _ in range(max_iterations):
        # Pattern: Look for 2+ consecutive spaces
        multi_space_match = re.search(r'(.+?)\s{2,}(.+)', remaining)

        if not multi_space_match:
            break

        potential_info = multi_space_match.group(1).strip()
        potential_remainder = multi_space_match.group(2).strip()

        # Check if the second part looks like an address
        address_indicators = [
            r'^\d+\s',  # Starts with number and space (street address)
            r'^PO\s+BOX',  # PO BOX
            r'^P\s*O\s+BOX',  # P O BOX
            r'^P\.O\.\s*BOX',  # P.O. BOX
            r'^ROUTE\s+\d+',  # Route addresses
            r'^\d+[A-Z]?\s+[NSEW]',  # Address starting with number + direction
        ]

        is_address = any(re.match(pattern, potential_remainder, re.IGNORECASE)
                        for pattern in address_indicators)

        # Check if the first part contains known non-address patterns
        non_address_patterns = [
            r'\bFBO\b',
            r'\bC/O\b',
            r'\bDBA\b',
            r'\bATTN\b',
            r'\bAGENT\b',
            r'\bTRUSTEE\b',
            r'\bTTEE\b',
            r'\bMANAGER\b',
            r'\bDEPT\b',
            r'\bDEPARTMENT\b',
            r'^%',
        ]

        has_non_address_pattern = any(re.search(pattern, potential_info, re.IGNORECASE)
                                      for pattern in non_address_patterns)

        # If we found a clear separation, extract this layer
        if is_address or has_non_address_pattern:
            extracted_parts.append(potential_info)
            remaining = potential_remainder

            # If we hit an actual address, stop processing
            if is_address:
                break
        else:
            # No clear pattern, stop processing
            break

    # Return results
    if extracted_parts:
        # Join multiple extracted parts with " | " separator
        additional_info = " | ".join(extracted_parts)
        return remaining, additional_info

    # No separation found - return original address with no additional info
    return address, ""


def process_address_file(input_file, output_file):
    """
    Process the address file and separate non-address info.
    """
    # Read the CSV file
    df = pd.read_csv(input_file, encoding='utf-8-sig')

    print(f"Processing {len(df)} addresses...")
    print(f"Columns in file: {list(df.columns)}")

    # Process each address
    results = []
    for idx, row in df.iterrows():
        source_address = row['SOURCE_ADDRESS']
        cleaned_address, additional_info = extract_non_address_info(source_address)
        results.append({
            'SOURCE_ADDRESS': cleaned_address,
            'ADDITION_ADDR_INFO': additional_info
        })

    # Create new dataframe with results
    result_df = pd.DataFrame(results)

    # Save to Excel
    result_df.to_excel(output_file, index=False, engine='openpyxl')

    # Generate summary statistics
    addresses_with_info = result_df[result_df['ADDITION_ADDR_INFO'] != ''].shape[0]
    total_addresses = len(result_df)

    print(f"\n{'='*70}")
    print(f"PROCESSING SUMMARY")
    print(f"{'='*70}")
    print(f"Total addresses processed: {total_addresses}")
    print(f"Addresses with extracted info: {addresses_with_info}")
    print(f"Addresses without extra info: {total_addresses - addresses_with_info}")
    print(f"Percentage with extracted info: {(addresses_with_info/total_addresses)*100:.1f}%")

    # Show examples
    print(f"\n{'='*70}")
    print(f"EXAMPLES OF EXTRACTED INFORMATION")
    print(f"{'='*70}")

    examples_df = result_df[result_df['ADDITION_ADDR_INFO'] != '']

    for idx, row in examples_df.iterrows():
        print(f"\nOriginal: {row['ADDITION_ADDR_INFO']}  {row['SOURCE_ADDRESS']}")
        print(f"  -> Additional Info: '{row['ADDITION_ADDR_INFO']}'")
        print(f"  -> Cleaned Address: '{row['SOURCE_ADDRESS']}'")

    print(f"\n{'='*70}")
    print(f"Output saved to: {output_file}")
    print(f"{'='*70}")

    return result_df


if __name__ == "__main__":
    input_file = r"c:\ClaudeMain\BA_Review_App\SOURCE_ADDRS.csv"
    output_file = r"c:\ClaudeMain\BA_Review_App\SOURCE_ADDRS_CLEANED.xlsx"

    result_df = process_address_file(input_file, output_file)
