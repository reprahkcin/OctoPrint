# -*- coding: utf-8 -*-
"""
    sockjs.tornado.transports.jsonp
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    JSONP transport implementation.
"""
import logging

from tornado.web import asynchronous

from octoprint.vendor.sockjs.tornado import proto
from octoprint.vendor.sockjs.tornado.transports import pollingbase
from octoprint.vendor.sockjs.tornado.util import bytes_to_str, unquote_plus

LOG = logging.getLogger("tornado.general")

class JSONPTransport(pollingbase.PollingTransportBase):
    name = 'jsonp'

    @asynchronous
    def get(self, session_id):
        # Start response
        self.handle_session_cookie()
        self.disable_cache()

        # Grab callback parameter
        self.callback = self.get_argument('c', None)
        if not self.callback:
            self.write('"callback" parameter required')
            self.set_status(500)
            self.finish()
            return

        # Get or create session without starting heartbeat
        if not self._attach_session(session_id, False):
            return

        # Might get already detached because connection was closed in on_open
        if not self.session:
            return

        if not self.session.send_queue:
            self.session.start_heartbeat()
        else:
            self.session.flush()

    def send_pack(self, message, binary=False):
        if binary:
            raise Exception('binary not supported for JSONPTransport')

        self.active = False

        try:
            # TODO: Just escape
            msg = '%s(%s);\r\n' % (self.callback, proto.json_encode(message))

            self.set_header('Content-Type', 'application/javascript; charset=UTF-8')
            self.set_header('Content-Length', len(msg))

            # TODO: Fix me
            self.set_header('Etag', 'dummy')

            self.write(msg)
            self.flush(callback=self.send_complete)
        except IOError:
            # If connection dropped, make sure we close offending session instead
            # of propagating error all way up.
            self.session.delayed_close()


class JSONPSendHandler(pollingbase.PollingTransportBase):
    def post(self, session_id):
        self.preflight()
        self.handle_session_cookie()
        self.disable_cache()

        session = self._get_session(session_id)

        if session is None or session.is_closed:
            self.set_status(404)
            return

        data = bytes_to_str(self.request.body)

        ctype = self.request.headers.get('Content-Type', '').lower()
        if ctype == 'application/x-www-form-urlencoded':
            if not data.startswith('d='):
                LOG.exception('jsonp_send: Invalid payload.')

                self.write("Payload expected.")
                self.set_status(500)
                return

            data = unquote_plus(data[2:])

        if not data:
            LOG.debug('jsonp_send: Payload expected.')

            self.write("Payload expected.")
            self.set_status(500)
            return

        try:
            messages = proto.json_decode(data)
        except:
            # TODO: Proper error handling
            LOG.debug('jsonp_send: Invalid json encoding')

            self.write("Broken JSON encoding.")
            self.set_status(500)
            return

        try:
            session.on_messages(messages)
        except Exception:
            LOG.exception('jsonp_send: on_message() failed')

            session.close()

            self.write('Message handler failed.')
            self.set_status(500)
            return

        self.write('ok')
        self.set_header('Content-Type', 'text/plain; charset=UTF-8')
        self.set_status(200)
