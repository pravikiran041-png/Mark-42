"""
Web tools — fetch global news briefings via RSS.
"""

import urllib.request
import xml.etree.ElementTree as ET
import concurrent.futures
import re

SEED_FEEDS = [
    'https://feeds.bbci.co.uk/news/world/rss.xml',
    'https://www.cnbc.com/id/100727362/device/rss/rss.html',
    'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'https://www.aljazeera.com/xml/rss/all.xml'
]

def fetch_and_parse_feed(url):
    """Helper function to handle a single feed request and parse its XML."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mark-L/1.0'})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            content = response.read()

        root = ET.fromstring(content)
        # Extract source name from URL (e.g., 'bbci', 'nytimes', 'cnbc', 'aljazeera')
        source_name = url.split('.')[1].upper()
        if source_name == 'BBCI': source_name = 'BBC'
        
        feed_items = []
        # Get top 5 items per feed
        items = root.findall(".//item")[:5]
        for item in items:
            title = item.findtext("title")
            description = item.findtext("description")
            link = item.findtext("link")
            
            if description:
                description = re.sub('<[^<]+?>', '', description).strip()

            feed_items.append({
                "source": source_name,
                "title": title,
                "summary": description[:200] + "..." if description else "",
                "link": link
            })
        return feed_items
    except Exception as e:
        print(f"[News] Failed to fetch {url}: {e}")
        return []

def get_world_news(parameters: dict = None, player=None) -> str:
    """
    Fetches the latest global headlines from major news outlets simultaneously.
    """
    print("[News] Fetching live world news...")
    
    # Fire them all at once and wait for the results
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results_of_lists = list(executor.map(fetch_and_parse_feed, SEED_FEEDS))
        
    # Flatten the list of lists into a single list of articles
    all_articles = [item for sublist in results_of_lists for item in sublist]

    if not all_articles:
        return "The global news grid is unresponsive, sir. I'm unable to pull headlines."

    # Format the final briefing
    report = ["### GLOBAL NEWS BRIEFING (LIVE)\n"]
    # Limit to top 12 items so the AI doesn't get overwhelmed
    for entry in all_articles[:12]:
        report.append(f"**[{entry['source']}]** {entry['title']}")
        report.append(f"{entry['summary']}")
        report.append(f"Link: {entry['link']}\n")

    return "\n".join(report)
