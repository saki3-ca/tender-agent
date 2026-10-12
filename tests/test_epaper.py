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


# ---------------------------------------------------------------- Gemini keys and quota handling
def _gemini_ok(text="[]"):
    return httpx.Response(status_code=200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
                          request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"))


def _gemini_429(quota_id, retry="30s"):
    body = {"error": {"code": 429, "message": "Resource exhausted", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry}]}}
    return httpx.Response(status_code=429, json=body, request=httpx.Request("POST", "https://generativelanguage.googleapis.com/"))


@pytest.fixture
def clean_gemini_state():
    from app.parsers import epaper_gemini as g
    g._UNUSABLE.clear(); g._COOLDOWN.clear(); g._USAGE.clear()
    yield g
    g._UNUSABLE.clear(); g._COOLDOWN.clear(); g._USAGE.clear()


def test_quota_kind_tells_per_minute_from_per_day(clean_gemini_state):
    g = clean_gemini_state
    assert g.quota_kind(_gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "23s")) == ("minute", 23.0)
    assert g.quota_kind(_gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))[0] == "day"
    # both exceeded: the daily one decides
    both = _gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
    body = both.json(); body["error"]["details"][0]["violations"].append({"quotaId": "GenerateRequestsPerDayPerProjectPerModel"})
    assert g.quota_kind(httpx.Response(429, json=body))[0] == "day"
    # nothing says "minute": same as before, treated as the daily quota
    assert g.quota_kind(httpx.Response(429, text="quota exceeded"))[0] == "day"


@pytest.mark.asyncio
async def test_per_minute_limit_waits_and_retries_instead_of_giving_up(clean_gemini_state):
    g = clean_gemini_state
    replies = [_gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "5s")] * len(GEMINI_MODELS) + [_gemini_ok('[{"title": "t"}]')]
    clock = [1000.0]
    waits = []

    async def fake_sleep(seconds):          # time only passes when the code sleeps
        waits.append(seconds)
        clock[0] += seconds

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as post, \
            patch("app.parsers.epaper_gemini.asyncio.sleep", fake_sleep), \
            patch("app.parsers.epaper_gemini.time.monotonic", lambda: clock[0]):
        post.side_effect = replies
        parser = GeminiEpaperParser(api_keys=["k1"])
        items = await parser.extract_tenders_from_image(b"img")
    assert items == [{"title": "t"}] and (parser.pages_read, parser.pages_failed) == (1, 0)
    assert not g._UNUSABLE                      # nothing was written off for the day
    assert max(waits) >= 5                      # it really waited for the limit to pass


@pytest.mark.asyncio
async def test_daily_quota_of_one_key_moves_on_to_the_next_key(clean_gemini_state):
    g = clean_gemini_state
    seen_keys = []

    async def fake_post(self, url, json=None, headers=None):  # noqa: A002
        seen_keys.append(headers["x-goog-api-key"])
        return _gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier") if headers["x-goog-api-key"] == "k1" else _gemini_ok()

    with patch.object(httpx.AsyncClient, "post", fake_post), patch("app.parsers.epaper_gemini.asyncio.sleep", new_callable=AsyncMock):
        parser = GeminiEpaperParser(api_keys=["k1", "k2"])
        for _ in range(3):
            assert await parser.extract_tenders_from_image(b"img") == []
    assert parser.pages_read == 3 and parser.pages_failed == 0
    assert all((("k1", m) in g._UNUSABLE) for m in GEMINI_MODELS if ("k1", m) in g._UNUSABLE)
    assert g._USAGE["k2"] == 3


@pytest.mark.asyncio
async def test_pages_start_on_different_keys(clean_gemini_state):
    first = []

    async def fake_post(self, url, json=None, headers=None):  # noqa: A002
        first.append(headers["x-goog-api-key"])
        return _gemini_ok()

    with patch.object(httpx.AsyncClient, "post", fake_post), patch("app.parsers.epaper_gemini.asyncio.sleep", new_callable=AsyncMock):
        parser = GeminiEpaperParser(api_keys=["a", "b", "c"])
        for _ in range(6):
            await parser.extract_tenders_from_image(b"img")
    assert sorted(set(first)) == ["a", "b", "c"] and all(first.count(k) == 2 for k in "abc")


def test_gemini_keys_from_one_secret_and_the_old_ones(monkeypatch):
    from app.utils.config import config
    monkeypatch.setenv("GEMINI_API_KEYS", "AIza-1,AIza-2\nAIza-3 ; AIza-4\r\n")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-2")            # duplicate is ignored
    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "AIza-5")
    assert config.gemini_api_keys == ["AIza-1", "AIza-2", "AIza-3", "AIza-4", "AIza-5"]
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"):
        monkeypatch.delenv(name)
    assert config.gemini_api_keys == []


def test_usage_summary_line(clean_gemini_state):
    g = clean_gemini_state
    g._USAGE["a"] = 12; g._USAGE["b"] = 3
    g._UNUSABLE.update({("a", GEMINI_MODELS[0]), ("a", GEMINI_MODELS[1])})
    line = g.usage_summary(["a", "b", "c"])
    assert "15 pages read" in line and "2 of 3 keys used" in line and f"2 of {3 * len(GEMINI_MODELS)} key/model pairs" in line
