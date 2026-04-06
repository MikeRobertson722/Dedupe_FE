"""Unit tests for BucketCache and related data_loader functions."""
import threading
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Connection lock test
# ---------------------------------------------------------------------------

def test_connection_lock_is_threading_lock():
    """data_loader._conn_lock must be a threading.Lock instance."""
    import data_loader
    assert isinstance(data_loader._conn_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# BucketCache tests
# ---------------------------------------------------------------------------


def _make_df(n=10, bucket='REVIEW'):
    """Create a small test DataFrame mimicking import_merge_matches."""
    return pd.DataFrame({
        'id': range(n),
        'recommendation': [bucket] * n,
        'source_id': [f'SRC{i}' for i in range(n)],
        'source_ssn': [f'SSN{i}' for i in range(n)],
        'name_score': [80.0] * n,
        'address_score': [75.0] * n,
        'ssn_match': [100] * n,
    })


def test_bucket_cache_stores_bucket_and_df():
    from data_loader import BucketCache
    df = _make_df(5, 'REVIEW')
    cache = BucketCache('REVIEW', df)
    assert cache.bucket == 'REVIEW'
    assert len(cache.df) == 5


def test_bucket_cache_is_fresh_within_ttl():
    from data_loader import BucketCache
    cache = BucketCache('REVIEW', _make_df())
    assert cache.is_fresh(ttl_seconds=300) is True


def test_bucket_cache_is_stale_after_ttl():
    from data_loader import BucketCache
    import datetime
    cache = BucketCache('REVIEW', _make_df())
    # Backdate load_time by 6 minutes
    cache.load_time = cache.load_time - datetime.timedelta(seconds=361)
    assert cache.is_fresh(ttl_seconds=300) is False


def test_bucket_cache_update_row():
    from data_loader import BucketCache
    df = _make_df(5)
    cache = BucketCache('REVIEW', df)
    cache.update_row(row_id=2, field='recommendation', value='APPROVED')
    assert cache.df.loc[cache.df['id'] == 2, 'recommendation'].values[0] == 'APPROVED'


def test_bucket_cache_update_row_no_match_is_noop():
    from data_loader import BucketCache
    df = _make_df(5)
    cache = BucketCache('REVIEW', df)
    # id=999 doesn't exist — should not raise
    cache.update_row(row_id=999, field='recommendation', value='APPROVED')


def test_bucket_cache_rejects_oversized_df():
    from data_loader import BucketCache, BUCKET_CACHE_MAX_ROWS
    big_df = pd.DataFrame({'id': range(BUCKET_CACHE_MAX_ROWS + 1)})
    with pytest.raises(ValueError, match='exceeds'):
        BucketCache('REVIEW', big_df)
