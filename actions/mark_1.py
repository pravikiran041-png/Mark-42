import asyncio
import json
import os
from datetime import datetime
from duckduckgo_search import DDGS
from actions.deep_scraper import scrape_url
from core.ai_router import call_ai
from pathlib import Path
import sys

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

async def mark_1_research(topic: str, speak_callback=None) -> str:
    """The Mark-1 Deep Research Agent entry point."""
    print(f"[Mark-1] Initiating deep research protocol for: {topic}")
    
    if speak_callback:
        speak_callback(f"Deploying Mark-1 Sir. Analyzing {topic}. Estimated time: 15 to 30 seconds. Stand by.")
    
    # Setup background status updates
    async def status_updates():
        messages = [
            "Mark-1 scanning deep sources Sir...",
            "Cross-referencing scraped data Sir...",
            "Synthesizing final intelligence dossier Sir..."
        ]
        try:
            for msg in messages:
                await asyncio.sleep(8)
                if speak_callback:
                    speak_callback(msg)
        except asyncio.CancelledError:
            pass

    update_task = asyncio.create_task(status_updates())
    
    # 1. Planning Phase
    plan_prompt = f"""You are Mark-1, a God-tier deep research agent.
The user wants to deeply research this topic: "{topic}"
Generate 3 to 5 highly specific search queries to uncover all angles of this topic.
CRITICAL: If the user is asking about a specific social media account or website, one of your items MUST be the direct URL to that profile (e.g., "https://www.instagram.com/username/" or "https://twitter.com/username").
Respond ONLY with a JSON list of strings. The strings can be search queries OR direct URLs. Example: ["https://www.instagram.com/target_user/", "target_user recent news"]"""
    
    raw_text = call_ai(plan_prompt, system="You are a JSON query generator.", max_tokens=200)
    try:
        raw_text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        queries = json.loads(raw_text)
    except Exception as e:
        print(f"[Mark-1] Planner failed or API returned non-JSON: {e}")
        queries = [topic] # Fallback
        
    print(f"[Mark-1] Planned queries: {queries}")
    
    # 2. Gathering Phase (Search & Scrape)
    all_urls = []
    ddg_queries = []
    
    for q in queries:
        if q.startswith("http://") or q.startswith("https://"):
            if q not in all_urls:
                all_urls.append(q)
        else:
            ddg_queries.append(q)
            
    if ddg_queries:
        with DDGS() as ddgs:
            for q in ddg_queries:
                try:
                    results = list(ddgs.text(q, max_results=3))
                    for r in results:
                        if r.get('href') not in all_urls:
                            all_urls.append(r.get('href'))
                except Exception as e:
                    print(f"[Mark-1] DDG search failed for {q}: {e}")
                
    # Limit to top 5 URLs to avoid overloading
    all_urls = all_urls[:5]
    print(f"[Mark-1] Scraping {len(all_urls)} targets: {all_urls}")
        
    scrape_tasks = [scrape_url(url) for url in all_urls]
    scraped_data = await asyncio.gather(*scrape_tasks)
    
    # Filter successful scrapes and compile raw context
    raw_context = ""
    total_images = []
    
    # Gather Images via DDG
    with DDGS() as ddgs:
        try:
            img_results = list(ddgs.images(topic, max_results=5, type_image="photo", size="Medium"))
            for r in img_results:
                if 'image' in r:
                    total_images.append(r['image'])
        except Exception as e:
            print(f"[Mark-1] DDG image search failed: {e}")
            
    # CRITICAL FALLBACK: Always append a generated high-quality image URL 
    # so the LLM has at least one guaranteed image if web search fails.
    safe_topic_url = topic.replace(" ", "+")
    total_images.append(f"https://image.pollinations.ai/prompt/{safe_topic_url}?width=1280&height=720&nologo=true")
            
    sources_consulted = []
    for data in scraped_data:
        if data.get('success'):
            url = data['url']
            text = data['text'][:4000] # Cap per source
            images = data.get('images', [])
            total_images.extend(images)
            raw_context += f"--- SOURCE: {url} ---\n{text}\n\n"
            sources_consulted.append(url)
            
    print(f"[Mark-1] Gathered {len(raw_context)} characters of context and {len(total_images)} images.")
    
    # 3. Synthesis Phase
    synthesis_prompt = f"""You are Mark-1, an advanced God-tier intelligence agent analyzing raw scraped data.
Topic: {topic}

Here is the raw data scraped from the web (including news, social media, and deep web sources):
{raw_context}

Available Image URLs to project as holograms:
{', '.join(total_images[:10])}

YOUR DIRECTIVES:
1. Synthesize the findings into a concise, punchy, conversational briefing. Do NOT write a long academic essay or use filler words. Speak like Tony Stark's JARVIS giving a quick, high-level intelligence update. Keep the entire speech under 200 words.
2. Cross-reference the data to find the absolute truth and state it confidently.
3. Adopt a highly professional, calculated, "God-tier" AI persona.
5. CRITICAL: At the very end of your speech, you MUST explicitly list the sources consulted. Start with "Sources consulted Sir:" followed by a numbered list of domains.

Write the final speech that JARVIS will read aloud to the user. Do not use asterisks or markdown formatting, as this will be read by a Text-To-Speech engine."""

    final_report = call_ai(synthesis_prompt, system="You are Mark-1. Answer in the requested format only.", max_tokens=3000)

    # GUARANTEED HOLOGRAM INJECTION
    if total_images and "[IMG:" not in final_report:
        final_report = f"[IMG: {total_images[0]}]\n\n" + final_report

    # Cancel the progress updates
    update_task.cancel()
    
    # Save to disk
    base_dir = _get_base_dir()
    research_dir = base_dir / "memory" / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_topic = "".join([c if c.isalnum() else "_" for c in topic[:20]])
    filename = f"{date_str}_{safe_topic}.md"
    file_path = research_dir / filename
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"# Mark-1 Research Dossier: {topic}\n\n")
        f.write(final_report)
        
    print(f"[Mark-1] Report saved to {file_path}")
    return final_report

# Wrapper for synchronous tool calling in main.py
def mark_1_tool(topic: str, speak_callback=None) -> str:
    """Run the Mark-1 research agent (synchronous wrapper for the LLM tool)."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(mark_1_research(topic, speak_callback))
