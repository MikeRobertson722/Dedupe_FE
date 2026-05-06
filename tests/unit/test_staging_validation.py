"""Unit tests for the staging-table length-validation feature.

Exercises the pure-logic helpers in data_loader.py and the SQL constructed by
stage_approved_records / get_staging_overflows. All Snowflake interaction is
mocked — no network, no credentials needed.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def _reset_staging_lengths_cache():
    """Module-level _STAGING_LENGTHS_CACHE persists across tests in the same
    process. Reset it before/after each test so each one starts clean."""
    import data_loader
    data_loader._STAGING_LENGTHS_CACHE = None
    yield
    data_loader._STAGING_LENGTHS_CACHE = None


# ---------------------------------------------------------------------------
# _build_column_specs — shape & invariants
# ---------------------------------------------------------------------------

def test_build_column_specs_returns_list_of_tuples():
    from data_loader import _build_column_specs
    specs = _build_column_specs()
    assert isinstance(specs, list)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in specs)
    assert all(isinstance(col, str) and isinstance(expr, str) for col, expr in specs)


def test_build_column_specs_includes_required_columns():
    """Every column the user-facing feature depends on must be mapped."""
    from data_loader import _build_column_specs
    specs = dict(_build_column_specs())
    required = {
        'ADDRADDRESS', 'ADDRCITY', 'ADDRCONTACT', 'ADDRSTATE', 'ADDRZIPCODE',
        'SSN', 'SSN_2', 'LEGACY_ID', 'ECODE', 'ADDRSEQ', 'ADDRSEQ_SOURCE',
    }
    missing = required - set(specs)
    assert not missing, f"column_specs missing required columns: {missing}"


def test_ssn_2_uses_regexp_replace_digits_only():
    """SSN_2 must strip non-alphanumerics — the staging length applies to the
    cleaned value, not the raw SSN."""
    from data_loader import _build_column_specs
    specs = dict(_build_column_specs())
    assert 'REGEXP_REPLACE' in specs['SSN_2']
    assert "[^A-Za-z0-9]" in specs['SSN_2']


def test_ecode_is_conditional_on_how_to_process():
    """ECODE only receives DEC_HDRCODE for two specific HOW_TO_PROCESS values;
    otherwise NULL. The conditional must survive into the INSERT SELECT."""
    from data_loader import _build_column_specs
    specs = dict(_build_column_specs())
    expr = specs['ECODE']
    assert 'CASE WHEN HOW_TO_PROCESS' in expr
    assert "'Merge BA and address'" in expr
    assert "'Add address to existing BA'" in expr
    assert 'DEC_HDRCODE' in expr


# ---------------------------------------------------------------------------
# _expand_with_auto_mirror — pure logic, no DB
# ---------------------------------------------------------------------------

def test_expand_no_mirror_when_no_underscore_two_columns():
    from data_loader import _expand_with_auto_mirror
    specs = [('ADDRADDRESS', 'expr_a'), ('ADDRCITY', 'expr_c')]
    expanded, mirrored = _expand_with_auto_mirror(specs, all_staging_cols=set())
    assert expanded == specs
    assert mirrored == []


def test_expand_mirrors_existing_underscore_two_sibling():
    """If <BASE>_2 exists in staging and isn't already in column_specs, it
    must be mirrored with the same SELECT expression."""
    from data_loader import _expand_with_auto_mirror
    specs = [('ADDRADDRESS', 'expr_a'), ('ADDRCITY', 'expr_c')]
    expanded, mirrored = _expand_with_auto_mirror(
        specs, all_staging_cols={'ADDRADDRESS', 'ADDRADDRESS_2', 'ADDRCITY'}
    )
    assert ('ADDRADDRESS', 'expr_a') in expanded
    assert ('ADDRADDRESS_2', 'expr_a') in expanded
    assert ('ADDRCITY_2', 'expr_c') not in expanded
    assert mirrored == ['ADDRADDRESS_2']


def test_expand_does_not_remirror_explicit_underscore_two():
    """SSN and SSN_2 are BOTH in column_specs (each with its own expression).
    The auto-mirror must skip SSN_2 because it's already explicit — otherwise
    we'd insert SSN's raw value into SSN_2 and clobber the digits-only
    transform."""
    from data_loader import _expand_with_auto_mirror
    specs = [('SSN', 'raw_expr'), ('SSN_2', 'digits_only_expr')]
    expanded, mirrored = _expand_with_auto_mirror(
        specs, all_staging_cols={'SSN', 'SSN_2'}
    )
    # Each column appears exactly once with its own expression.
    assert expanded == specs
    assert mirrored == []


def test_expand_preserves_order_with_sibling_immediately_after_base():
    from data_loader import _expand_with_auto_mirror
    specs = [('A', 'ea'), ('B', 'eb'), ('C', 'ec')]
    expanded, mirrored = _expand_with_auto_mirror(
        specs, all_staging_cols={'A', 'A_2', 'B', 'B_2', 'C'}
    )
    cols_in_order = [c for c, _ in expanded]
    assert cols_in_order == ['A', 'A_2', 'B', 'B_2', 'C']
    assert mirrored == ['A_2', 'B_2']


# ---------------------------------------------------------------------------
# SOURCE_TO_STAGING_FIELDS — UI contract
# ---------------------------------------------------------------------------

def test_source_to_staging_fields_includes_only_editable_columns():
    """Per user decision: only editable grid columns get the cell highlight.
    Read-only overflow surfaces in the validation modal — not via cellClassRules."""
    from data_loader import SOURCE_TO_STAGING_FIELDS
    expected_editable = {
        'source_name', 'source_address_recomend',
        'source_city', 'source_state', 'source_zip',
    }
    assert set(SOURCE_TO_STAGING_FIELDS.keys()) == expected_editable


def test_source_to_staging_fields_does_not_include_readonly():
    from data_loader import SOURCE_TO_STAGING_FIELDS
    # If any of these ever appear, the "read-only stays in modal only" promise
    # in the user-facing decision was broken.
    forbidden = {'source_id', 'source_ssn', 'dec_hdrcode',
                 'dec_addrsubcode', 'source_addrseq'}
    assert not (forbidden & set(SOURCE_TO_STAGING_FIELDS.keys()))


def test_source_to_staging_fields_targets_match_column_specs():
    """Every staging column that SOURCE_TO_STAGING_FIELDS points at must
    actually appear in _build_column_specs — otherwise the limits map would
    refer to a column the INSERT never writes to."""
    from data_loader import SOURCE_TO_STAGING_FIELDS, _build_column_specs
    spec_cols = {col for col, _ in _build_column_specs()}
    for src, targets in SOURCE_TO_STAGING_FIELDS.items():
        for t in targets:
            assert t in spec_cols, f"{src} -> {t} not in _build_column_specs"


# ---------------------------------------------------------------------------
# get_staging_column_lengths — INFORMATION_SCHEMA query + caching
# ---------------------------------------------------------------------------

def _mk_lengths_cursor(rows):
    """Cursor that returns the given (col_name, length) tuples on fetchall."""
    cur = MagicMock()
    cur.fetchall.return_value = rows
    return cur


def test_get_staging_column_lengths_returns_dict_uppercased():
    from data_loader import get_staging_column_lengths
    cur = _mk_lengths_cursor([
        ('ADDRCONTACT', 35),
        ('ADDRADDRESS', 80),
        ('addrcity', 40),  # exercise the upper() normalization
    ])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_staging_column_lengths({'table': 'IMPORT_MERGE_MATCHES'})
    assert result == {'ADDRCONTACT': 35, 'ADDRADDRESS': 80, 'ADDRCITY': 40}


def test_get_staging_column_lengths_drops_null_lengths():
    """Boolean / numeric columns return CHARACTER_MAXIMUM_LENGTH = NULL.
    They must not appear in the result (they have no string limit)."""
    from data_loader import get_staging_column_lengths
    cur = _mk_lengths_cursor([
        ('ADDRCONTACT', 35),
        ('JIBOWNER', None),  # boolean — no length
    ])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_staging_column_lengths({})
    assert 'JIBOWNER' not in result
    assert result == {'ADDRCONTACT': 35}


def test_get_staging_column_lengths_queries_information_schema():
    """Sanity check: we hit INFORMATION_SCHEMA on MA_STAGING.STG_BA_MASTER —
    not the wrong schema, not DESCRIBE TABLE."""
    from data_loader import get_staging_column_lengths
    cur = _mk_lengths_cursor([('ADDRCONTACT', 35)])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        get_staging_column_lengths({})
    sql = cur.execute.call_args[0][0]
    assert 'INFORMATION_SCHEMA.COLUMNS' in sql
    assert "TABLE_SCHEMA = 'MA_STAGING'" in sql
    assert "TABLE_NAME = 'STG_BA_MASTER'" in sql
    # Filtered to string types — we don't want booleans/numerics polluting
    # the result.
    assert 'DATA_TYPE' in sql


def test_get_staging_column_lengths_is_cached():
    """Process-local cache: the second call must NOT re-query Snowflake."""
    from data_loader import get_staging_column_lengths
    cur = _mk_lengths_cursor([('ADDRCONTACT', 35)])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        first = get_staging_column_lengths({})
        second = get_staging_column_lengths({})
    assert first == second
    assert cur.execute.call_count == 1


# ---------------------------------------------------------------------------
# get_source_field_limits — auto-mirror minimum
# ---------------------------------------------------------------------------

def test_get_source_field_limits_returns_simple_max():
    from data_loader import get_source_field_limits
    fake_lengths = {
        'ADDRCONTACT': 35, 'ADDRADDRESS': 80,
        'ADDRCITY': 40, 'ADDRSTATE': 2, 'ADDRZIPCODE': 10,
    }
    with patch('data_loader.get_staging_column_lengths', return_value=fake_lengths):
        result = get_source_field_limits({})
    assert result['source_name']['max'] == 35
    assert result['source_name']['staging_columns'] == ['ADDRCONTACT']
    assert result['source_address_recomend']['max'] == 80
    assert result['source_state']['max'] == 2
    assert result['source_zip']['max'] == 10


def test_get_source_field_limits_picks_min_when_underscore_two_is_stricter():
    """If ADDRADDRESS_2 (auto-mirrored) is shorter than ADDRADDRESS, the
    effective max is the stricter one — same value goes to both columns,
    must fit in both."""
    from data_loader import get_source_field_limits
    fake_lengths = {
        'ADDRCONTACT': 35,
        'ADDRADDRESS': 80, 'ADDRADDRESS_2': 60,  # _2 sibling is stricter
        'ADDRCITY': 40, 'ADDRSTATE': 2, 'ADDRZIPCODE': 10,
    }
    with patch('data_loader.get_staging_column_lengths', return_value=fake_lengths):
        result = get_source_field_limits({})
    assert result['source_address_recomend']['max'] == 60
    assert 'ADDRADDRESS' in result['source_address_recomend']['staging_columns']
    assert 'ADDRADDRESS_2' in result['source_address_recomend']['staging_columns']


def test_get_source_field_limits_skips_field_with_no_known_length():
    """If the staging column genuinely has no entry (e.g. table doesn't have
    that column at all), the source field is dropped from the limits map."""
    from data_loader import get_source_field_limits
    # Only ADDRCONTACT is known — every other source field must be skipped.
    with patch('data_loader.get_staging_column_lengths',
               return_value={'ADDRCONTACT': 35}):
        result = get_source_field_limits({})
    assert set(result.keys()) == {'source_name'}


# ---------------------------------------------------------------------------
# get_staging_overflows — SQL build + result parsing
# ---------------------------------------------------------------------------

def _make_overflow_cursor(rows, alias_columns):
    """Build a mock cursor whose description matches the SELECT we expect.
    `alias_columns` is the ordered list of non-pk SELECT aliases (e.g.
    ['L_ADDRCONTACT', 'L_ADDRADDRESS', ...]). Returns the cursor and
    a callable that records the executed SQL for later inspection."""
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.description = (
        [('SOURCE_ID',), ('SOURCE_SSN',)] +
        [(a,) for a in alias_columns]
    )
    return cur


def test_get_staging_overflows_builds_select_with_length_per_mapped_col():
    """SELECT must include LENGTH(<expr>) for every mapped string column,
    and the WHERE must contain the eligibility predicate plus the
    OR-of-overflows expression."""
    from data_loader import get_staging_overflows
    fake_lengths = {
        'ADDRCONTACT': 35, 'ADDRADDRESS': 80, 'ADDRCITY': 40,
        'ADDRSTATE': 2, 'ADDRZIPCODE': 10, 'SSN': 11, 'SSN_2': 9,
        'LEGACY_ID': 30, 'ECODE': 4, 'ADDRSEQ': 5, 'ADDRSEQ_SOURCE': 5,
    }
    cur = _make_overflow_cursor(rows=[], alias_columns=[])  # no overflows
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths):
        result = get_staging_overflows({'table': 'IMPORT_MERGE_MATCHES'})

    assert result == []
    sql = cur.execute.call_args[0][0]
    # Critical eligibility filters
    assert "UPPER(RECOMMENDATION) = 'APPROVED'" in sql
    assert "HOW_TO_PROCESS IS NOT NULL" in sql
    assert "HOW_TO_PROCESS <> 'Manual Review - DNP'" in sql
    # Per-mapped-column LENGTH expressions
    assert 'LENGTH(NULLIF(SOURCE_NAME' in sql            # ADDRCONTACT
    assert 'LENGTH(NULLIF(SOURCE_ADDRESS_RECOMEND' in sql  # ADDRADDRESS
    assert 'LENGTH(NULLIF(SOURCE_CITY' in sql            # ADDRCITY
    assert 'LENGTH(NULLIF(SOURCE_STATE' in sql           # ADDRSTATE
    assert 'LENGTH(NULLIF(SOURCE_ZIP' in sql             # ADDRZIPCODE
    assert 'LENGTH(NULLIF(SOURCE_SSN' in sql             # SSN
    assert 'REGEXP_REPLACE' in sql                       # SSN_2 honors the digits-only transform
    assert 'LENGTH(NULLIF(SOURCE_ID' in sql              # LEGACY_ID
    # OR-of-overflows
    assert ' > 35' in sql or '> 35' in sql
    assert ' > 80' in sql or '> 80' in sql


def test_get_staging_overflows_omits_dnp_rows_via_where_clause():
    """The /api/staging_validate must NEVER return Manual Review - DNP rows,
    even if they overflow — they aren't eligible for staging in the first place."""
    from data_loader import get_staging_overflows
    cur = _make_overflow_cursor(rows=[], alias_columns=[])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths',
               return_value={'ADDRCONTACT': 35}):
        get_staging_overflows({'table': 'IMPORT_MERGE_MATCHES'})
    sql = cur.execute.call_args[0][0]
    assert "Manual Review - DNP" in sql
    assert "<> 'Manual Review - DNP'" in sql


