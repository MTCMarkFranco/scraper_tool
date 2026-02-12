"""
Web App: Scrape Articles from URL
Designed to be used as a Foundry agent tool via Azure Web App.
Accepts a URL, scrapes all article links, visits each, and returns
stripped text content as a JSON array.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, bypassing
Cloudflare and similar anti-bot protections that inspect the TLS
client hello (JA3 fingerprint).
"""

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cffi_requests
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# ── HTML Parsers ─────────────────────────────────────────────────────

class HTMLTextExtractor(HTMLParser):
    """Extracts visible text from HTML, skipping script/style tags."""

    # Only paired (non-void) tags that contain no visible text
    SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._pieces)
        return re.sub(r"\s+", " ", raw).strip()


class LinkExtractor(HTMLParser):
    """Extracts href values from <a> tags that look like article links.

    Only keeps links that:
      • Are on the same domain as the starting page
      • Share the same path prefix (i.e. deeper sub-paths / actual articles)
      • Are not obvious non-article resources (RSS, CDN, pagination, etc.)
    """

    IGNORE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js",
        ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
        ".xml",
    }
    IGNORE_PREFIXES = ("mailto:", "tel:", "javascript:", "#")
    IGNORE_PATH_SEGMENTS = {"rss", "feed", "cdn-cgi", "tag", "category", "page", "author"}

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        parsed = urlparse(base_url)
        self.base_domain = parsed.netloc.lower()
        # Use parent directory as path prefix so articles in sibling paths are included
        # e.g. /media-centre/news-releases/ → /media-centre/
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2:
            self.base_path = "/" + "/".join(path_parts[:-1]) + "/"
        else:
            self.base_path = "/" + "/".join(path_parts) + "/" if path_parts else "/"
        self.links: list[str] = []

    def _is_article_link(self, full_url: str) -> bool:
        parsed = urlparse(full_url)
        # Must be same domain
        if parsed.netloc.lower() != self.base_domain:
            return False
        path = parsed.path.rstrip("/") + "/"
        # Must be under the parent-path prefix
        if not path.startswith(self.base_path) or path == self.base_path:
            return False
        # Must have enough depth to be an article (at least 3 segments)
        segments = [s for s in parsed.path.split("/") if s]
        if len(segments) < 3:
            return False
        # Skip paths that contain known non-article segments
        lower_segments = [s.lower() for s in segments]
        if self.IGNORE_PATH_SEGMENTS & set(lower_segments):
            return False
        return True

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        if any(href.startswith(p) for p in self.IGNORE_PREFIXES):
            return
        full = urljoin(self.base_url, href)
        parsed = urlparse(full)
        if any(parsed.path.lower().endswith(ext) for ext in self.IGNORE_EXTENSIONS):
            return
        # Strip fragment (#storyline etc.) to avoid duplicates
        full = full.split("#")[0]
        if parsed.scheme in ("http", "https") and self._is_article_link(full) and full not in self.links:
            self.links.append(full)


# ── Helpers ──────────────────────────────────────────────────────────


def _new_session():
    """Create a fresh session with Chrome TLS fingerprint impersonation."""
    return cffi_requests.Session(impersonate="chrome")


def fetch_html(url: str, session=None) -> str:
    """Fetch a page impersonating Chrome's TLS fingerprint."""
    if session is None:
        session = _new_session()
    resp = session.get(url, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def extract_text(html: str) -> str:
    extractor = HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def extract_links(html: str, base_url: str) -> list[str]:
    parser = LinkExtractor(base_url)
    parser.feed(html)
    return parser.links


def scrape_articles(url: str, debug: bool = False) -> list[dict]:
    # Reuse one session so Cloudflare cookies from the index page carry over
    session = _new_session()
    index_html = fetch_html(url, session=session)
    article_links = extract_links(index_html, url)

    if debug:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2:
            base_path = "/" + "/".join(path_parts[:-1]) + "/"
        else:
            base_path = "/" + "/".join(path_parts) + "/" if path_parts else "/"
        raw_parser = LinkExtractor(url)
        raw_parser.base_path = "/"
        raw_parser.feed(index_html)
        return [{
            "debug": True,
            "html_length": len(index_html),
            "base_path_used": base_path,
            "filtered_article_links": article_links,
            "all_same_domain_links": raw_parser.links,
        }]

    results: list[dict] = []
    logging.info(f"Found {len(article_links)} article links to scrape")
    for i, link in enumerate(article_links):
        try:
            page_html = fetch_html(link, session=session)
            content = extract_text(page_html)
            if content:
                results.append({"url": link, "content": content})
        except Exception as exc:
            logging.warning(f"Failed [{i+1}]: {type(exc).__name__}: {exc}")
            results.append({"url": link, "error": str(exc)})

    return results


# ── Flask endpoints ──────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "screenscrapehub"})


@app.route("/api/scrape", methods=["GET", "POST"])
def scrape():
    """
    HTTP endpoint for article scraping.

    GET:  /api/scrape?url=https://example.com/blog
    POST: /api/scrape  body: {"url": "https://example.com/blog"}
    """
    logging.info("scrape endpoint triggered")

    url = flask_request.args.get("url")
    if not url and flask_request.is_json:
        url = flask_request.get_json(silent=True, force=True).get("url")

    if not url:
        return jsonify({"error": "Missing required parameter: url"}), 400

    try:
        debug = flask_request.args.get("debug", "").lower() in ("1", "true")
        results = scrape_articles(url, debug=debug)
        return jsonify(results), 200
    except Exception as exc:
        logging.error(f"Scrape failed: {exc}")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
