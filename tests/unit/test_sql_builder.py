"""Unit tests for SQL query building in data_loader."""
from unittest.mock import MagicMock, patch, call
import pytest


def _make_cursor(rows=None, description=None, rowcount=1):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = (rows or [[None]])[0] if rows else None
    cursor.description = description or [('COUNT(*)',)]
    cursor.rowcount = rowcount
    return cursor


# ---------------------------------------------------------------------------
# get_bucket_counts
# ---------------------------------------------------------------------------

def test_get_bucket_counts_returns_dict():
    from data_loader import get_bucket_counts
    cursor = _make_cursor(rows=[('REVIEW', 1234), ('AUTO_MERGE', 5678), ('APPROVED', 90)])
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_bucket_counts({'table': 'import_merge_matches'})
    assert result == {'REVIEW': 1234, 'AUTO_MERGE': 5678, 'APPROVED': 90}


def test_get_bucket_counts_handles_empty():
    from data_loader import get_bucket_counts
    cursor = _make_cursor(rows=[])
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        result = get_bucket_counts({'table': 'import_merge_matches'})
    assert result == {}


# ---------------------------------------------------------------------------
# query_snowflake_page — SQL construction
# ---------------------------------------------------------------------------

def test_query_snowflake_page_single_bucket_filter():
    from data_loader import query_snowflake_page
    executed_sqls = []

    cursor = MagicMock()
    # First call = total count, second = filtered count, third = page data
    cursor.fetchone.side_effect = [(50000,), (50000,)]
    cursor.fetchall.return_value = []
    cursor.description = [('id',), ('recommendation',), ('source_id',)]

    def capture_execute(sql, params=None):
        executed_sqls.append((sql, params))

    cursor.execute.side_effect = capture_execute
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch('data_loader.get_snowflake_connection', return_value=conn):
        query_snowflake_page(
            config={'table': 'import_merge_matches'},
            filters={'recommendation': 'REVIEW'},
            sort_col='name_score',
            sort_dir='desc',
            start=0,
            length=25,
        )

    # At least one SQL call must contain WHERE ... RECOMMENDATION
    sql_bodies = [s for s, _ in executed_sqls]
    assert any('RECOMMENDATION' in s.upper() for s in sql_bodies)
    assert any('ORDER BY' in s.upper() for s in sql_bodies)
    assert any('LIMIT' in s.upper() for s in sql_bodies)


def test_query_snowflake_page_returns_tuple():
    from data_loader import query_snowflake_page
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1000,), (250,)]
    cursor.fetchall.return_value = [{'id': 1, 'recommendation': 'REVIEW'}]
    cursor.description = [('id',), ('recommendation',)]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    with patch('data_loader.get_snowflake_connection', return_value=conn):
        rows, total, filtered = query_snowflake_page(
            config={'table': 'import_merge_matches'},
            filters={},
            sort_col=None,
            sort_dir='asc',
            start=0,
            length=25,
        )
    assert isinstance(rows, list)
    assert isinstance(total, int)
    assert isinstance(filtered, int)