def test_get_staging_overflows_returns_empty_when_no_string_cols_known():
    """If get_staging_column_lengths returns nothing for any mapped column,
    there's no overflow possible — short-circuit to empty list, don't run SQL."""
    from data_loader import get_staging_overflows
    cur = _make_overflow_cursor(rows=[], alias_columns=[])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value={}):
        result = get_staging_overflows({})
    assert result == []
    assert cur.execute.call_count == 0  # never queried


def test_get_staging_overflows_parses_violations_correctly():
    """Given a row from Snowflake with LENGTH columns showing overflow on
    ADDRCONTACT (47 vs 35) and SSN (12 vs 11), the function must produce
    one entry with two violations marked correctly editable/read-only."""
    from data_loader import get_staging_overflows
    fake_lengths = {'ADDRCONTACT': 35, 'SSN': 11}
    aliases = ['L_ADDRCONTACT', 'L_SSN']
    # SOURCE_ID, SOURCE_SSN, L_ADDRCONTACT, L_SSN
    rows = [('SRC123', '111-22-3333', 47, 12)]
    cur = _make_overflow_cursor(rows=rows, alias_columns=aliases)
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths):
        result = get_staging_overflows({'table': 'IMPORT_MERGE_MATCHES'})

    assert len(result) == 1
    entry = result[0]
    assert entry['source_id'] == 'SRC123'
    assert entry['source_ssn'] == '111-22-3333'
    by_col = {v['column']: v for v in entry['violations']}
    assert by_col['source_name']['max'] == 35
    assert by_col['source_name']['actual'] == 47
    assert by_col['source_name']['editable'] is True   # source_name IS editable
    assert by_col['source_name']['staging'] == 'ADDRCONTACT'
    assert by_col['source_ssn']['editable'] is False    # SSN is read-only on the grid


