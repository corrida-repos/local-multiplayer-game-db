"""Declared crawler, per-host pacing, robots checks, and postcode-redacted errors."""
import gzip
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

AGENT = 'SofaDuoPrices/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'
LIMIT = 12 * 1024 * 1024


class SourceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def redact(value):
    text = str(value)
    postcode = os.environ.get('PRICING_POSTCODE', '').strip()
    if postcode:
        text = text.replace(postcode, '[delivery-area]').replace(urllib.parse.quote(postcode), '[delivery-area]')
    return re.sub(r'\b\d{4}-\d{3}\b', '[delivery-area]', text)


class Client:
    def __init__(self, delay=1.1, attempts=3):
        self.delay = delay
        self.attempts = attempts
        self.robots = {}
        self.locks = {}
        self.last = {}
        self.guard = threading.Lock()

    def pace(self, host, delay):
        with self.guard:
            lock = self.locks.setdefault(host, threading.Lock())
        with lock:
            time.sleep(max(0, delay - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()

    def raw(self, url):
        request = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,application/json,application/xml;q=0.9', 'Accept-Encoding': 'gzip', 'Accept-Language': 'pt-PT,pt;q=0.9,en;q=0.5'})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read(LIMIT + 1)
                if len(body) > LIMIT:
                    raise SourceError('unsupported', 'Response exceeds bounded parser size')
                if response.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                return response.geturl(), body.decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            status = 'blocked' if exc.code in [401, 403] else 'throttled' if exc.code in [408, 429, 500, 502, 503, 504] else 'not_found' if exc.code in [404, 410] else 'error'
            raise SourceError(status, 'HTTP ' + str(exc.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError, EOFError):
            raise SourceError('error', 'Network unavailable or timed out') from None

    def robot(self, parsed):
        root = parsed.scheme + '://' + parsed.netloc
        if root not in self.robots:
            self.pace(parsed.hostname, self.delay)
            try:
                _, page = self.raw(root + '/robots.txt')
            except SourceError as exc:
                if exc.status != 'not_found':
                    raise
                page = 'User-agent: *\nAllow: /'
            robot = urllib.robotparser.RobotFileParser()
            robot.parse(page.splitlines())
            self.robots[root] = robot
        return self.robots[root]

    def get(self, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname:
            raise SourceError('unsupported', 'HTTPS source URL required')
        robot = self.robot(parsed)
        if not robot.can_fetch(AGENT, url):
            raise SourceError('blocked', 'Source robots policy excludes this resource')
        delay = max(self.delay, robot.crawl_delay(AGENT) or 0)
        for attempt in range(self.attempts):
            self.pace(parsed.hostname, delay)
            try:
                return self.raw(url)
            except SourceError as exc:
                if exc.status not in ['throttled', 'error'] or attempt == self.attempts - 1:
                    raise
                time.sleep(min(20, 2 ** attempt * 2))

    def json(self, url):
        final, page = self.get(url)
        try:
            return final, json.loads(page)
        except ValueError:
            raise SourceError('unsupported', 'Public response does not contain expected JSON') from None
