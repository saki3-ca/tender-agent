import json
import pytest
from unittest.mock import AsyncMock, patch

import httpx
from app.crawler.epaper.bangladeshtoday import BangladeshTodayEpaperCrawler
from app.crawler.epaper.bdpratidin import BdPratidinEpaperCrawler
from app.crawler.epaper.dhakatribune import DhakaTribuneEpaperCrawler
from app.crawler.epaper.financialexpress import FinancialExpressEpaperCrawler
from app.crawler.epaper.jugantor import JugantorEpaperCrawler
from app.crawler.epaper.prothomalo import ProthomAloEpaperCrawler
from app.crawler.epaper.protidinerbangladesh import ProtidinerBangladeshEpaperCrawler
from app.parsers.epaper_gemini import GeminiEpaperParser


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
async def test_jugantor_crawler():
    crawler = JugantorEpaperCrawler()
    assert crawler is not None


@pytest.mark.asyncio
async def test_bd_pratidin_crawler():
    crawler = BdPratidinEpaperCrawler()
    assert crawler is not None