def test_get_staging_overflows_skips_rows_within_limit():
    """A row whose lengths are all <= max but happened to be returned (e.g.
    the WHERE rounded a comparison) must NOT produce a violations entry."""
    from data_loader import get_staging_overflows
    fake_lengths = {'ADDRCONTACT': 35}
    rows = [
        ('SRC_OVER',  '111', 50),  # over
        ('SRC_OK',    '222', 30),  # under — should be filtered out
        ('SRC_EQUAL', '333', 35),  # at limit — equal is fine
    ]
    cur = _make_overflow_cursor(rows=rows, alias_columns=['L_ADDRCONTACT'])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths):
        result = get_staging_overflows({'table': 'IMPORT_MERGE_MATCHES'})
    assert len(result) == 1
    assert result[0]['source_id'] == 'SRC_OVER'


# ---------------------------------------------------------------------------
# stage_approved_records — defense-in-depth WHERE & return shape
# ---------------------------------------------------------------------------

class _StageCursor:
    """Stateful cursor that records every SQL execute call. The fetchone /
    fetchall responses are queued in the order stage_approved_records
    actually runs them."""
    def __init__(self, eligible_pairs, staging_cols, rejected_pairs=()):
        self._eligible = eligible_pairs
        self._staging_cols = staging_cols
        self._rejected = rejected_pairs
        self.executed = []  # (sql, params)
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        s = sql.strip().upper()
        if s.startswith('SELECT SOURCE_ID, SOURCE_SSN FROM') and 'NOT (' not in sql:
            # initial eligibility scan
            self._next_fetchall = self._eligible
        elif s.startswith('DESCRIBE TABLE'):
            self._next_fetchall = [(c,) for c in self._staging_cols]
        elif s.startswith('SELECT SOURCE_ID, SOURCE_SSN FROM') and 'NOT (' in sql:
            # rejected-rows capture
            self._next_fetchall = self._rejected
        elif s.startswith('INSERT'):
            self.rowcount = max(0, len(self._eligible) - len(self._rejected))
        elif s.startswith('UPDATE'):
            pass

    def fetchall(self):
        return getattr(self, '_next_fetchall', [])

    def fetchone(self):
        rows = getattr(self, '_next_fetchall', [])
        return rows[0] if rows else None

    def close(self):
        pass


