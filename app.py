
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote, quote
from urllib.request import Request, urlopen

ARCHIVE = "https://archive.org"

MANIFEST = {
    "id": "pt.ruben.liveconcerts",
    "version": "1.1.0",
    "name": "Live Music Concerts",
    "description": "Pesquisa concertos, DVDs musicais e gravações ao vivo.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "catalogs": [{
        "type": "movie",
        "id": "liveconcerts",
        "name": "Concertos ao Vivo",
        "extra": [{"name": "search", "isRequired": False}]
    }]
}

def fetch_json(url):
    req = Request(url, headers={"User-Agent": "LiveMusicAddon/1.1"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def archive_search(term):
    phrase = " ".join(term.strip().split()).replace('"', "")

    if not phrase:
        return []

    query = f'title:"{phrase}" AND mediatype:movies'

    url = (
        ARCHIVE + "/advancedsearch.php?q=" + quote(query)
        + "&fl[]=identifier&fl[]=title&fl[]=year"
        + "&fl[]=description&rows=100&page=1&output=json"
    )

    results = fetch_json(url)["response"]["docs"]

    # Só apresentar títulos que contenham a pesquisa completa
    filtered = []
    for item in results:
        title = str(item.get("title", ""))
        if phrase.casefold() in title.casefold():
            filtered.append(item)

    return filtered


def make_meta(item):
    identifier = item.get("identifier")
    if not identifier:
        return None

    title = item.get("title", identifier)
    year = item.get("year", "")
    description = item.get("description", "")

    if isinstance(description, list):
        description = " ".join(str(x) for x in description[:3])

    return {
        "id": identifier,
        "type": "movie",
        "name": str(title),
        "description": str(description)[:1000],
        "poster": ARCHIVE + "/services/img/" + quote(identifier, safe=""),
        "background": ARCHIVE + "/services/img/" + quote(identifier, safe=""),
        "releaseInfo": str(year) if year else ""
    }

class Handler(BaseHTTPRequestHandler):

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = path.strip("/").split("/")

        if path == "/manifest.json":
            return self.send_json(MANIFEST)

        if len(parts) >= 3 and parts[0] == "catalog":
            term = parse_qs(parsed.query).get("search", [""])[0]

            for part in parts[3:]:
                if part.startswith("search="):
                    term = part[7:].removesuffix(".json")

            if not term:
                term = "live concert"

            try:
                docs = archive_search(term)
                metas = []
                for doc in docs:
                    meta = make_meta(doc)
                    if meta:
                        metas.append(meta)
                return self.send_json({"metas": metas})
            except Exception:
                return self.send_json({"metas": []})

        if len(parts) >= 3 and parts[0] == "meta":
            identifier = parts[2].removesuffix(".json")
            try:
                data = get_item(identifier)
                metadata = data.get("metadata", {})
                item = {
                    "identifier": identifier,
                    "title": metadata.get("title", identifier),
                    "year": metadata.get("year", ""),
                    "description": metadata.get("description", "")
                }
                meta = make_meta(item)
                return self.send_json({"meta": meta})
            except Exception:
                return self.send_json({"meta": None})

        if len(parts) >= 3 and parts[0] == "stream":
            identifier = parts[2].removesuffix(".json")
            try:
                data = get_item(identifier)
                streams = []

                for file in data.get("files", []):
                    filename = file.get("name", "")
                    lower = filename.lower()

                    if not lower.endswith((".mp4", ".mkv", ".webm", ".mov")):
                        continue

                    if file.get("private") in (True, "true", 1):
                        continue

                    link = (
                        ARCHIVE + "/download/"
                        + quote(identifier, safe="") + "/"
                        + quote(filename, safe="/")
                    )

                    size = file.get("size", "")
                    title = filename
                    if size:
                        try:
                            title += " | " + str(round(int(size) / 1048576)) + " MB"
                        except (ValueError, TypeError):
                            pass

                    streams.append({
                        "name": "Internet Archive",
                        "title": title,
                        "url": link
                    })

                return self.send_json({"streams": streams})
            except Exception:
                return self.send_json({"streams": []})

        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass

port = int(os.environ.get("PORT", 10000))
server = HTTPServer(("0.0.0.0", port), Handler)
server.serve_forever()
