"""
Cloudflare bypass helper using Selenium + undetected-chromedriver.
Returns HTML content for sites protected by Cloudflare bot challenges.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("cloudflare_bypass")

try:
    import undetected_chromedriver as uc
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logger.warning("undetected_chromedriver not installed; Cloudflare bypass will not work")


async def fetch_with_selenium(url: str, timeout: int = 30) -> Optional[str]:
    """
    Fetch a URL using Selenium + undetected-chromedriver to bypass Cloudflare.
    Returns HTML content or None if failed or Selenium not available.
    """
    if not SELENIUM_AVAILABLE:
        logger.error("Selenium not available; cannot bypass Cloudflare")
        return None

    try:
        # Run Selenium in thread pool since it's blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _selenium_fetch, url, timeout)
    except Exception as e:
        logger.error(f"Selenium fetch failed for {url}: {e}")
        return None


def _selenium_fetch(url: str, timeout: int) -> Optional[str]:
    """Blocking Selenium fetch (runs in thread pool)."""
    if not SELENIUM_AVAILABLE:
        return None

    driver = None
    try:
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-extensions")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        driver = uc.Chrome(options=options, version_main=None)
        driver.set_page_load_timeout(timeout)
        driver.get(url)

        # Wait for Cloudflare challenge to complete
        import time
        time.sleep(3)

        html = driver.page_source
        return html if html else None

    except Exception as e:
        logger.error(f"Selenium error fetching {url}: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


async def fetch_image_with_selenium(url: str, timeout: int = 30) -> Optional[bytes]:
    """
    Fetch an image URL using Selenium to bypass Cloudflare.
    Returns image bytes or None if failed or Selenium not available.
    """
    if not SELENIUM_AVAILABLE:
        logger.error("Selenium not available; cannot bypass Cloudflare for images")
        return None

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _selenium_fetch_binary, url, timeout)
    except Exception as e:
        logger.error(f"Selenium image fetch failed for {url}: {e}")
        return None


def _selenium_fetch_binary(url: str, timeout: int) -> Optional[bytes]:
    """Blocking Selenium binary fetch (runs in thread pool)."""
    if not SELENIUM_AVAILABLE:
        return None

    driver = None
    try:
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--start-maximized")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        driver = uc.Chrome(options=options, version_main=None)
        driver.set_page_load_timeout(timeout)

        # Use JavaScript to fetch binary data
        driver.get("about:blank")
        script = f"""
        return fetch('{url}')
            .then(r => r.arrayBuffer())
            .then(buf => new Uint8Array(buf))
            .then(arr => Array.from(arr))
        """
        data = driver.execute_script(script)
        if data:
            return bytes(data)
        return None

    except Exception as e:
        logger.error(f"Selenium binary fetch error for {url}: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
