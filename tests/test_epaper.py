import json
import pytest
from unittest.mock import AsyncMock, patch

import httpx
from app.crawler.epaper.bangladeshtoday import BangladeshTodayEpaperCrawler
from app.crawler.epaper.bdpratidin import full_page_image, page_numbers
from app.crawler.epaper.dhakatribune import DhakaTribuneEpaperCrawler
from app.crawler.epaper.financialexpress import FinancialExpressEpaperCrawler
from app.crawler.epaper.jugantor import page_images
from app.crawler.epaper.prothomalo import ProthomAloEpaperCrawler
from app.crawler.epaper.protidinerbangladesh import ProtidinerBangladeshEpaperCrawler
from app.parsers.epaper_gemini import GEMINI_MODELS, GeminiEpaperParser


@pytest.mark.asyncio
async def test_epaper_gemini_parser():
    mock_response_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps([
                                {
                                    "organization": "Dhaka South City Corporation",
                                    "organization_type": "Government",
                                    "title": "e-Tender Notice for Road Works",
                                    "ref_no": "46.207.000.21.16.0014.2026",
                                    "publication_date": "06/10/2026",
                                    "deadline": "22-Oct-2026 15:00",
                                    "category": "Works",
                                    "details": "e-GP portal works in Sayedabad",
                                    "contact": "Executive Engineer, Zone-5"
                                }
                            ])
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_response_json,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/")
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        parser = GeminiEpaperParser(api_keys=["test_key", "test_key_backup"])
        tenders = await parser.extract_tenders_from_image(b"fake_image_bytes")

        assert len(tenders) == 1
        assert tenders[0]["organization"] == "Dhaka South City Corporation"
        assert tenders[0]["ref_no"] == "46.207.000.21.16.0014.2026"
        assert tenders[0]["deadline"] == "22-Oct-2026 15:00"


@pytest.mark.asyncio
async def test_prothomalo_crawler_page_list():
    sample_html = """
    <html>
    <head><title>Prothom Alo e-Paper</title></head>
    <body>
    <script>
    var pglist_ = [
        {"PageId": 511517, "PageNo": "4", "NewsProPageTitle": "খবর", "HighResolution": "https://images.eprothomalo.com/PA/page4.jpg"}
    ];
    </script>
    </body>
    </html>
    """

    crawler = ProthomAloEpaperCrawler()
    mock_client = AsyncMock()
    mock_client.get.return_value = httpx.Response(
        status_code=200,
        text=sample_html,
        request=httpx.Request("GET", "https://epaper.prothomalo.com/")
    )

    pages = await crawler.fetch_page_list(mock_client, "07/10/2026")
    assert len(pages) == 1
    assert pages[0]["PageId"] == 511517
    assert pages[0]["PageNo"] == "4"


@pytest.mark.asyncio
async def test_financial_express_crawler():
    crawler = FinancialExpressEpaperCrawler()
    assert crawler is not None


@pytest.mark.asyncio
async def test_bangladesh_today_crawler():
    crawler = BangladeshTodayEpaperCrawler()
    assert crawler is not None


@pytest.mark.asyncio
async def test_protidiner_bangladesh_crawler():
    crawler = ProtidinerBangladeshEpaperCrawler()
    assert crawler is not None


@pytest.mark.asyncio
async def test_dhaka_tribune_crawler():
    crawler = DhakaTribuneEpaperCrawler()
    assert crawler is not None


