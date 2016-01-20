from __future__ import absolute_import

from functools import wraps
import json

from girder_client import GirderClient, HttpError

import celery
from celery.signals import before_task_publish, task_failure, task_postrun
import requests
from cumulus.celery import command


class TaskState:
    RUNNING = 'running'
    ERROR = 'error'
    COMPLETE = 'complete'

# This pretty horrid, revist
def _extract_taskflow(args):
    taskflow = None

    for a in args:
        if isinstance(a, dict) and '_is_taskflow' in a:
            taskflow = a

    return taskflow

def _extract_and_patch_args(args):
    taskflow = _extract_taskflow(args)
    if not taskflow:
        return (taskflow, args)

    args_list = list(args)
    args_list.remove(taskflow)
    args = tuple(args_list)

    return (taskflow, args)

def task(func):

    # First apply our own wrapper
    @wraps(func)
    def wrapped(celery_task, *args, **kwargs):

        taskflow, args = _extract_and_patch_args(args)

        # Convert possible serialized taskflow_runner object
        taskflow = to_taskflow(taskflow)

        # Patch task state
        client = GirderClient(apiUrl=taskflow.girder_api_url)
        client.token = taskflow.girder_token

        task_id = celery_task.request.headers['taskflow_task_id']
        body = {
            'status': TaskState.RUNNING
        }
        url = 'tasks/%s' % task_id
        client.patch(url, data=json.dumps(body))

        return func(taskflow, *args, **kwargs)

    # Now apply the celery decorator
    celery_task = command.task(wrapped, bind=True)

    return celery_task

def to_taskflow(d, app=None):
    if d is not None:
        if isinstance(d, dict):
            d = TaskFlow(d)

    return d

class TaskFlow(dict):
    def __init__(self, d=None, id=None, girder_token=None, girder_api_url=None):

        if isinstance(d, dict):
            super(TaskFlow, self).__init__(d)
        else:
            super(TaskFlow, self).__init__(
                girder_api_url=girder_api_url,
                girder_token=girder_token,
                id=id)

        # This feels pretty dirty!
        self['_is_taskflow'] = True

    @property
    def id(self):
        return self['id']

    @property
    def girder_token(self):
        return self['girder_token']

    @property
    def girder_api_url(self):
        return self['girder_api_url']

    # State methods
    def start(self):
        pass

    def terminate(self):
        pass

    def delete(self):
        pass

    def run(self):
        self.start()

@before_task_publish.connect
def task_before_sent_handler(headers=None, body=None, **kwargs):
    # Extract the taskflow dict from the args
    if body['task'] == 'celery.chord_unlock':
        _, callback = body['args'][:2]
        taskflow = _extract_taskflow(callback.args)
    else:
        taskflow = _extract_taskflow(body['args'])

    taskflow_id = taskflow['id']

    girder_token = taskflow['girder_token']
    girder_api_url = taskflow['girder_api_url']

    # Create a task instance
    client = GirderClient(apiUrl=girder_api_url)
    client.token = girder_token

    body = {
        'celeryTaskId': body['id']
    }
    url = 'taskflows/%s/tasks' % taskflow_id
    r = client.post(url, data=json.dumps(body))
    task_id = r['_id']
    # Save the task_id in the headers
    headers['taskflow_task_id'] = task_id

def _celery_id_to_taskflow_id(taskflow, celery_task_id):
    girder_token = taskflow['girder_token']
    girder_api_url = taskflow['girder_api_url']
    client = GirderClient(apiUrl=girder_api_url)
    client.token = girder_token

    params = {
        'celeryTaskId': celery_task_id
    }
    try:
        # TODO log exception information
        # use log handler.
        r = client.get('tasks', parameters=params)
        taskflow_task_id = r['_id']
    except HttpError as he:
        print he.responseText

    return taskflow_task_id

def _update_task_status(girder_token, girder_api_url, task_id, status):
    url = 'tasks/%s' % task_id
    client = GirderClient(apiUrl=girder_api_url)
    client.token = girder_token
    body = {
        'status': status
    }
    client.patch(url, data=json.dumps(body))

@task_failure.connect
def task_failure_handler(task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **extra):

    taskflow, _ = _extract_and_patch_args(args)
    if not taskflow:
        return

    taskflow = to_taskflow(args[0])
    # First get the taskflow_runner task_id
    taskflow_task_id = _celery_id_to_taskflow_id(taskflow, task_id)
    # Now update the status
    taskflow = args[0]
    girder_token = taskflow['girder_token']
    girder_api_url = taskflow['girder_api_url']
    _update_task_status(
        girder_token, girder_api_url, taskflow_task_id, TaskState.ERROR)

# Here we use postrun instead of on success as we need original task
@task_postrun.connect
def task_success_handler(task=None, state=None, args=None, **kwargs):
    if task.name == 'celery.chord_unlock':
        _, callback = args[:2]
        taskflow = _extract_taskflow(callback['args'])
    else:
        taskflow = _extract_taskflow(args)

    if state != celery.states.SUCCESS:
        return

    # First get the taskflow_runner task_id from the celery task headers

    if 'taskflow_task_id' not in task.request.headers:
        return

    taskflow_task_id = task.request.headers['taskflow_task_id']
    # Now update the status
    girder_token = taskflow['girder_token']
    girder_api_url = taskflow['girder_api_url']
    _update_task_status(
        girder_token, girder_api_url, taskflow_task_id, TaskState.COMPLETE)

