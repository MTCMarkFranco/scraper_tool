# Foundry Hosted Agent — Screen Scrape Hub

A Flask web API that scrapes article links from a given URL, visits each page, strips HTML, and returns plain-text content as JSON. Uses **curl_cffi** to impersonate Chrome's TLS fingerprint, bypassing Cloudflare and similar anti-bot protections.

Deployed as an **Azure Web App** and designed for use as a Foundry agent tool.

## API

### `POST /api/scrape`

Scrape all article links from a page and return their text content.

**Request body:**
```json
{ "url": "https://example.com/blog" }
```

**Response:** JSON array of objects with `url` and `content` (or `error`) fields.

A `GET` variant is also supported: `/api/scrape?url=https://example.com/blog`

See [openapi.json](openapi.json) for the full OpenAPI 3.0 specification.

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

The server starts on `http://localhost:8000`.

## Deployment

The app runs on Azure Web App with Gunicorn via [startup.sh](startup.sh):

```bash
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 app:app
```

## Dependencies

- **Flask** — HTTP framework
- **gunicorn** — WSGI server
- **curl_cffi** — HTTP client with Chrome TLS fingerprint impersonation
