import os
import tempfile
import urllib.request
import urllib.parse
import json
import re
from typing import Optional

def _get_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

def _download_to_temp(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers=_get_headers())
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read()
        if not data:
            return None
        fd, path = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        return path
    except Exception as e:
        print(f"[ImageSearch] Download failed for {url}: {e}")
        return None

def fetch_image_temp(query: str = "", url: str = "") -> Optional[str]:
    """
    Fetches an image based on the URL (og:image) or query (DDGS), saves to a temp file.
    The caller is responsible for deleting the file.
    """
    # 1. Try News Article Thumbnail (og:image) or Direct Image
    if url:
        try:
            req = urllib.request.Request(url, headers=_get_headers())
            with urllib.request.urlopen(req, timeout=5) as response:
                content_type = response.headers.get('Content-Type', '')
                
                # If it's already an image, just download it directly!
                if 'image' in content_type:
                    data = response.read()
                    import tempfile, os
                    fd, path = tempfile.mkstemp(suffix=".jpg")
                    with os.fdopen(fd, 'wb') as f:
                        f.write(data)
                    return path
                
                # Otherwise, it's a webpage, so scrape for og:image
                html = response.read().decode('utf-8', errors='ignore')
            
            match = re.search(r'<meta\s+(?:property|name)=[\'"]og:image[\'"]\s+content=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
            if not match:
                match = re.search(r'content=[\'"]([^\'"]+)[\'"]\s+property=[\'"]og:image[\'"]', html, re.IGNORECASE)
            
            if match:
                img_url = match.group(1)
                # handle relative URLs
                if img_url.startswith('/'):
                    from urllib.parse import urljoin
                    img_url = urljoin(url, img_url)
                
                path = _download_to_temp(img_url)
                if path:
                    print(f"[ImageSearch] Extracted og:image from {url}")
                    return path
        except Exception as e:
            print(f"[ImageSearch] Failed to extract from URL {url}: {e}")

    # 2. Try DuckDuckGo Images Fallback
    if query:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            try:
                from ddgs import DDGS
            except ImportError:
                return None

        try:
            img_url = None
            with DDGS() as ddgs:
                for r in ddgs.images(query, max_results=3):
                    if r.get("image"):
                        img_url = r["image"]
                        break
            
            if img_url:
                path = _download_to_temp(img_url)
                if path:
                    print(f"[ImageSearch] Fallback DDGS used for '{query}'")
                    return path
        except Exception as e:
            print(f"[ImageSearch] ⚠️ DDGS fallback failed: {e}")

    # 3. Try Wikipedia Fallback
    if query:
        try:
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&utf8=&format=json&srlimit=1"
            req = urllib.request.Request(search_url, headers=_get_headers())
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode())
            
            if data.get('query', {}).get('search'):
                title = data['query']['search'][0]['title']
                img_api_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=pageimages&format=json&piprop=original&titles={urllib.parse.quote(title)}"
                req = urllib.request.Request(img_api_url, headers=_get_headers())
                with urllib.request.urlopen(req, timeout=3) as response:
                    img_data = json.loads(response.read().decode())
                    
                pages = img_data.get('query', {}).get('pages', {})
                for page_id, page_info in pages.items():
                    if 'original' in page_info and 'source' in page_info['original']:
                        print(f"[ImageSearch] Fallback Wikipedia used for '{query}'")
                        return _download_to_temp(page_info['original']['source'])
        except Exception as e:
            print(f"[ImageSearch] Wikipedia fallback failed: {e}")

    return None
