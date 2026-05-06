"""HTTP-level tests for the new staging-validation endpoints.

Mocks the data_loader functions and exercises the Flask routes end-to-end
to catch shape mismatches between the data layer and the JSON contract.
"""
import json
import os
import unittest
from unittest.mock import patch

# Allow `import app` without a real Snowflake connection.
os.environ.setdefault('SNOWFLAKE_ACCOUNT', 'test')
os.environ.setdefault('SNOWFLAKE_USER', 'test')
os.environ.setdefault('SNOWFLAKE_PASSWORD', 'test')
os.environ.setdefault('SNOWFLAKE_DATABASE', 'test')
os.environ.setdefault('SNOWFLAKE_SCHEMA', 'test')
os.environ.setdefault('SNOWFLAKE_WAREHOUSE', 'test')

import app as _app


class TestStagingLimitsEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_returns_limits_in_expected_shape(self):
        fake_limits = {
            'source_name':      {'max': 35, 'staging_columns': ['ADDRCONTACT']},
            'source_address_recomend': {'max': 80,
                'staging_columns': ['ADDRADDRESS', 'ADDRADDRESS_2']},
            'source_city':      {'max': 40, 'staging_columns': ['ADDRCITY']},
        }
        with patch('app.get_source_field_limits', return_value=fake_limits):
            resp = self.client.get('/api/staging_limits')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        # Frontend reads data.limits.<field>.max — that path must exist
        self.assertIn('limits', data)
        self.assertEqual(data['limits']['source_name']['max'], 35)
        self.assertEqual(
            data['limits']['source_address_recomend']['staging_columns'],
            ['ADDRADDRESS', 'ADDRADDRESS_2'],
        )

    def test_returns_500_on_error(self):
        with patch('app.get_source_field_limits',
                   side_effect=RuntimeError('Snowflake unavailable')):
            resp = self.client.get('/api/staging_limits')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('error', json.loads(resp.data))


class TestStagingValidateEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_returns_overflows_in_expected_shape(self):
        fake_overflows = [
            {
                'source_id': 'SRC123', 'source_ssn': '111-22-3333',
                'violations': [
                    {'column': 'source_name', 'staging': 'ADDRCONTACT',
                     'max': 35, 'actual': 47, 'editable': True},
                    {'column': 'source_id', 'staging': 'LEGACY_ID',
                     'max': 30, 'actual': 35, 'editable': False},
                ],
            },
        ]
        with patch('app.get_staging_overflows', return_value=fake_overflows):
            resp = self.client.get('/api/staging_validate')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(len(data['overflows']), 1)
        # Frontend modal walks resp.overflows[*].violations[*]
        violations = data['overflows'][0]['violations']
        self.assertTrue(any(v['editable'] is True for v in violations))
        self.assertTrue(any(v['editable'] is False for v in violations))

    def test_returns_empty_overflows_when_all_fits(self):
        with patch('app.get_staging_overflows', return_value=[]):
            resp = self.client.get('/api/staging_validate')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['overflows'], [])


class TestStagingCountSubtractsOverflows(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_count_is_eligible_minus_overflows(self):
        """Badge count must be `eligible − overflows` so it tells the truth."""
        from unittest.mock import MagicMock
        cur = MagicMock()
        cur.fetchone.return_value = (50,)  # 50 eligible
        conn = MagicMock(); conn.cursor.return_value = cur

        # 7 overflow rows (don't care about details for the count)
        seven_overflows = [{'source_id': str(i), 'source_ssn': '',
                            'violations': []} for i in range(7)]
        with patch('app.get_snowflake_connection', return_value=conn), \
             patch('app.get_staging_overflows', return_value=seven_overflows):
            resp = self.client.get('/api/staging_count')

        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['count'], 43)        # 50 − 7
        self.assertEqual(data['eligible'], 50)
        self.assertEqual(data['overflow'], 7)

    def test_count_clamps_at_zero(self):
        """If somehow overflow > eligible (shouldn't happen but be safe),
        the badge must show 0, never negative."""
        from unittest.mock import MagicMock
        cur = MagicMock()
        cur.fetchone.return_value = (3,)
        conn = MagicMock(); conn.cursor.return_value = cur

        many_overflows = [{'source_id': str(i), 'source_ssn': '',
                           'violations': []} for i in range(10)]
        with patch('app.get_snowflake_connection', return_value=conn), \
             patch('app.get_staging_overflows', return_value=many_overflows):
            resp = self.client.get('/api/staging_count')
        self.assertEqual(json.loads(resp.data)['count'], 0)


class TestStageApprovedNewResponse(unittest.TestCase):
    def setUp(self):
        self.client = _app.app.test_client()

    def test_response_includes_rejected_fields(self):
        """The frontend expects {success, staged, rejected, rejected_rows,
        message}; the toast styling switches on `rejected`."""
        rejected_rows = [
            {'source_id': 'SRC1', 'source_ssn': '111',
             'violations': [{'column': 'source_name', 'staging': 'ADDRCONTACT',
                             'max': 35, 'actual': 50, 'editable': True}]}
        ]
        with patch('app.stage_approved_records', return_value={
            'staged': 12, 'rejected': 1, 'rejected_rows': rejected_rows,
        }), patch('app._invalidate_cache'):
            resp = self.client.post('/api/stage_approved',
                                    json={}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['staged'], 12)
        self.assertEqual(data['rejected'], 1)
        self.assertEqual(data['rejected_rows'], rejected_rows)
        # Message should mention both numbers when rejected > 0
        self.assertIn('12', data['message'])
        self.assertIn('1', data['message'])
        self.assertIn('rejected', data['message'].lower())

    def test_response_when_only_staged(self):
        """No rejections → standard success message, no 'rejected' wording."""
        with patch('app.stage_approved_records', return_value={
            'staged': 5, 'rejected': 0, 'rejected_rows': [],
        }), patch('app._invalidate_cache'):
            resp = self.client.post('/api/stage_approved',
                                    json={}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['rejected'], 0)
        self.assertNotIn('rejected', data['message'].lower())

    def test_response_when_nothing_eligible(self):
        """The 0-eligible early return must still match the new shape so the
        frontend doesn't crash trying to read data.rejected_rows."""
        with patch('app.stage_approved_records', return_value={
            'staged': 0, 'rejected': 0, 'rejected_rows': [],
        }):
            resp = self.client.post('/api/stage_approved',
                                    json={}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['staged'], 0)
        self.assertIn('rejected_rows', data)
        self.assertEqual(data['rejected_rows'], [])

    def test_returns_500_on_data_loader_exception(self):
        with patch('app.stage_approved_records',
                   side_effect=RuntimeError('Connection lost')):
            resp = self.client.post('/api/stage_approved',
                                    json={}, content_type='application/json')
        self.assertEqual(resp.status_code, 500)
        self.assertIn('error', json.loads(resp.data))


if __name__ == '__main__':
    unittest.main()
