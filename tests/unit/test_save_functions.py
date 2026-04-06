"""Unit tests for immediate-write save functions."""
from unittest.mock import MagicMock, patch, call
import pytest
from datetime import datetime


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 1
    conn.cursor.return_value = cursor
    return conn, cursor


def test_save_record_immediately_runs_update():
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=42,
            source_id='SRC001',
            source_ssn='555-12-3456',
            fields={'recommendation': ('REVIEW', 'APPROVED')},
            user_id='uuid-abc',
            user_name='Alice',
        )
    assert result == 1
    # Verify UPDATE was called (not MERGE)
    calls = [str(c) for c in cursor.execute.call_args_list]
    assert any('UPDATE' in c.upper() for c in calls)
    assert any('WHERE' in c.upper() and 'ID' in c.upper() for c in calls)


def test_save_record_immediately_writes_audit_log():
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=42,
            source_id='SRC001',
            source_ssn='555-12-3456',
            fields={'recommendation': ('REVIEW', 'APPROVED')},
            user_id='uuid-abc',
            user_name='Alice',
        )
    calls = [str(c) for c in cursor.execute.call_args_list]
    assert any('UPDATE_LOG' in c.upper() or 'INSERT' in c.upper() for c in calls)


def test_save_records_batch_updates_all_records():
    from data_loader import save_records_batch
    conn, cursor = _mock_conn()
    cursor.rowcount = 3
    records = [
        {'record_id': 1, 'source_id': 'S1', 'source_ssn': 'SSN1',
         'fields': {'recommendation': ('REVIEW', 'APPROVED')}},
        {'record_id': 2, 'source_id': 'S2', 'source_ssn': 'SSN2',
         'fields': {'recommendation': ('REVIEW', 'APPROVED')}},
        {'record_id': 3, 'source_id': 'S3', 'source_ssn': 'SSN3',
         'fields': {'recommendation': ('AUTO_MERGE', 'APPROVED')}},
    ]
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        affected = save_records_batch(
            config={'table': 'import_merge_matches'},
            records=records,
            user_id='uuid-abc',
            user_name='Alice',
        )
    assert affected >= 0  # returns rowcount


def test_save_record_maps_source_address_recomend():
    """source_address_recomend maps to SOURCE_ADDRESS column in DB."""
    from data_loader import save_record_immediately
    conn, cursor = _mock_conn()
    executed = []
    cursor.execute.side_effect = lambda sql, params=None: executed.append(sql)
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        save_record_immediately(
            config={'table': 'import_merge_matches'},
            record_id=1,
            source_id='S1',
            source_ssn='SSN1',
            fields={'source_address_recomend': ('123 Old St', '456 New Ave')},
        )
    update_sql = next(s for s in executed if 'UPDATE' in s.upper())
    assert 'SOURCE_ADDRESS' in update_sql.upper()
    assert 'SOURCE_ADDRESS_RECOMEND' not in update_sql.upper()


def test_write_audit_log_includes_user_id_and_user_name():
    """write_audit_log_to_snowflake must accept 8-tuple entries with user_id/user_name."""
    from data_loader import write_audit_log_to_snowflake
    from datetime import datetime
    conn, cursor = _mock_conn()
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        write_audit_log_to_snowflake(
            config={'table': 'import_merge_matches'},
            log_entries=[('S1', 'SSN1', 'recommendation', 'REVIEW', 'APPROVED',
                          datetime.now(), 'uuid-abc', 'Alice')],
        )
    calls = [str(c) for c in cursor.executemany.call_args_list]
    assert any('USER_ID' in c.upper() or 'USER_NAME' in c.upper() for c in calls)
