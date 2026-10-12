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
                return httpx.Response(200, content=BIG + b"y" * n * 100, headers={"content-type": "image/jpeg"})   # every page its own size
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


# ---------------------------------------------------------------- the configured newspapers
def _generic_sources():
    from app.utils.config import config
    return [s for s in config.sources if s.get("type") == "epaper_generic"]


def test_every_generic_source_is_complete_and_its_patterns_are_valid():
    import re
    sources = _generic_sources()
    assert sources, "no epaper_generic sources configured"
    for s in sources:
        cfg = s["epaper"]
        assert s.get("newspaper") and s["organization_id"].startswith("epaper_"), s["id"]
        assert cfg["mode"] in ("template", "html", "browser"), s["id"]
        if cfg["mode"] == "template":
            assert "{page" in cfg["image_template"], s["id"]
            assert fill(cfg["image_template"], DAY, 3).startswith("http"), s["id"]
        if cfg["mode"] == "html":
            re.compile(fill(cfg["image_regex"], DAY))       # must be a valid pattern
        assert "{page" in cfg.get("view_url", "{page}") or cfg.get("view_url", "").startswith("http"), s["id"]


def test_configured_kalbela_and_ajker_patrika_patterns_find_pages_in_the_real_markup():
    by_id = {s["id"]: s for s in _generic_sources()}
    kal = by_id["src_epaper_kalbela"]["epaper"]
    html = ('<img class="img-fluid" data-src="2026/10/13/1st-Edition/thumb/page02.jpg?v=1.0" src="2026/10/13/1st-Edition/thumb/page02.jpg?v=1.0">'
            '<img data-src="2026/10/13/1st-Edition/thumb/page01.jpg?v=1.0">')
    pages = pages_from_html(html, "https://epaper.kalbela.com/", fill(kal["image_regex"], DAY), kal.get("replace"))
    assert pages == [(1, "https://epaper.kalbela.com/2026/10/13/1st-Edition/large/page01.jpg?v=1.0".split("?")[0]),
                     (2, "https://epaper.kalbela.com/2026/10/13/1st-Edition/large/page02.jpg")]

    ajk = by_id["src_epaper_ajkerpatrika"]["epaper"]
    html = ('<img src="https://eimages.ajkerpatrika.com/compressedepaper/date_13-10-2026_edition_1_page_1_821838_62166_updated_LateEdition-01-Layout%201_compressed_9338a3ec.jpg">'
            '<img src="https://eimages.ajkerpatrika.com/cropped-images/image_sl13_row12_date_13-10-2026_edition_1_page1_372692.jpg">')
    pages = pages_from_html(html, "https://epaper.ajkerpatrika.com/", fill(ajk["image_regex"], DAY))
    assert len(pages) == 1 and pages[0][0] == 1 and "compressedepaper" in pages[0][1]


@pytest.mark.asyncio
async def test_stock_image_answered_for_every_page_number_is_not_counted_as_pages():
    sizes = {1: 50000, 2: 61000, 3: 58000, 4: 52000}          # real pages differ; 5.. all return the same stock image

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(str(request.url).rsplit("/p", 1)[1][:2])
        return httpx.Response(200, content=b"x" * sizes.get(n, 45000), headers={"content-type": "image/jpeg"})

    real = httpx.AsyncClient
    factory = lambda *a, **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "proxy"})  # noqa: E731
    crawler = GenericEpaperCrawler(_source(max_pages=10))
    with patch.object(generic.httpx, "AsyncClient", factory):
        status, error, pages = await crawler.discover(httpx.AsyncClient(), DAY, 10)
    assert error is None
    assert [n for n, _ in pages] == [1, 2, 3, 4, 5]    # the first stock image may be page 5 itself; the repeats are dropped


@pytest.mark.asyncio
async def test_html_page_answered_with_status_200_for_missing_pages_is_not_a_page():
    """Amader Shomoy answers page 13 and up with a 10 KB HTML page and status 200."""
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(str(request.url).rsplit("/p", 1)[1][:2])
        if n <= 12:
            return httpx.Response(200, content=b"x" * (60000 + n * 100), headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=b"<html>" + b"x" * 10567, headers={"content-type": "text/html; charset=UTF-8"})

    real = httpx.AsyncClient
    factory = lambda *a, **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "proxy"})  # noqa: E731
    crawler = GenericEpaperCrawler(_source(max_pages=24))
    with patch.object(generic.httpx, "AsyncClient", factory):
        _, error, pages = await crawler.discover(httpx.AsyncClient(), DAY, 24)
    assert error is None and [n for n, _ in pages] == list(range(1, 13))


def test_image_names_with_a_space_are_found_and_encoded():
    """Ajker Patrika / Amar Desh write the page file names with a space in them, inside srcSet lists."""
    html = ('<img srcSet="https://eimages.example.com/compressedepaper/date_13-10-2026_edition_1_page_1_8_6_updated_LateEdition-01-Layout 1_compressed_93.jpg 1x, '
            'https://eimages.example.com/compressedepaper/date_13-10-2026_edition_1_page_1_8_6_updated_LateEdition-01-Layout 1_compressed_93.jpg 2x" '
            'src="https://eimages.example.com/compressedepaper/date_13-10-2026_edition_1_page_1_8_6_updated_LateEdition-01-Layout 1_compressed_93.jpg">')
    rx = fill(r"(?P<url>https://eimages\.example\.com/compressedepaper/date_{dd}-{mm}-{yyyy}_edition_\d+_page_(?P<page>\d+)_[^\"'<>\\]+?\.jpg)", DAY)
    pages = pages_from_html(html, "https://epaper.example.com/", rx)
    assert len(pages) == 1 and pages[0][1].endswith("Layout%201_compressed_93.jpg") and " " not in pages[0][1]
