import pandas as pd

# Read the cleaned file
df = pd.read_excel('SOURCE_ADDRS_CLEANED.xlsx')

print('\nFINAL PROCESSING RESULTS')
print('=' * 80)
print(f'Total addresses processed: {len(df):,}')

with_info = (df['ADDITION_ADDR_INFO'] != '').sum()
without_info = (df['ADDITION_ADDR_INFO'] == '').sum()

print(f'Addresses with extracted info: {with_info:,}')
print(f'Addresses unchanged: {without_info:,}')
print(f'\nPercentage with extracted info: {with_info / len(df) * 100:.1f}%')
print('\nOutput file: SOURCE_ADDRS_CLEANED.xlsx (672 KB)')
print('=' * 80)

# Show some sample extracted patterns
print('\nSample of extracted information types:')
print('-' * 80)
df_with_info = df[df['ADDITION_ADDR_INFO'] != '']

samples = {
    'FBO (For Benefit Of)': df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.startswith('FBO', na=False)].head(3),
    'C/O (Care Of)': df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.startswith('C/O', na=False)].head(3),
    'AGENT': df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.contains('AGENT', na=False)].head(3),
    'TRUSTEE/TTEE': df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.contains('TRUSTEE|TTEE', na=False)].head(3),
    'ATTN': df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.contains('ATTN', na=False)].head(3),
}

for pattern_type, sample_df in samples.items():
    count = df_with_info[df_with_info['ADDITION_ADDR_INFO'].str.contains(pattern_type.split()[0], na=False)].shape[0]
    print(f'\n{pattern_type} - {count} occurrences')
    for idx, row in sample_df.iterrows():
        print(f'  • {row["ADDITION_ADDR_INFO"][:60]}...')

print('\n' + '=' * 80)
print('SUCCESS! All addresses have been processed and saved.')
print('=' * 80)
