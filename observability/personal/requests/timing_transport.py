"""Per-request timings for direct HTTPS, with one shared network deadline.

Only duration values and validated opaque correlation IDs leave this module.
The OS resolver cannot be cancelled: at most four daemon lookups can outlive a
request deadline. No new socket or HTTP request starts after that deadline.
"""
from contextlib import contextmanager
import errno
import http.client
import math
import re
import socket
import threading
import time
import uuid

PHASES = ('client_setup', 'dns', 'tcp_connect', 'tls_handshake', 'request_send',
          'response_headers_wait', 'response_body', 'validation', 'cleanup')
_DNS_SLOTS = threading.BoundedSemaphore(4)
_EXTENDED_ID = re.compile(r'[A-Za-z0-9+/_-]{8,126}={0,2}')


def canonical_uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


def extended_request_id(value):
    return value if isinstance(value, str) and _EXTENDED_ID.fullmatch(value) else None


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return round(value, 3) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def sanitize_measurement(raw):
    """Copy the additive measurement contract; never copy arbitrary headers."""
    raw = raw if isinstance(raw, dict) else {}
    timings = raw.get('timing_ms')
    timings = timings if isinstance(timings, dict) else {}
    correlation = raw.get('correlation')
    correlation = correlation if isinstance(correlation, dict) else {}
    phase = raw.get('phase_at_failure')
    phase = phase if isinstance(phase, str) and phase in PHASES else None
    return {
        'client_probe_id': canonical_uuid(raw.get('client_probe_id')),
        'timing_ms': {name: _duration(timings.get(name)) for name in PHASES},
        'phase_at_failure': phase,
        'failed_phase_elapsed_ms': _duration(raw.get('failed_phase_elapsed_ms')) if phase else None,
        'correlation': {
            'app_request_id': canonical_uuid(correlation.get('app_request_id')),
            'gateway_extended_request_id': extended_request_id(correlation.get('gateway_extended_request_id')),
            'gateway_request_id': canonical_uuid(correlation.get('gateway_request_id')),
        },
    }


def response_correlation(response):
    # getheader joins duplicate values with commas; validation then rejects them.
    return {
        'app_request_id': canonical_uuid(response.getheader('X-Slash-Request-Id')),
        'gateway_extended_request_id': extended_request_id(response.getheader('x-amz-apigw-id')),
        'gateway_request_id': canonical_uuid(response.getheader('x-amzn-requestid')),
    }


class PhaseTimings:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.values = {name: None for name in PHASES}
        self.failed_phase = None
        self.failed_elapsed_ms = None

    @contextmanager
    def measure(self, name):
        started = self.clock()
        try:
            yield
        except BaseException:
            if self.failed_phase is None:
                self.failed_phase = name
                self.failed_elapsed_ms = round(max(0, self.clock() - started) * 1000, 3)
            raise
        else:
            self.values[name] = round(max(0, self.clock() - started) * 1000, 3)

    def validation_failed(self):
        self.failed_phase = 'validation'


class Deadline:
    def __init__(self, started, timeout, clock=time.monotonic):
        self.clock = clock
        self.ends_at = started + timeout
        self.expired = threading.Event()
        self._lock = threading.Lock()
        self._sockets = set()
        self._timer = threading.Timer(max(0, self.ends_at - self.clock()), self.abort)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self):
        remaining = self.ends_at - self.clock()
        if self.expired.is_set() or remaining <= 0:
            raise TimeoutError
        return remaining

    @staticmethod
    def _close(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def register(self, sock):
        with self._lock:
            if not self.expired.is_set():
                self._sockets.add(sock)
                return
        self._close(sock)
        raise TimeoutError

    def abort(self):
        self.expired.set()
        with self._lock:
            sockets = tuple(self._sockets)
        for sock in sockets:
            self._close(sock)

    def finish(self):
        self._timer.cancel()

    def set_socket_timeout(self, sock):
        sock.settimeout(self.remaining())


def resolve(host, port, deadline):
    """Wait only until the shared deadline; bound uninterruptible OS lookups."""
    slots = _DNS_SLOTS
    if not slots.acquire(timeout=deadline.remaining()):
        raise TimeoutError
    ready = threading.Event()
    result = []

    def lookup():
        try:
            result.append((True, socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)))
        except Exception as error:
            result.append((False, error))
        finally:
            slots.release()
            ready.set()

    worker = threading.Thread(target=lookup, name='slash-bounded-dns', daemon=True)
    try:
        worker.start()
    except BaseException:
        slots.release()
        raise
    if not ready.wait(deadline.remaining()):
        raise TimeoutError
    deadline.remaining()
    ok, value = result[0]
    if not ok:
        raise value
    return value


class TimedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, *, timeout, context, deadline, timings):
        super().__init__(host, port, timeout=timeout, context=context)
        self.deadline = deadline
        self.timings = timings

    def connect(self):
        if self._tunnel_host or self.source_address:
            raise ValueError('Only direct HTTPS connections are supported.')
        with self.timings.measure('dns'):
            addresses = resolve(self.host, self.port, self.deadline)
        with self.timings.measure('tcp_connect'):
            last_error = None
            for family, kind, proto, _name, address in addresses:
                self.deadline.remaining()
                sock = socket.socket(family, kind, proto)
                self.deadline.register(sock)
                try:
                    self.deadline.set_socket_timeout(sock)
                    sock.connect(address)
                    self.deadline.remaining()
                    self.sock = sock
                    break
                except OSError as error:
                    sock.close()
                    last_error = error
            else:
                raise last_error if last_error is not None else OSError('No addresses')
            # Preserve HTTPConnection.connect's TCP behavior while splitting
            # its original DNS/TCP/TLS work into measured phases.
            try:
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as error:
                if error.errno != errno.ENOPROTOOPT:
                    raise
        with self.timings.measure('tls_handshake'):
            self.deadline.set_socket_timeout(self.sock)
            # Register the SSL socket before the blocking handshake. The raw
            # socket becomes detached during wrap_socket; both close safely.
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host,
                                                  do_handshake_on_connect=False)
            self.deadline.register(self.sock)
            self.deadline.set_socket_timeout(self.sock)
            self.sock.do_handshake()
            self.deadline.remaining()
