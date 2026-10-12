"""Generic e-paper crawler: finding the page images of an edition, and reading them."""

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.crawler.epaper import generic
from app.crawler.epaper.generic import GenericEpaperCrawler, fill, pages_from_html

DAY = date(2026, 10, 13)
BIG = b"x" * 40000


def test_fill_placeholders():
    t = "https://e.example/{yyyy}/{mm}/{dd}/{date}/p{page2}-{page}.jpg"
    assert fill(t, DAY, 7) == "https://e.example/2026/10/13/2026-10-13/p07-7.jpg"
    assert fill("{date}", DAY, None, "%d-%m-%Y") == "13-10-2026"
    assert fill("{dd}.{mm}", DAY) == "13.10"


def test_kalbela_style_relative_thumbnails_become_full_pages_of_today_only():
    html = ('<img data-src="2026/10/13/1st-Edition/thumb/page02.jpg?v=1.0"> <img src="2026/10/13/1st-Edition/thumb/page01.jpg">'
            '<img src="2026/10/12/2nd-Edition/thumb/page01.jpg">')
    rx = fill(r"(?P<url>{yyyy}/{mm}/{dd}/\d(?:st|nd|rd|th)-Edition/thumb/page(?P<page>\d+)\.jpg)", DAY)
    pages = pages_from_html(html, "https://epaper.kalbela.com/", rx, ["/thumb/", "/large/"])
    assert pages == [(1, "https://epaper.kalbela.com/2026/10/13/1st-Edition/large/page01.jpg"),
                     (2, "https://epaper.kalbela.com/2026/10/13/1st-Edition/large/page02.jpg")]


def test_addresses_escaped_inside_page_data_are_found_and_old_dates_ignored():
    html = ('{"p":["https:\\/\\/img.example.com\\/c\\/date_13-10-2026_edition_1_page_2_x_9.jpg",'
            '"https:\\/\\/img.example.com\\/c\\/date_13-10-2026_edition_1_page_1_y_8.jpg",'
            '"https://img.example.com/c/date_12-10-2026_edition_1_page_1_old.jpg"]}')
    rx = fill(r"(?P<url>https://img\.example\.com/c/date_{dd}-{mm}-{yyyy}_edition_\d+_page_(?P<page>\d+)_[^\"'\s<>\\]+?\.jpg)", DAY)
    pages = pages_from_html(html, "https://epaper.example.com/", rx)
    assert [n for n, _ in pages] == [1, 2] and all("13-10-2026" in u for _, u in pages)


def test_pages_without_a_page_group_are_numbered_in_order():
    pages = pages_from_html('<img src="/a.jpg"><img src="/b.jpg"><img src="/a.jpg">', "https://x.example/", r'(?P<url>/[ab]\.jpg)')
    assert pages == [(1, "https://x.example/a.jpg"), (2, "https://x.example/b.jpg")]


def _client_factory(pages_available, other=None):
    """An AsyncClient whose server has page images 1..pages_available (and optional extra answers by url)."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if other and url in other:
            return other[url]
        for n in range(1, pages_available + 1):
            if url.endswith(f"/p{n:02d}.jpg"):
                return httpx.Response(200, content=BIG, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    return lambda *a, **kw: real(transport=transport, **{k: v for k, v in kw.items() if k not in ("proxy",)})


def _source(**epaper):
    return {"id": "src_epaper_x", "type": "epaper_generic", "newspaper": "The X", "url": "https://x.example/",
            "epaper": {"mode": "template", "image_template": "https://x.example/{date}/p{page2}.jpg",
                       "view_url": "https://x.example/{date}/{page2}", **epaper}}


@pytest.mark.asyncio
async def test_template_mode_reads_every_page_and_stamps_the_notices():
    crawler = GenericEpaperCrawler(_source())
    crawler.parser.extract_tenders_from_image = AsyncMock(side_effect=lambda *a, **k: [{"title": "Audit firm"}])
    with patch.object(generic.httpx, "AsyncClient", _client_factory(5)):
        status, error, tenders = await crawler.crawl_edition(DAY)
    assert (status, error) == (200, None)
    assert [t["_page_no"] for t in tenders] == ["1", "2", "3", "4", "5"]
    t = tenders[2]
    assert t["_newspaper"] == "The X" and t["_page_url"] == "https://x.example/2026-10-13/03"
    assert t["_image_url"] == "https://x.example/2026-10-13/p03.jpg" and t["_edition_date"] == "13/10/2026"


@pytest.mark.asyncio
async def test_template_mode_without_pages_reports_no_pages():
    crawler = GenericEpaperCrawler(_source())
    with patch.object(generic.httpx, "AsyncClient", _client_factory(0)):
        status, error, tenders = await crawler.crawl_edition(DAY)
    assert error.startswith("NO_PAGES") and tenders == []


@pytest.mark.asyncio
async def test_max_pages_is_respected():
    crawler = GenericEpaperCrawler(_source(max_pages=3))
    crawler.parser.extract_tenders_from_image = AsyncMock(side_effect=lambda *a, **k: [{"title": "t"}])
    with patch.object(generic.httpx, "AsyncClient", _client_factory(9)):
        _, error, tenders = await crawler.crawl_edition(DAY)
    assert error is None and len(tenders) == 3


@pytest.mark.asyncio
async def test_html_mode_reads_the_listing_then_the_images():
    page = httpx.Response(200, text='<img src="/img/2026-10-13/p01.jpg"><img src="/img/2026-10-13/p02.jpg">')
    other = {"https://x.example/": page}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) in other:
            return other[str(request.url)]
        return httpx.Response(200, content=BIG, headers={"content-type": "image/jpeg"})

    real = httpx.AsyncClient
    factory = lambda *a, **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "proxy"})  # noqa: E731
    src = {"id": "src_epaper_h", "type": "epaper_generic", "newspaper": "The H", "url": "https://x.example/",
           "epaper": {"mode": "html", "image_regex": r"(?P<url>/img/{date}/p(?P<page>\d+)\.jpg)"}}
    crawler = GenericEpaperCrawler(src)
    crawler.parser.extract_tenders_from_image = AsyncMock(side_effect=lambda *a, **k: [{"title": "t"}])
    with patch.object(generic.httpx, "AsyncClient", factory):
        status, error, tenders = await crawler.crawl_edition(DAY)
    assert error is None and [t["_page_no"] for t in tenders] == ["1", "2"]
    assert tenders[0]["_image_url"] == "https://x.example/img/2026-10-13/p01.jpg"


@pytest.mark.asyncio
async def test_html_mode_blocked_page_is_reported_as_blocked():
    forbidden = {"https://x.example/": httpx.Response(403, text="no")}
    src = {"id": "s", "type": "epaper_generic", "newspaper": "B", "url": "https://x.example/",
           "epaper": {"mode": "html", "image_regex": r"(?P<url>/p\d+\.jpg)"}}
    with patch.object(generic.httpx, "AsyncClient", _client_factory(0, forbidden)):
        status, error, tenders = await GenericEpaperCrawler(src).crawl_edition(DAY)
    assert (status, error, tenders) == (403, "BLOCKED", [])


@pytest.mark.asyncio
async def test_browser_mode_needs_the_browser_flag(monkeypatch):
    monkeypatch.delenv("EPAPER_PC_BROWSER", raising=False)
    src = {"id": "s", "type": "epaper_generic", "newspaper": "B", "url": "https://x.example/", "epaper": {"mode": "browser"}}
    status, error, tenders = await GenericEpaperCrawler(src).crawl_edition(DAY)
    assert error.startswith("NEEDS_PC_BROWSER") and tenders == []