def test_stage_approved_records_returns_dict_shape_when_no_eligible():
    """No eligible rows → must return the empty dict shape — never the
    bare integer that the old API used."""
    from data_loader import stage_approved_records
    cur = MagicMock()
    cur.fetchall.return_value = []   # initial eligibility scan returns nothing
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = stage_approved_records({'table': 'IMPORT_MERGE_MATCHES'}, df=None)
    assert result == {'staged': 0, 'rejected': 0, 'rejected_rows': []}


def test_stage_approved_records_insert_where_includes_length_predicates():
    """Defense in depth: the INSERT WHERE clause must AND a
    `(<expr> IS NULL OR LENGTH(<expr>) <= <max>)` term for every mapped
    string column. Even if the frontend is bypassed, an oversize value
    cannot land in STG_BA_MASTER."""
    from data_loader import stage_approved_records
    fake_lengths = {
        'ADDRCONTACT': 35, 'ADDRADDRESS': 80, 'ADDRCITY': 40,
        'ADDRSTATE': 2, 'ADDRZIPCODE': 10, 'SSN': 11, 'SSN_2': 9,
        'LEGACY_ID': 30, 'ECODE': 4, 'ADDRSEQ': 5, 'ADDRSEQ_SOURCE': 5,
    }
    eligible = [('SRC1', '111'), ('SRC2', '222')]
    staging_cols = list(fake_lengths.keys()) + [
        'ADDRCOUNTRY', 'JIBOWNER', 'LANDOWNER', 'REVOWNER',
        'LOAD_ME', 'MATCH_BY_ADDRESS', 'MATCH_BY_ENERTIA',
        'SOURCESYSTEM', 'SOURCETABLE', 'VALIDATION', 'ID', 'ADDRUNKNOWN',
    ]
    cur = _StageCursor(eligible, staging_cols, rejected_pairs=[])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths), \
         patch('data_loader.get_staging_overflows', return_value=[]):
        result = stage_approved_records({'table': 'IMPORT_MERGE_MATCHES'}, df=None)

    insert_sql = next(sql for sql, _ in cur.executed if sql.strip().upper().startswith('INSERT'))
    # Every mapped column's length predicate must be present
    assert 'LENGTH(NULLIF(SOURCE_NAME' in insert_sql
    assert '<= 35' in insert_sql                               # ADDRCONTACT
    assert '<= 80' in insert_sql                               # ADDRADDRESS
    assert '<= 9' in insert_sql                                # SSN_2 (digits-only)
    assert 'REGEXP_REPLACE(SOURCE_SSN' in insert_sql           # SSN_2 transform survives
    # NULL-tolerant predicate (so NULL/empty values still pass)
    assert 'IS NULL OR LENGTH' in insert_sql
    # Eligibility filter still in place
    assert "UPPER(RECOMMENDATION) = 'APPROVED'" in insert_sql
    assert "HOW_TO_PROCESS <> 'Manual Review - DNP'" in insert_sql
    # Return shape
    assert set(result.keys()) == {'staged', 'rejected', 'rejected_rows'}


