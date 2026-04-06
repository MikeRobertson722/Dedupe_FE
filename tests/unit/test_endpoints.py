"""Unit tests for Task 9 API endpoints."""
import json
import unittest
from unittest.mock import patch

# Set the environment so app can be imported without a real Snowflake connection
import os
os.environ.setdefault('SNOWFLAKE_ACCOUNT', 'test')
os.environ.setdefault('SNOWFLAKE_USER', 'test')
os.environ.setdefault('SNOWFLAKE_PASSWORD', 'test')
os.environ.setdefault('SNOWFLAKE_DATABASE', 'test')
os.environ.setdefault('SNOWFLAKE_SCHEMA', 'test')
os.environ.setdefault('SNOWFLAKE_WAREHOUSE', 'test')

import app as _app


class TestBucketCountsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_returns_counts_dict(self):
        with patch('app.get_bucket_counts', return_value={'REVIEW': 10, 'APPROVED': 5}):
            resp = self.client.get('/api/bucket-counts')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['REVIEW'], 10)
        self.assertEqual(data['APPROVED'], 5)

    def test_returns_500_on_error(self):
        with patch('app.get_bucket_counts', side_effect=RuntimeError('DB down')):
            resp = self.client.get('/api/bucket-counts')
        self.assertEqual(resp.status_code, 500)


class TestCacheStatusEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_no_cache_returns_sql_mode(self):
        with patch.object(_app, '_bucket_cache', None):
            resp = self.client.get('/api/cache-status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['mode'], 'sql')
        self.assertIsNone(data['bucket'])
        self.assertEqual(data['row_count'], 0)

    def test_cached_mode_returns_bucket_info(self):
        import datetime
        import pandas as pd
        from data_loader import BucketCache
        df = pd.DataFrame({'id': [1, 2, 3], 'recommendation': ['REVIEW'] * 3})
        cache = BucketCache('REVIEW', df)
        with patch.object(_app, '_bucket_cache', cache):
            resp = self.client.get('/api/cache-status')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['mode'], 'cached')
        self.assertEqual(data['bucket'], 'REVIEW')
        self.assertEqual(data['row_count'], 3)
        self.assertIn('load_time', data)
        self.assertIn('fresh', data)


class TestUserInfoEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_no_cookie_sets_new_uuid(self):
        resp = self.client.get('/api/user-info')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['is_new'])
        self.assertIsNotNone(data['user_id'])
        # Cookie should be set
        self.assertIn('user_id', resp.headers.get('Set-Cookie', ''))

    def test_existing_cookie_returns_is_new_false(self):
        self.client.set_cookie('user_id', 'existing-uuid-123')
        resp = self.client.get('/api/user-info')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['is_new'])
        self.assertEqual(data['user_id'], 'existing-uuid-123')

    def test_user_name_cookie_returned(self):
        self.client.set_cookie('user_id', 'uid-123')
        self.client.set_cookie('user_name', 'Alice')
        resp = self.client.get('/api/user-info')
        data = json.loads(resp.data)
        self.assertEqual(data['user_name'], 'Alice')

    def test_no_user_name_returns_empty_string(self):
        self.client.set_cookie('user_id', 'uid-456')
        resp = self.client.get('/api/user-info')
        data = json.loads(resp.data)
        self.assertEqual(data['user_name'], '')


class TestSetUsernameEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_valid_name_returns_success(self):
        resp = self.client.post(
            '/api/set-username',
            data=json.dumps({'user_name': 'Alice'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['user_name'], 'Alice')

    def test_empty_name_returns_400(self):
        resp = self.client.post(
            '/api/set-username',
            data=json.dumps({'user_name': ''}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_whitespace_only_name_returns_400(self):
        resp = self.client.post(
            '/api/set-username',
            data=json.dumps({'user_name': '   '}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_name_truncated_to_50_chars(self):
        long_name = 'A' * 60
        resp = self.client.post(
            '/api/set-username',
            data=json.dumps({'user_name': long_name}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(len(data['user_name']), 50)


if __name__ == '__main__':
    unittest.main()
