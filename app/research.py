"""Link inspection, content scraping, and web search retrieval for zero-hallucination grounding."""

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def extract_urls(text: str) -> list[str]:
    """Extract all unique HTTP/HTTPS URLs from the input text."""
    if not text:
        return []
    raw_urls = re.findall(r"https?://[^\s<>\"'()]+", text)
    cleaned = []
    for u in raw_urls:
        u = u.rstrip(".,;!?:)")
        if u not in cleaned:
            cleaned.append(u)
    return cleaned


def scrape_url(url: str, timeout: float = 8.0, max_chars: int = 3500) -> dict:
    """Fetch and scrape clean text content from a given link."""
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        # Remove unwanted script, style, navigation, footer elements
        for element in soup(
            ["script", "style", "nav", "footer", "header", "noscript", "aside", "svg"]
        ):
            element.decompose()

        title = soup.title.get_text(strip=True) if soup.title else urlparse(url).netloc
        paragraphs = [
            p.get_text(strip=True) for p in soup.find_all(["p", "h1", "h2", "h3", "li"])
        ]
        clean_text = " ".join(p for p in paragraphs if p and len(p) > 20)
        if not clean_text:
            clean_text = soup.get_text(separator=" ", strip=True)

        truncated = clean_text[:max_chars].strip()
        if len(clean_text) > max_chars:
            truncated += "..."

        return {
            "url": url,
            "title": title or url,
            "text": truncated,
            "status": "success",
            "chars": len(truncated),
        }
    except Exception as exc:
        return {
            "url": url,
            "title": url,
            "text": f"Could not retrieve content: {exc}",
            "status": "failed",
            "chars": 0,
        }


def search_web(query: str, max_results: int = 3, timeout: float = 8.0) -> list[dict]:
    """Perform a web search via DuckDuckGo HTML and return top result titles, snippets, and URLs."""
    if not query or not query.strip():
        return []
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query.strip()})
            if resp.status_code != 200:
                return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        titles = soup.select(".result__title a")
        snippets = soup.select(".result__snippet")

        for idx, title_elem in enumerate(titles[:max_results]):
            title = title_elem.get_text(strip=True)
            href = title_elem.get("href", "")
            # DuckDuckGo wraps links in uddg redirect
            if "uddg=" in href:
                from urllib.parse import parse_qs

                parsed = parse_qs(urlparse(href).query)
                link = parsed.get("uddg", [href])[0]
            else:
                link = href
            snippet = snippets[idx].get_text(strip=True) if idx < len(snippets) else ""
            if title and link:
                results.append({"title": title, "url": link, "snippet": snippet})
        return results
    except Exception:
        return []


def assemble_context(
    source_brief: str,
    project_name: str | None = None,
    past_milestones: list[dict] | None = None,
    past_posts: list[dict] | None = None,
    given_links_content: list[dict] | None = None,
    web_search_results: list[dict] | None = None,
) -> tuple[str, dict]:
    """
    Assemble the complete grounding context document incorporating:
    - User source brief
    - Project memory (past milestones & prior updates)
    - Given links scraped content
    - Web search results
    Returns (context_text, sources_metadata).
    """
    sections = []
    sources_meta = {
        "source_brief": source_brief,
        "project_name": project_name,
        "past_milestones": past_milestones or [],
        "past_posts": past_posts or [],
        "given_links": given_links_content or [],
        "web_search": web_search_results or [],
    }

    # 1. Project Memory & Continuity
    if project_name or past_milestones or past_posts:
        proj_lines = [f"PROJECT MEMORY & CONTINUITY CONTEXT: {project_name or 'Ongoing Research'}"]
        if past_milestones:
            proj_lines.append("Prior Milestones & Achievements Achieved to Date:")
            for m in past_milestones:
                date_str = m.get("date", "")
                title = m.get("title") or m.get("summary", "")
                proj_lines.append(f"- [{date_str}] {title}")
        if past_posts:
            proj_lines.append("Recent Weekly Updates in this Series:")
            for idx, p in enumerate(past_posts[-3:], 1):
                created = p.get("created_at", "")
                snippet = p.get("source", "")[:200].replace("\n", " ")
                proj_lines.append(f"Update #{idx} ({created}): {snippet}...")
        sections.append("\n".join(proj_lines))

    # 2. Current Source Brief
    sections.append(f"CURRENT SOURCE UPDATE (THIS WEEK'S NEW FACTS):\n{source_brief}")

    # 3. Given Links Content
    if given_links_content:
        link_lines = ["GROUND TRUTH FROM INSPECTED LINKS (GIVEN URLS):"]
        for idx, link in enumerate(given_links_content, 1):
            if link.get("status") == "success" and link.get("text"):
                link_lines.append(
                    f"[Link {idx}: {link['title']}] ({link['url']})\n"
                    f"Extracted Content: {link['text']}\n"
                )
        if len(link_lines) > 1:
            sections.append("\n".join(link_lines))

    # 4. Web Search Findings
    if web_search_results:
        search_lines = ["FACTUAL FINDINGS FROM WEB SEARCH:"]
        for idx, res in enumerate(web_search_results, 1):
            search_lines.append(
                f"[Search Result {idx}: {res['title']}] ({res['url']})\n"
                f"Snippet: {res['snippet']}\n"
            )
        sections.append("\n".join(search_lines))

    full_context_text = "\n\n====================\n\n".join(sections)
    return full_context_text, sources_meta