def test_stage_approved_records_update_where_also_blocks_oversize():
    """The UPDATE-to-STAGED must use the SAME hard-block predicates as the
    INSERT — otherwise a rejected row would be flipped to STAGED in the
    source table without ever reaching staging, silently disappearing."""
    from data_loader import stage_approved_records
    fake_lengths = {'ADDRCONTACT': 35}
    eligible = [('SRC1', '111')]
    cur = _StageCursor(eligible, ['ADDRCONTACT'], rejected_pairs=[])
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths), \
         patch('data_loader.get_staging_overflows', return_value=[]):
        stage_approved_records({'table': 'IMPORT_MERGE_MATCHES'}, df=None)

    update_sql = next(sql for sql, _ in cur.executed if sql.strip().upper().startswith('UPDATE'))
    assert "RECOMMENDATION = 'STAGED'" in update_sql
    assert 'LENGTH(NULLIF(SOURCE_NAME' in update_sql  # same hard-block
    assert '<= 35' in update_sql


def test_stage_approved_records_captures_rejected_rows():
    """When some eligible rows overflow, the function must:
       a) capture them via the NOT(<length_where>) SELECT,
       b) return them in rejected_rows with full violation detail,
       c) report rejected count > 0."""
    from data_loader import stage_approved_records
    fake_lengths = {'ADDRCONTACT': 35}
    eligible = [('SRC_OVER', '111'), ('SRC_OK', '222')]
    rejected_pairs = [('SRC_OVER', '111')]
    fake_overflow_entry = {
        'source_id': 'SRC_OVER', 'source_ssn': '111',
        'violations': [{'column': 'source_name', 'staging': 'ADDRCONTACT',
                        'max': 35, 'actual': 50, 'editable': True}],
    }
    cur = _StageCursor(eligible, ['ADDRCONTACT'], rejected_pairs=rejected_pairs)
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths), \
         patch('data_loader.get_staging_overflows',
               return_value=[fake_overflow_entry]):
        result = stage_approved_records({'table': 'IMPORT_MERGE_MATCHES'}, df=None)

    assert result['rejected'] == 1
    assert result['rejected_rows'] == [fake_overflow_entry]


