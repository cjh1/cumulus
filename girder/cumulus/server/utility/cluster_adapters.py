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

import base64
from jsonpath_rw import parse

from girder.utility.model_importer import ModelImporter
from girder.models.model_base import ValidationException
from girder.api.rest import RestException, getApiUrl, getCurrentUser

from cumulus.constants import ClusterType
from cumulus.common.girder import get_task_token
import cumulus.starcluster.tasks.cluster


class AbstractClusterAdapter(ModelImporter):
    """
    This defines the interface to be used by all cluster adapters.
    """
    def __init__(self, cluster):
        self.cluster = cluster

    def validate(self):
        """
        Adapters may implement this if they need to perform any validation
        steps whenever the cluster info is saved to the database. It should
        return the document with any necessary alterations in the success case,
        or throw an exception if validation fails.
        """
        return self.cluster

    def start(self, request_body):
        """
        Adapters may implement this if they support a start operation.
        """
        raise ValidationException(
            'This cluster type does not support a start operation')

    def terminate(self):
        """
        Adapters may implement this if they support a terminate operation.
        """
        raise ValidationException(
            'This cluster type does not support a terminate operation')

    def update(self, request_body):
        """
        Adapters may implement this if they support a update operation.
        """
        raise ValidationException(
            'This cluster type does not support a update operation')

    def delete(self):
        """
        Adapters may implement this if they support a delete operation.
        """
        # If an assetstore was created for this cluster then try to remove it
        if 'assetstoreId' in self.cluster:
            try:
                assetstore = self.model('assetstore').load(
                    self.cluster['assetstoreId'])
                self.model('assetstore').remove(assetstore)
            except ValidationException:
                # If we still have files associated with the assetstore then
                # leave it.
                pass

    def submit_job(self, job):
        log_url = '%s/jobs/%s/log' % (getApiUrl(), job['_id'])
        job['_id'] = str(job['_id'])
        del job['access']

        girder_token = get_task_token()['_id']
        cumulus.starcluster.tasks.job.submit(girder_token, self.cluster, job,
                                             log_url)


class Ec2ClusterAdapter(AbstractClusterAdapter):
    def validate(self):
        query = {
            'name': self.cluster['name'],
            'userId': getCurrentUser()['_id'],
            'type': 'ec2'
        }

        if '_id' in self.cluster:
            query['_id'] = {'$ne': self.cluster['_id']}

        duplicate = self.model('cluster', 'cumulus').findOne(query,
                                                             fields=['_id'])
        if duplicate:
            raise ValidationException(
                'A cluster with that name already exists.', 'name')

        # Check the template exists
        config = self.model('starclusterconfig', 'cumulus').load(
            self.cluster['config']['_id'], force=True)
        config = config['config']

        found = False

        if 'cluster' in config:
            for template in config['cluster']:
                name, _ = template.iteritems().next()

                if self.cluster['template'] == name:
                    found = True
                    break

        if not found:
            raise ValidationException(
                'A cluster template \'%s\' not found in configuration.'
                % self.cluster['template'], 'template')

        return self.cluster

    def start(self, request_body):
        if self.cluster['status'] == 'running':
            raise RestException('Cluster already running.', code=400)

        on_start_submit = None
        if request_body and 'onStart' in request_body and \
           'submitJob' in request_body['onStart']:
            on_start_submit = request_body['onStart']['submitJob']

        base_url = getApiUrl()
        log_write_url = '%s/clusters/%s/log' % (base_url, self.cluster['_id'])
        girder_token = get_task_token()['_id']
        cumulus.starcluster.tasks.cluster.start_cluster \
            .delay(self.cluster,
                   log_write_url=log_write_url,
                   on_start_submit=on_start_submit,
                   girder_token=girder_token)

    def terminate(self):
        base_url = getApiUrl()
        log_write_url = '%s/clusters/%s/log' % (base_url, self.cluster['_id'])

        if self.cluster['status'] == 'terminated' or \
           self.cluster['status'] == 'terminating':
            return

        girder_token = get_task_token()['_id']
        cumulus.starcluster.tasks.cluster.terminate_cluster \
            .delay(self.cluster,
                   log_write_url=log_write_url,
                   girder_token=girder_token)

    def update(self, body):
        # Don't return the access object
        del self.cluster['access']
        # Don't return the log
        del self.cluster['log']

        return self.cluster

    def delete(self):
        super(Ec2ClusterAdapter, self).delete()
        if self.cluster['status'] in ['running', 'initializing']:
            raise RestException('Cluster is active', code=400)

        # Remove the config associated with the cluster first
        self.model('starclusterconfig', 'cumulus').remove(
            {'_id': self.cluster['config']['_id']})


