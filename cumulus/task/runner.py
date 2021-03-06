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

import json
import cumulus
from jinja2 import Environment
from jinja2.exceptions import UndefinedError
import requests
import sys
from cumulus.celery import monitor
import traceback
import time


def _add_log_entry(token, task, entry):
    headers = {'Girder-Token': token}
    url = '%s/tasks/%s/log' % (cumulus.config.girder.baseUrl, task['_id'])
    r = requests.post(url, headers=headers, json=entry)
    _check_status(r)


def _check_status(request):
    if request.status_code != 200:
        print >> sys.stderr, request.content
        request.raise_for_status()


def _remove_empty(d):
    if type(d) is dict:
        return dict((k, _remove_empty(v)) for k, v in d.iteritems() if v and
                    _remove_empty(v))
    elif type(d) is list:
        return [_remove_empty(v) for v in d if v and _remove_empty(v)]
    else:
        return d


def _template_dict(d, variables):
    env = Environment()
    json_str = json.dumps(d)

    # List of templated variables that we want to survive the templating
    # process, these will be resolved later. So we replace them with themselves!
    save = [
        'stdout', 'stderr'
    ]

    template_vars = {}

    for v in save:
        template_vars[v] = '{{%s}}' % v

    template_vars.update(variables)

    json_str = env.from_string(json_str).render(
        amis=cumulus.config.amis, **template_vars)

    d = json.loads(json_str)
    d = _remove_empty(d)

    return d


def _run_http(token, task, variables, step):
    params = step['params']
    headers = {'Girder-Token': token}
    url = '%s%s' % (cumulus.config.girder.baseUrl, params['url'])

    body = None

    if 'body' in params:
        body = params['body']

    r = requests.request(params['method'], url, json=body, headers=headers)
    _check_status(r)

    if 'output' in params:
        variables[params['output']] = r.json()

    if 'log' in step:
        entry = {
            '$ref': step['log']
        }
        _add_log_entry(token, task, entry)


def _run_status(token, task, spec, step, variables):
    # Fire of task to monitor the status
    task['_id'] = str(task['_id'])

    monitor.send_task('cumulus.task.status.monitor_status', args=(
        token, task, spec, step, variables))


def _log_http_error(token, task, err):
    entry = {
        'statusCode': err.response.status_code,
        'content': err.response.content,
        'stack': traceback.format_exc()
    }
    _add_log_entry(token, task, entry)


def run(token, task, spec, variables, start_step=0):
    headers = {'Girder-Token': token}
    update = {}
    try:
        steps = spec['steps']
        for s in range(start_step, len(steps)):
            step = _template_dict(steps[s], variables)
            if step['type'] == 'http':
                _run_http(token, task, variables, step)
            elif step['type'] == 'status':
                spec['steps'][s] = step
                _run_status(token, task, spec, s, variables)
                update['output'] = variables
                return
            if 'terminate' in step:
                url = '%s%s' % (
                    cumulus.config.girder.baseUrl, step['terminate'])
                if 'onTerminate' in update:
                    update['onTerminate'].append(url)
                else:
                    update['onTerminate'] = [url]

            if 'delete' in step:
                url = '%s%s' % (cumulus.config.girder.baseUrl, step['delete'])
                if 'onDelete' in update:
                    update['onDelete'].append(url)
                else:
                    update['onDelete'] = [url]

        # Task is now complete, save the variable into the output property
        # and set status
        update['output'] = variables
        update['status'] = 'complete'
        update['endTime'] = int(round(time.time() * 1000))

    except requests.HTTPError as e:
        _log_http_error(token, task, e)
        update['status'] = 'error'
        raise
    except UndefinedError as e:
        update['status'] = 'error'
        raise
    finally:
        # Update the state of the task if necessary
        try:
            if update:
                url = '%s/tasks/%s' % (cumulus.config.girder.baseUrl,
                                       task['_id'])
                r = requests.patch(url, headers=headers, json=update)
                _check_status(r)
        except requests.HTTPError as e:
            _log_http_error(token, task, e)
