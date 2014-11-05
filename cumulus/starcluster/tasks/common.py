import cumulus.starcluster.logging
import requests
import tempfile
import traceback
import sys
import os

def _write_config_file(girder_token, config_url):
        headers = {'Girder-Token':  girder_token}

        r = requests.get(config_url, headers=headers, params={'format': 'ini'})
        r.raise_for_status()

        # Write config to temp file
        (fd, config_filepath)  = tempfile.mkstemp()

        try:
            os.write(fd, r.text)
        finally:
            os.close(fd)

        return config_filepath

def _log_exception(ex):
    log = starcluster.logger.get_starcluster_logger()
    log.error(traceback.format_exc())

def _check_status(request):
    if request.status_code != 200:
        print sys.stderr, request.json()
        request.raise_for_status()

