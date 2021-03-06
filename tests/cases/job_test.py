#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2015 Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import unittest
import mock
import httmock
import cumulus
import json
import re
import os
from cumulus.starcluster.tasks import job
from celery.app import task


class MockMaster:
    execute_stack = []
    def __init__(self):
        self.ssh = mock.MagicMock()

        self.ssh.execute.side_effect = MockMaster.execute_stack
        MockMaster.instance = self

class MockCluster:
    def __init__(self):
        self.master_node = MockMaster()
        self.cluster_user = 'bob'


class MockClusterManager:
    def __init__(self):
        self.cluster = MockCluster()
    def get_cluster(self, name):
        return self.cluster

class MockStarClusterConfig:
    def __init__(self, *args, **kw):
        self.cluster_manager = MockClusterManager()

    def load(self):
        pass

    def get_cluster_manager(self):
        return self.cluster_manager


class MockContext(task.Context):

    def __init__(self, *args, **kwargs):
        self.id = 'test_uuid'
        self.delivery_info = {'exchange': 'jobs'}

    def retry(self,args=None, kwargs=None, exc=None, throw=True, eta=None, countdown=None, max_retries=None, **options):
        pass

def capture_mock(func):
    pass

class JobTestCase(unittest.TestCase):

    def setUp(self):
        self._get_status_called  = False
        self._set_status_called  = False
        self._upload_job_output = cumulus.starcluster.tasks.job.upload_job_output.delay = mock.Mock()

    def normalize(self, data):
        str_data = json.dumps(data, default=str)
        str_data = re.sub(r'[\w]{64}', 'token', str_data)

        return json.loads(str_data)

    def assertCalls(self, actual, expected, msg=None):
        calls = []
        for (args, kwargs) in self.normalize(actual):
            calls.append((args, kwargs))

        self.assertListEqual(self.normalize(calls), expected, msg)

    @mock.patch('starcluster.config.StarClusterConfig', new=MockStarClusterConfig)
    @mock.patch('cumulus.starcluster.logging')
    def test_monitor_job_terminated(self, logging):

        job_id = 'dummy'
        cluster = {
            '_id': 'bob',
            'type': 'ec2',
            'name': 'dummy',
            'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_model = {
            '_id': job_id,
            'queueJobId': 'dummy',
            'name': 'dummy',
            'output': []
        }

        MockMaster.execute_stack = ['qstat output']

        def _get_status(url, request):
            content = {
                'status': 'terminating'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._get_status_called  = True
            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            expected = {u'status': u'terminated', u'timings': {}, u'output': []}

            self._set_status_called = json.loads(request.body) == expected

            return httmock.response(200, None, {}, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.monitor_job(cluster, job_model, **{'girder_token': 's', 'log_write_url': 1})

        self.assertTrue(self._get_status_called, 'Expect get status endpoint to be hit')
        self.assertTrue(self._set_status_called, 'Expect set status endpoint to be hit')

    @mock.patch('starcluster.config.StarClusterConfig')
    @mock.patch('starcluster.logger')
    @mock.patch('cumulus.starcluster.logging')
    def test_monitor_job_complete(self, logging,logger, StarClusterConfig):

        StarClusterConfig.return_value.get_cluster_manager.return_value \
            .get_cluster.return_value \
            .master_node.ssh.stat.return_value.st_size = 0

        job_id = 'dummy'
        cluster = {
            '_id': 'dummy',
            'type': 'ec2',
            'name': 'dummy',
             'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_model = {
            '_id': job_id,
            'queueJobId': 'dummy',
            'name': 'dummy',
            'output': [{
                'itemId': 'dummy'
            }]
        }

        MockMaster.execute_stack = ['qstat output']

        def _get_status(url, request):
            content = {
                'status': 'running'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._get_status_called  = True
            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            expected = {'status': 'uploading', 'timings': {}, 'output': [{'itemId': u'dummy'}]}
            self._set_status_called = json.loads(request.body) == expected

            return httmock.response(200, None, {}, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.monitor_job(cluster, job_model, **{'girder_token': 's', 'log_write_url': 1})

        self.assertTrue(self._get_status_called, 'Expect get status endpoint to be hit')
        self.assertTrue(self._set_status_called, 'Expect set status endpoint to be hit')
        expected_calls = [[[{u'config': {u'_id': u'dummy', u'scheduler': {u'type': u'sge'}}, u'name': u'dummy', u'type': u'ec2', u'_id': u'dummy'}, {u'status': u'uploading', u'output': [{u'itemId': u'dummy'}], u'_id': u'dummy', u'queueJobId': u'dummy', u'name': u'dummy'}], {u'girder_token': u's', u'log_write_url': 1, u'job_dir': u'./dummy'}]]
        self.assertCalls(self._upload_job_output.call_args_list, expected_calls)

    @mock.patch('starcluster.config.StarClusterConfig', new=MockStarClusterConfig)
    @mock.patch('starcluster.logger')
    @mock.patch('cumulus.starcluster.logging')
    @mock.patch('cumulus.celery.monitor.Task.retry')
    def test_monitor_job_running(self, retry, *args):
        job_id = 'dummy'
        cluster = {
            '_id': 'jill',
            'type': 'ec2',
            'name': 'dummy',
            'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'output': []
        }

        MockMaster.execute_stack = [[ 'job-ID  prior   name       user         state submit/start at     queue  slots ja-task-ID',
                             '-----------------------------------------------------------------------------------------',
                             '1 0.00000 hostname   sgeadmin     r     09/09/2009 14:58:14                1']]

        def _get_status(url, request):
            content = {
                'status': 'running'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._get_status_called  = True
            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            expected = {'status': 'running', 'timings': {}, 'output': []}
            self._set_status_called = json.loads(request.body) == expected

            if not self._set_status_called:
                print json.loads(request.body)

            return httmock.response(200, None, {}, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.monitor_job(cluster, job_model, **{'girder_token': 's', 'log_write_url': 1})

        self.assertTrue(self._get_status_called, 'Expect get status endpoint to be hit')
        self.assertTrue(self._set_status_called, 'Expect set status endpoint to be hit')

    @mock.patch('starcluster.config.StarClusterConfig', new=MockStarClusterConfig)
    @mock.patch('starcluster.logger')
    @mock.patch('cumulus.starcluster.logging')
    @mock.patch('cumulus.celery.monitor.Task.retry')
    def test_monitor_job_queued(self, *args):

        job_id = 'dummy'
        cluster = {
            '_id': 'lost',
            'type': 'ec2',
            'name': 'dummy',
            'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'output': []
        }

        MockMaster.execute_stack = [[ 'job-ID  prior   name       user         state submit/start at     queue  slots ja-task-ID',
                             '-----------------------------------------------------------------------------------------',
                             '1 0.00000 hostname   sgeadmin     q     09/09/2009 14:58:14                1']]

        def _get_status(url, request):
            content = {
                'status': 'queued'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._get_status_called  = True
            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            expected = {'status': 'queued', 'timings': {}, 'output': []}
            self._set_status_called = json.loads(request.body) == expected

            return httmock.response(200, None, {}, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.monitor_job(cluster, job_model, **{'girder_token': 's', 'log_write_url': 1})

        self.assertTrue(self._get_status_called, 'Expect get status endpoint to be hit')
        self.assertTrue(self._set_status_called, 'Expect set status endpoint to be hit')

    @mock.patch('starcluster.config.StarClusterConfig', new=MockStarClusterConfig)
    @mock.patch('starcluster.logger')
    @mock.patch('cumulus.starcluster.logging')
    @mock.patch('cumulus.celery.monitor.Task.retry')
    @mock.patch('cumulus.starcluster.tasks.job.get_connection', autospec=True)
    def test_monitor_job_tail_output(self, get_connection, retry, *args):

        job_id = 'dummy'
        cluster = {
            '_id': 'bill',
            'type': 'ec2',
            'name': 'dummy',
            'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'output': [{'tail': True,  'path': 'dummy/file/path'}]
        }

        conn = get_connection.return_value.__enter__.return_value
        conn.execute.side_effect = [[ 'job-ID  prior   name       user         state submit/start at     queue  slots ja-task-ID',
                             '-----------------------------------------------------------------------------------------',
                             '1 0.00000 hostname   sgeadmin     r     09/09/2009 14:58:14                1'], ['i have a tail', 'asdfas'] ]

        def _get_status(url, request):
            content = {
                'status': 'running'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._get_status_called  = True
            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            expected = {u'status': u'running', u'output': [{u'content': [u'i have a tail', u'asdfas'], u'path': u'dummy/file/path', u'tail': True}], u'timings': {}}
            self._set_status_called = json.loads(request.body) == expected

            if not self._set_status_called:
                print json.loads(request.body)

            return httmock.response(200, None, {}, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.monitor_job(cluster, job_model, **{'girder_token': 's', 'log_write_url': 1})

        self.assertTrue(self._get_status_called, 'Expect get status endpoint to be hit')
        self.assertTrue(self._set_status_called, 'Expect set status endpoint to be hit')

    @mock.patch('starcluster.config.StarClusterConfig', new=MockStarClusterConfig)
    @mock.patch('starcluster.logger')
    @mock.patch('cumulus.starcluster.logging')
    @mock.patch('cumulus.celery.monitor.Task.retry')
    @mock.patch('cumulus.starcluster.tasks.job.monitor_job')
    @mock.patch('cumulus.starcluster.tasks.job.get_connection', autospec=True)
    def test_submit_job(self, get_connection, *args):

        cluster = {
            '_id': 'bob',
            'type': 'ec2',
            'name': 'dummy',
            'config': {
                '_id': 'dummy',
                'scheduler': {
                    'type': 'sge'
                }
            },

        }
        job_id = 'dummy'
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'commands': ['ls'],
            'output': [{'tail': True,  'path': 'dummy/file/path'}]
        }

        qconf_output = ['pe_name            orte',
                        'slots              10\n',
                        'user_lists         NONE',
                        'xuser_lists        NONE',
                        'start_proc_args    /bin/true',
                        'stop_proc_args     /bin/true',
                        'allocation_rule    $pe_slots',
                        'control_slaves     FALSE',
                        'job_is_first_task  TRUE',
                        'urgency_slots      min',
                        'accounting_summary FALSE']

        qsub_output = ['Your job 74 ("test.sh") has been submitted']

        conn = get_connection.return_value.__enter__.return_value
        conn.execute.side_effect = [qconf_output, qsub_output]

        def _get_status(url, request):
            content = {
                'status': 'queued'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            return httmock.response(200, content, headers, request=request)

        def _set_status(url, request):
            content = {
                'status': 'queued'
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            return httmock.response(200, content, headers, request=request)

        status_url = '/api/v1/jobs/%s/status' % job_id
        get_status = httmock.urlmatch(
            path=r'^%s$' % status_url, method='GET')(_get_status)

        status_update_url = '/api/v1/jobs/%s' % job_id
        set_status = httmock.urlmatch(
            path=r'^%s$' % status_update_url, method='PATCH')(_set_status)

        with httmock.HTTMock(get_status, set_status):
            job.submit_job(cluster, job_model, log_write_url='log_write_url',
                           girder_token='girder_token')

        self.assertEqual(conn.execute.call_args_list[0],
                         mock.call('qconf -sp orte'), 'Unexpected qconf command: %s' %
                         str(MockMaster.instance.ssh.execute.call_args_list[0]))

        # Specifying and parallel environment
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'commands': ['ls'],
            'output': [{'tail': True,  'path': 'dummy/file/path'}],
            'params': {
                'parallelEnvironment': 'mype'
            }
        }

        qconf_output = ['pe_name            mype',
                        'slots              10\n',
                        'user_lists         NONE',
                        'xuser_lists        NONE',
                        'start_proc_args    /bin/true',
                        'stop_proc_args     /bin/true',
                        'allocation_rule    $pe_slots',
                        'control_slaves     FALSE',
                        'job_is_first_task  TRUE',
                        'urgency_slots      min',
                        'accounting_summary FALSE']

        conn.reset_mock()
        conn.execute.side_effect = [qconf_output, qsub_output]

        with httmock.HTTMock(get_status, set_status):
            job.submit_job(cluster, job_model, log_write_url='log_write_url',
                           girder_token='girder_token')
        self.assertEqual(conn.execute.call_args_list[0],
                         mock.call('qconf -sp mype'), 'Unexpected qconf command: %s' %
                         str(conn.execute.call_args_list[0]))

        # For traditional clusters we shouldn't try to extract slot from orte
        cluster = {
            '_id': 'dummy',
            'type': 'trad',
            'name': 'dummy',
            'config': {
                'host': 'dummy',
                'ssh': {
                    'user': 'dummy',
                    'passphrase': 'its a secret'
                },
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_id = 'dummy'
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'commands': ['ls'],
            'output': [{'tail': True,  'path': 'dummy/file/path'}]
        }

        conn.reset_mock()
        conn.execute.side_effect = [['Your job 74 ("test.sh") has been submitted']]

        with httmock.HTTMock(get_status, set_status):
            job.submit_job(cluster, job_model, log_write_url='log_write_url',
                           girder_token='girder_token')

        # Assert that we don't try and get the number of slots
        self.assertFalse('qconf' in str(conn.execute.call_args_list), 'qconf should not be called')

        # For traditional clusters define a parallel env
        cluster = {
            '_id': 'dummy',
            'type': 'trad',
            'name': 'dummy',
            'config': {
                'host': 'dummy',
                'ssh': {
                    'user': 'dummy',
                    'passphrase': 'its a secret'
                },
                'scheduler': {
                    'type': 'sge'
                }
            }
        }
        job_id = 'dummy'
        job_model = {
            '_id': job_id,
            'queueJobId': '1',
            'name': 'dummy',
            'commands': ['ls'],
            'output': [{'tail': True,  'path': 'dummy/file/path'}],
            'params': {
                'parallelEnvironment': 'mype'
            }
        }

        conn.reset_mock()
        conn.execute.side_effect = [qconf_output, ['Your job 74 ("test.sh") has been submitted']]

        with httmock.HTTMock(get_status, set_status):
            job.submit_job(cluster, job_model, log_write_url='log_write_url',
                           girder_token='girder_token')

        self.assertEqual(conn.execute.call_args_list[0], mock.call('qconf -sp mype'))
        self.assertEqual(job_model['params']['numberOfSlots'], 10)


