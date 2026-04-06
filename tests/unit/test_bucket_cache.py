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
