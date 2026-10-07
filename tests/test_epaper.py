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