@pytest.mark.asyncio
async def test_gemini_failure_is_counted_not_silent():
    failed = httpx.Response(status_code=429, text="quota exceeded",
                            request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"))
    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post, \
            patch("app.parsers.epaper_gemini.asyncio.sleep", new_callable=AsyncMock):
        mock_post.return_value = failed
        parser = GeminiEpaperParser(api_keys=["k"])
        assert await parser.extract_tenders_from_image(b"img") == []
    assert (parser.pages_read, parser.pages_failed) == (0, 1)
    assert "quota" in parser.last_error
    assert mock_post.await_count == len(GEMINI_MODELS)  # exhausted models are not retried


@pytest.mark.asyncio
async def test_slow_gemini_gives_up_on_the_page_instead_of_retrying_for_half_an_hour():
    from app.parsers import epaper_gemini
    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post, \
            patch("app.parsers.epaper_gemini.asyncio.sleep", new_callable=AsyncMock), \
            patch.dict(epaper_gemini._TIMEOUTS, clear=True), \
            patch.object(epaper_gemini, "_UNUSABLE", set()):
        mock_post.side_effect = httpx.ReadTimeout("slow")
        parser = GeminiEpaperParser(api_keys=["k1", "k2"])
        assert await parser._extract(b"img", "image/jpeg") is None
        # every (key, model) timed out twice and was then dropped: 2 rounds, not 3 rounds x every model x 120 s
        assert mock_post.await_count == 2 * 2 * len(GEMINI_MODELS)
        assert all(n == 2 for n in epaper_gemini._TIMEOUTS.values())


def test_jugantor_page_images_skip_clippings_and_features():
    html = """
    <img src="https://epaper.jugantor.com/storage/2026-10-08/1/1791396290_1.jpg">
    <img src="https://epaper.jugantor.com/storage/2026-10-08/1/link_img_1791396585_1.jpg">
    <img src="https://epaper.jugantor.com/storage/2026-10-08/10/1791396300_10.jpg">
    <img src="https://epaper.jugantor.com/storage/feature_page/2026-10-06/1/1791231204_1.jpg">
    """
    assert page_images(html, "2026-10-08") == {
        1: "https://epaper.jugantor.com/storage/2026-10-08/1/1791396290_1.jpg",
        10: "https://epaper.jugantor.com/storage/2026-10-08/10/1791396300_10.jpg",
    }


def test_bd_pratidin_pages_and_full_size_image():
    home = '<a href="https://www.bd-pratidin.com/epaper/2026-10-08/1"></a><a href="/epaper/2026-10-08/12"></a>'
    assert page_numbers(home, "2026-10-08") == [1, 12]
    view = ('<img src="https://cdn.bd-pratidin.com/public/paper/2026/10/08/page-4/page-4-tag-7.jpg">'
            '<img src="https://cdn.bd-pratidin.com/public/paper/2026/10/08/thumb/1791401703-3.jpg">')
    assert full_page_image(view, "2026/10/08", 3) == \
        "https://cdn.bd-pratidin.com/public/paper/2026/10/08/1791401703-3.jpg"
    assert full_page_image(view, "2026/10/08", 4) is None


def test_generic_epaper_page_images():
    from datetime import date
    from app.crawler.epaper.generic import edition_urls

    # JSON-escaped relative paths (Inqilab), first occurrence per page, sorted by page number
    html = (r'{"p":"uploads\/epaper\/2026\/11\/22\/pages\/1\/page_3.jpg"} '
            '"uploads/epaper/2026/11/22/pages/1/page_2.jpg" "uploads/epaper/2026/11/21/pages/1/page_9.jpg"')
    src = {"page_regex": r"uploads/epaper/{Y}/{m}/{d}/pages/\d+/page_(?P<n>\d+)\.jpg"}
    assert edition_urls(html, "https://epaper.dailyinqilab.com/", date(2026, 11, 22), src) == [
        (2, "https://epaper.dailyinqilab.com/uploads/epaper/2026/11/22/pages/1/page_2.jpg"),
        (3, "https://epaper.dailyinqilab.com/uploads/epaper/2026/11/22/pages/1/page_3.jpg")]

    # image_template built from named groups (Samakal thumbnail -> full page)
    html = ('<a title="Page 2" href="https://epaper.samakal.com/nogor-edition/2026-11-22/2"><img src="https://epaper.'
            'samakal.com/../uploads/epaper/2026/11/22/thumb/page6b0204dd7e04c.jpg" style="width: 100%"></a>')
    src = {"page_regex": r'title="Page (?P<n>\d+)" href="[^"]*/nogor-edition/[^"]*"><img src="[^"]*?'
                         r'(?P<path>uploads/epaper/{Y}/{m}/{d})/thumb/(?P<id>page\w+)\.jpg',
           "image_template": "https://epaper.samakal.com/{path}/pages/{id}.jpg"}
    assert edition_urls(html, "https://epaper.samakal.com/", date(2026, 11, 22), src) == [
        (2, "https://epaper.samakal.com/uploads/epaper/2026/11/22/pages/page6b0204dd7e04c.jpg")]

    # template using the date (Observer page views)
    src = {"page_regex": r'onclick="loadpage\((?P<n>\d+)\);',
           "image_template": "https://epaper.observerbd.com/{Y}/{m}/{d}/{n}.htm"}
    html = '<a id="1" onclick="loadpage(1); return false;">1</a><a id="2" onclick="loadpage(2); return false;">2</a>'
    assert [u for _, u in edition_urls(html, "https://epaper.observerbd.com/", date(2026, 11, 22), src)] == [
        "https://epaper.observerbd.com/2026/11/22/1.htm", "https://epaper.observerbd.com/2026/11/22/2.htm"]


@pytest.mark.asyncio
async def test_generic_epaper_checks_every_redirect_hop():
    from app.crawler.epaper.generic import GenericEpaperCrawler
    requested = []

    def handler(req):
        requested.append(str(req.url))
        if str(req.url) == "https://epaper.samakal.com/a.jpg":
            return httpx.Response(302, headers={"location": "/b.jpg"})
        if str(req.url) == "https://epaper.samakal.com/b.jpg":
            return httpx.Response(200, content=b"img")
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    crawler = GenericEpaperCrawler({"id": "s", "url": "https://epaper.samakal.com/", "page_regex": "(?P<n>1)"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await crawler._get(client, "https://epaper.samakal.com/a.jpg")).content == b"img"
        assert await crawler._get(client, "https://epaper.samakal.com/evil.jpg") is None
        assert await crawler._get(client, "https://evil.example/x.jpg") is None
    assert not any("169.254" in u or "evil.example" in u for u in requested)


def test_epaper_ocr_refuses_oversized_and_strip_images():
    from io import BytesIO
    from PIL import Image
    from app.parsers.epaper_ocr import _ocr_sync

    def png(w, h):
        buf = BytesIO()
        Image.new("L", (w, h), 255).save(buf, "PNG")
        return buf.getvalue()

    assert _ocr_sync(png(1, 5000)) == ""        # a 1 px strip would otherwise be upscaled 1400x
    assert _ocr_sync(png(9000, 9000)) == ""     # 81 MP: above MAX_PIXELS


def test_ocr_finds_a_small_audit_notice_inside_a_page_full_of_tenders():
    # Pratidin 23 Nov 2026 p.9: RAOWA's external-audit notice sat between daycare food tenders; the merged OCR block
    # was thousands of characters long and the audit wording fell outside what was classified.
    from app.parsers.epaper_ocr import ocr_items
    filler = ("e-GP Tender Notice Ref. No- 32.01.0000.000.706.07.0001.26-761 Appointment of Supplier for Supplying "
              "Child Food to Daycare Center in Dhaka under the Department of Women Affairs. Tender ID 1359793 OTM. "
              "This is an online tender, where only e-tender will be accepted in the national e-GP portal. ") * 6
    raowa = ("“HOM কপ WE\" ২০২৬-২০২৭ অর্থবছরের THA feria জন্য বিভিন্ন অডিট ফার্মের নিকট হতে অনলাইনে "
             "(raowa.office@gmail.com), সস অথবা ডাকযোগে আগামী ২৮ নভেঘর ২০২৩ তারিখের বো সেটার রেলে রাওয়া, "
             "ভিআইপি রোড, মহাখালী, ঢাকা বরাবর দরপত্র জমা দেওয়ার আহ্বান করা যাচ্ছে ")
    text = filler + raowa + filler
    priority = ocr_items(text, only_priority=True)
    assert len(priority) == 1 and "raowa.office@gmail.com" in priority[0]["details"]
    everything = ocr_items(text)
    assert any("raowa" in i["details"] for i in everything)