def _validate_key(key):
    try:
        parts = key.split()
        key_type, key_string = parts[:2]
        data = base64.decodestring(key_string)
        return data[4:11] == key_type
    except Exception:
        return False


class TraditionClusterAdapter(AbstractClusterAdapter):
    def validate(self):
        query = {
            'name': self.cluster['name'],
            'userId': getCurrentUser()['_id'],
            'type': 'trad'
        }

        if '_id' in self.cluster:
            query['_id'] = {'$ne': self.cluster['_id']}

        duplicate = self.model('cluster', 'cumulus').findOne(query,
                                                             fields=['_id'])
        if duplicate:
            raise ValidationException(
                'A cluster with that name already exists.', 'name')

        return self.cluster

    def update(self, body):

        # Use JSONPath to extract out what we need
        passphrase = parse('config.ssh.passphrase').find(body)
        public_key = parse('config.ssh.publicKey').find(body)

        if passphrase:
            ssh = self.cluster['config'].setdefault('ssh', {})
            ssh['passphrase'] = passphrase[0].value

        if public_key:
            public_key = public_key[0].value
            if not _validate_key(public_key):
                raise RestException('Invalid key format', 400)

            ssh = self.cluster['config'].setdefault('ssh', {})
            ssh['publicKey'] = public_key

        self.cluster = self.model('cluster', 'cumulus').save(self.cluster)

        # Don't return the access object
        del self.cluster['access']
        # Don't return the log
        del self.cluster['log']
        # Don't return the passphrase
        if parse('config.ssh.passphrase').find(self.cluster):
            del self.cluster['config']['ssh']['passphrase']

        return self.cluster

    def start(self, request_body):
        if self.cluster['status'] == 'creating':
            raise RestException('Cluster is not ready to start.', code=400)

        log_write_url = '%s/clusters/%s/log' % (getApiUrl(),
                                                self.cluster['_id'])
        girder_token = get_task_token()['_id']
        cumulus.starcluster.tasks.cluster.test_connection \
            .delay(self.cluster,
                   log_write_url=log_write_url,
                   girder_token=girder_token)

    def delete(self):
        super(TraditionClusterAdapter, self).delete()
        # Clean up key associate with cluster
        cumulus.ssh.tasks.key.delete_key_pair.delay(self.cluster,
                                                    get_task_token()['_id'])


class NewtClusterAdapter(AbstractClusterAdapter):
    def validate(self):
        query = {
            'name': self.cluster['name'],
            'userId': getCurrentUser()['_id'],
            'type': 'trad'
        }

        if '_id' in self.cluster:
            query['_id'] = {'$ne': self.cluster['_id']}

        duplicate = self.model('cluster', 'cumulus').findOne(query,
                                                             fields=['_id'])
        if duplicate:
            raise ValidationException(
                'A cluster with that name already exists.', 'name')

        return self.cluster

    def update(self, body):

        # Don't return the access object
        del self.cluster['access']
        # Don't return the log
        del self.cluster['log']

        return self.cluster

    def _generate_girder_token(self):
        user = self.model('user').load(self.cluster['userId'], force=True)
        girder_token = self.model('token').createToken(user=user, days=7)

        return girder_token['_id']

    def start(self, request_body):
        log_write_url = '%s/clusters/%s/log' % (getApiUrl(),
                                                self.cluster['_id'])

        girder_token = get_task_token(self.cluster)['_id']
        cumulus.starcluster.tasks.cluster.test_connection \
            .delay(self.cluster,
                   log_write_url=log_write_url,
                   girder_token=girder_token)

    def submit_job(self, job):
        log_url = '%s/jobs/%s/log' % (getApiUrl(), job['_id'])
        job['_id'] = str(job['_id'])
        del job['access']

        girder_token = get_task_token(self.cluster)['_id']
        cumulus.starcluster.tasks.job.submit(girder_token, self.cluster, job,
                                             log_url)


type_to_adapter = {
    ClusterType.EC2: Ec2ClusterAdapter,
    ClusterType.TRADITIONAL: TraditionClusterAdapter,
    ClusterType.NEWT: NewtClusterAdapter
}


def get_cluster_adapter(cluster):
    global type_to_adapter

    return type_to_adapter[cluster['type']](cluster)
