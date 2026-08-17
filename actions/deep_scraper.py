import asyncio
from bs4 import BeautifulSoup
import requests
from playwright.async_api import async_playwright
import re

def scrape_static(url: str) -> dict:
    """Fast scrape using requests for static sites."""
    try:
        headers = {'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove junk
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.extract()
            
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        
        # Extract images from img tags
        images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src and src.startswith('http'):
                images.append(src)
                
        # Also extract og:image (crucial for Instagram profile pics)
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            # Prepend so it gets highest priority as the main image
            # Replace html entities if any
            content = og_img.get('content').replace('&amp;', '&')
            images.insert(0, content)
                
        return {
            "success": True,
            "url": url,
            "text": text[:20000], # Limit text length to prevent context explosion
            "images": images[:10],
            "method": "static"
        }
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


async def scrape_dynamic(url: str) -> dict:
    """Deep scrape using Playwright for JS-heavy sites (Instagram, X, etc)."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            page = await context.new_page()
            
            # Navigate and wait for network idle
            await page.goto(url, timeout=30000, wait_until='networkidle')
            
            # Wait a bit extra for dynamic content
            await page.wait_for_timeout(3000)
            
            # Get text
            text = await page.evaluate("() => document.body.innerText")
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Get images
            images = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('img')).map(img => img.src).filter(src => src.startsWith('http'));
            }""")
            
            await browser.close()
            
            return {
                "success": True,
                "url": url,
                "text": text[:20000],
                "images": list(set(images))[:10],
                "method": "dynamic"
            }
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}

async def scrape_url(url: str) -> dict:
    """Intelligently scrapes a URL, falling back to dynamic if needed."""
    # Instagram/Twitter direct scraping using Googlebot static
    if "instagram.com/" in url.lower() or "twitter.com/" in url.lower() or "x.com/" in url.lower():
        print(f"[DeepScraper] Using Googlebot static scraper for {url}")
        return scrape_static(url)
    
    dynamic_domains = ['tiktok.com', 'facebook.com']
    
    needs_dynamic = any(domain in url.lower() for domain in dynamic_domains)
    
    if needs_dynamic:
        print(f"[DeepScraper] Using dynamic scraper for {url}")
        return await scrape_dynamic(url)
    
    print(f"[DeepScraper] Using static scraper for {url}")
    res = scrape_static(url)
    if not res['success'] or len(res.get('text', '')) < 200:
        print(f"[DeepScraper] Static failed or returned little text. Retrying with dynamic scraper...")
        return await scrape_dynamic(url)
        
    return res

if __name__ == "__main__":
    # Test script
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    res = asyncio.run(scrape_url(test_url))
    print(res)
