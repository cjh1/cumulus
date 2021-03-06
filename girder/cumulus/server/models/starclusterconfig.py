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

from jsonpath_rw import parse
from bson.objectid import ObjectId

from girder.constants import AccessType
from .base import BaseModel
from girder.models.model_base import ValidationException
from girder.api.rest import getCurrentUser


class Starclusterconfig(BaseModel):

    def __init__(self):
        super(Starclusterconfig, self).__init__()

    def initialize(self):
        self.name = 'starclusterconfigs'

    def validate(self, doc):
        profile_id = parse('aws.profileId').find(doc)

        if profile_id:
            profile_id = profile_id[0].value
            profile = self.model('aws', 'cumulus').load(profile_id,
                                                        user=getCurrentUser())

            if not profile:
                raise ValidationException('Invalid profile id')

            doc['aws']['profileId'] = profile['_id']

        return doc

    def create(self, config):
        group = {
            '_id': ObjectId(self.get_group_id())
        }

        doc = self.setGroupAccess(config, group, level=AccessType.ADMIN,
                                  save=False)
        self.save(doc)

        return doc
