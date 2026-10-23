
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import ipaddress
import socket
import time
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ThumbnailLoader:
    _reported_errors = set()
    _report_lock = threading.Lock()

    @classmethod
    def _report_failure(cls, error):
        message = type(error).__name__ + ': ' + str(error)
        with cls._report_lock:
            if message in cls._reported_errors or len(cls._reported_errors) >= 15:
                return
            cls._reported_errors.add(message)
        try:
            from YouSnipePaths import appdata_subdirectory
            directory = appdata_subdirectory('Logs')
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / 'YouSnipeThumbnails.log').open('a', encoding='utf-8') as handle:
                handle.write(message[:1000] + '\n')
        except OSError:
            pass

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='YouSnipe-Thumbnail')
        self.cache = {}
        self.failure_times = {}
        self.lock = threading.Lock()

    @staticmethod
    def _safe_url(url):
        if not isinstance(url, str) or len(url) > 4000:
            return False
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in ('localhost',) or host.endswith(('.local', '.internal')):
            return False
        try:
            addr = ipaddress.ip_address(host)
            return addr.is_global
        except ValueError:
            return True

    @classmethod
    def _safe_public_destination(cls, url):
        if not cls._safe_url(url):
            return False
        host = urlsplit(url).hostname
        try:
            destinations = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            return bool(destinations) and all(ipaddress.ip_address(item[4][0]).is_global for item in destinations)
        except (OSError, ValueError):
            return False

    def submit(self, url, size=(120, 68)):
        if not self._safe_url(url):
            return None
        key = (url, size)
        with self.lock:
            task = self.cache.get(key)
            if task is not None and task.done():
                try:
                    failed = task.result() is None
                except Exception:
                    failed = True
                if failed:
                    last = self.failure_times.get(key, 0)
                    if last == 0:
                        self.failure_times[key] = time.monotonic()
                        last = self.failure_times[key]
                    if time.monotonic() - last >= 20:
                        task = None
                        self.cache.pop(key, None)
                        self.failure_times.pop(key, None)
                else:
                    self.failure_times.pop(key, None)
            if task is None:
                task = self.pool.submit(self._fetch, url, size)
                self.cache[key] = task
            return task

    @classmethod
    def _fetch(cls, url, size):
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            cls._report_failure(exc)
            return None
        try:
            
            from urllib.request import build_opener, HTTPRedirectHandler
            class SafeRedirect(HTTPRedirectHandler):
                redirects = 0
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    self.redirects += 1
                    if self.redirects > 4 or not cls._safe_public_destination(newurl):
                        return None
                    return super().redirect_request(req, fp, code, msg, headers, newurl)
            if not cls._safe_public_destination(url):
                return None
            opener = build_opener(SafeRedirect())
            with opener.open(Request(url, headers={'User-Agent': 'Mozilla/5.0 YouSnipe/1.0'}), timeout=8) as response:
                if int(response.headers.get('Content-Length') or 0) > 4_000_000:
                    return None
                content = response.read(4_000_001)
            if len(content) > 4_000_000:
                return None
            with Image.open(BytesIO(content)) as img:
                img.load()
                return ImageOps.contain(img.convert('RGB'), size)
        except Exception as exc:
            cls._report_failure(exc)
            return None