def test_stage_approved_records_filters_get_staging_overflows_to_this_batch():
    """get_staging_overflows enumerates the WHOLE table; stage_approved_records
    must only include entries whose (source_id, source_ssn) appear in this
    batch's pair list — otherwise unrelated DB-level offenders leak into the
    response of a small approval batch."""
    from data_loader import stage_approved_records
    fake_lengths = {'ADDRCONTACT': 35}
    eligible = [('SRC_BATCH', '111')]
    rejected_pairs = [('SRC_BATCH', '111')]
    # get_staging_overflows returns TWO entries — but only one is in the batch.
    other_offender = {
        'source_id': 'SRC_OTHER_BATCH', 'source_ssn': '999',
        'violations': [{'column': 'source_name', 'staging': 'ADDRCONTACT',
                        'max': 35, 'actual': 99, 'editable': True}],
    }
    in_batch = {
        'source_id': 'SRC_BATCH', 'source_ssn': '111',
        'violations': [{'column': 'source_name', 'staging': 'ADDRCONTACT',
                        'max': 35, 'actual': 50, 'editable': True}],
    }
    cur = _StageCursor(eligible, ['ADDRCONTACT'], rejected_pairs=rejected_pairs)
    conn = MagicMock(); conn.cursor.return_value = cur
    with patch('data_loader.get_snowflake_connection', return_value=conn), \
         patch('data_loader.get_staging_column_lengths', return_value=fake_lengths), \
         patch('data_loader.get_staging_overflows',
               return_value=[other_offender, in_batch]):
        result = stage_approved_records({'table': 'IMPORT_MERGE_MATCHES'}, df=None)

    # Only the in-batch offender survived the filter.
    assert len(result['rejected_rows']) == 1
    assert result['rejected_rows'][0]['source_id'] == 'SRC_BATCH'
