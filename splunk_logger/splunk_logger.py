import urllib
import socket
import json
import logging
import gzip
import cStringIO

import requests

from .utils import parse_config_file, get_config_from_env


class SplunkLogger(logging.Handler):
    """
    A class to send messages to splunk storm using their API
    """

    # The default is to log to splunk storm
    INPUT_URL = 'https://api.splunkstorm.com/1/inputs/http'


    def __init__(self, access_token=None, project_id=None, input_url=INPUT_URL):
        logging.Handler.__init__(self)
        
        self.url = input_url
        self._set_auth(access_token, project_id)
        self._set_url_opener()
        
        # Handle errors in authentication
        self._auth_failed = False
        
    def _set_auth(self, access_token, project_id):
        # The access token and project id passed as parameter override the ones
        # configured in the .splunk_logger file.
        if access_token is not None and project_id is not None:
            self.project_id = project_id
            self.access_token = access_token
        else:
            self.project_id, self.access_token = parse_config_file()

            if self.project_id is None or self.access_token is None:
                self.project_id, self.access_token = get_config_from_env()

        if self.access_token is None or self.project_id is None:
            raise ValueError('Access token and project id need to be set.')

    def _set_url_opener(self):
        # We disable the logging of the requests module to avoid some infinite
        # recursion errors that might appear.
        requests_log = logging.getLogger("requests")
        requests_log.setLevel(logging.CRITICAL)

        self.session = requests.Session()
        self.session.auth = ('x', self.access_token)
        self.session.headers.update({'Content-Encoding': 'gzip'})

    def usesTime(self):
        return False

    def _compress(self, input_str):
        '''
        Compress the log message in order to send less bytes to the wire.
        '''
        compressed_bits = cStringIO.StringIO()
        
        f = gzip.GzipFile(fileobj=compressed_bits, mode='wb')
        f.write(input_str)
        f.close()
        
        return compressed_bits.getvalue()

    def emit(self, record):
        
        if self._auth_failed:
            # Don't send anything else once a 401 was returned
            return
        
        try:
            response = self._send_to_splunk(record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            # All errors end here.
            self.handleError(record)
        else:
            if response.status_code == 401:
                self._auth_failed = True
            
    def _send_to_splunk(self, record):
        # http://docs.splunk.com/Documentation/Storm/latest/User/Sourcesandsourcetypes
        sourcetype = 'json_no_timestamp'
        
        host = socket.gethostname()
        
        event_dict = {'data': self.format(record),
                      'level': record.levelname,
                      'module': record.module,
                      'line': record.lineno}
        event = json.dumps(event_dict)
        event = self._compress(event)
        
        params = {'project': self.project_id,
                  'sourcetype': sourcetype}
        params['host'] = host

        url = '%s?%s' % (self.url, urllib.urlencode(params))
        return self.session.post(url, data=event, verify=False)


