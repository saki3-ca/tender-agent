"""pc_browser: proxy settings, and reading a page behind a Cloudflare-style "Just a moment…" check."""

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.crawler import pc_browser


def test_proxy_settings_with_credentials():
    assert pc_browser.proxy_settings("http://us%40er:p%3Ass@proxy.example.com:8080") == {
        "server": "http://proxy.example.com:8080", "username": "us@er", "password": "p:ss"}


def test_proxy_settings_without_credentials_or_value():
    assert pc_browser.proxy_settings("http://proxy.example.com:3128") == {"server": "http://proxy.example.com:3128"}
    assert pc_browser.proxy_settings(None) is None
    assert pc_browser.proxy_settings("not a url") is None


def test_proxy_url_from_environment(monkeypatch):
    monkeypatch.delenv(pc_browser.PROXY_ENV, raising=False)
    assert pc_browser.proxy_url() is None
    monkeypatch.setenv(pc_browser.PROXY_ENV, "  http://p:1  ")
    assert pc_browser.proxy_url() == "http://p:1"


class _Site(BaseHTTPRequestHandler):
    started = time.time()
    clear_after = 3.0     # seconds the check page is shown

    def do_GET(self):  # noqa: N802
        challenged = time.time() - _Site.started < _Site.clear_after
        body = ("<html><head><title>Just a moment...</title></head><body>checking</body></html>" if challenged
                else "<html><head><title>E-Paper</title></head><body>edition page</body></html>").encode()
        self.send_response(403 if challenged else 200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = HTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


async def _read(url):
    async with pc_browser.chrome_pages() as get:
        return await get(url)


def _run(url):
    try:
        return asyncio.run(_read(url))
    except Exception as e:  # noqa: BLE001
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip("no browser installed")
        raise


def test_page_is_returned_once_the_check_clears(site, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setattr(_Site, "started", time.time())
    monkeypatch.setattr(_Site, "clear_after", 3.0)
    status, html = _run(site)
    assert status == 200 and "edition page" in html


def test_403_when_the_check_never_clears(site, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setattr(_Site, "started", time.time())
    monkeypatch.setattr(_Site, "clear_after", 10_000)
    monkeypatch.setattr(pc_browser, "ATTEMPTS", 2)
    monkeypatch.setattr(pc_browser, "CHALLENGE_WAIT_STEPS", 2)
    status, html = _run(site)
    assert status == 403 and "checking" in html
