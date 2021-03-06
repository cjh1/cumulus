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

from __future__ import absolute_import
import sys
import urllib2
import collections


def check_status(request):
    if request.status_code != 200:
        print >> sys.stderr, request.content
        request.raise_for_status()


def get_config_url(base_url, config_id):
    return '%s/starcluster-configs/%s?format=ini' \
           % (base_url, config_id)


def create_config_request(girder_token, base_url, config_id):
    config_url = get_config_url(base_url, config_id)

    headers = {
        'Girder-Token': girder_token
    }

    config_request = urllib2.Request(config_url, headers=headers)

    return config_request


def update_dict(d, u):
    for k, v in u.iteritems():
        if isinstance(v, collections.Mapping):
            r = update_dict(d.get(k, {}), v)
            d[k] = r
        else:
            d[k] = u[k]

    return d
