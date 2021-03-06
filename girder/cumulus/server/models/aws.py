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

from starcluster.awsutils import EasyEC2
from starcluster.exception import RegionDoesNotExist, ZoneDoesNotExist
from boto.exception import EC2ResponseError
from bson.objectid import ObjectId

from girder.constants import AccessType

from .base import BaseModel
from girder.models.model_base import ValidationException
from girder.api.rest import getCurrentUser
from cumulus.common.girder import create_status_notifications


class Aws(BaseModel):
    def __init__(self):
        super(Aws, self).__init__()

    def initialize(self):
        self.name = 'aws'
        self.ensureIndices(['userId', 'name'])
        self.exposeFields(level=AccessType.READ, fields=(
            '_id', 'name', 'accessKeyId', 'regionName', 'regionHost',
            'availabilityZone', 'status', 'errorMessage', 'publicIPs'))

    def validate(self, doc):
        name = doc['name']

        if type(doc['publicIPs']) != bool:
            raise ValidationException('Value must be of type boolean',
                                      'publicIPs')

        if not name:
            raise ValidationException('A name must be provided', 'name')

        # Check for duplicate names
        query = {
            'name': name,
            'userId': doc['userId']
        }
        if '_id' in doc:
            query['_id'] = {'$ne': doc['_id']}

        if self.findOne(query):
            raise ValidationException('A profile with that name already exists',
                                      'name')

        ec2 = EasyEC2(doc['accessKeyId'],
                      doc['secretAccessKey'])

        try:
            region = ec2.get_region(doc['regionName'])
            # Only do the rest of the validation if this is a new profile (not
            # a key update )
            if '_id' not in doc:
                ec2.connect_to_region(doc['regionName'])
                ec2.get_zone(doc['availabilityZone'])
                doc['regionHost'] = region.endpoint
        except EC2ResponseError:
            raise ValidationException('Invalid AWS credentials')
        except RegionDoesNotExist:
            raise ValidationException('Invalid region', 'regionName')
        except ZoneDoesNotExist:
            raise ValidationException('Invalid zone', 'availabilityZone')

        return doc

    def create_profile(self, userId, name, access_key_id, secret_access_key,
                       region_name, availability_zone, public_ips):

        user = getCurrentUser()
        profile = {
            'name': name,
            'accessKeyId': access_key_id,
            'secretAccessKey': secret_access_key,
            'regionName': region_name,
            'availabilityZone': availability_zone,
            'userId': userId,
            'status': 'creating',
            'publicIPs': public_ips
        }

        profile = self.setUserAccess(profile, user, level=AccessType.ADMIN,
                                     save=False)
        group = {
            '_id': ObjectId(self.get_group_id())
        }
        profile = self.setGroupAccess(profile, group, level=AccessType.ADMIN)

        return self.save(profile)

    def find_profiles(self, userId):
        query = {
            'userId': userId
        }

        return self.find(query)

    def update_aws_profile(self, user, profile):
        profile_id = profile['_id']
        current_profile = self.load(profile_id, user=user,
                                    level=AccessType.ADMIN)
        new_status = profile['status']
        if current_profile['status'] != new_status:
            notification = {
                '_id': profile_id,
                'status': new_status
            }
            create_status_notifications('profile', notification,
                                        current_profile)

        return self.save(profile)
