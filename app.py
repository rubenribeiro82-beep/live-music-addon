
import json
import os
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", 10000))
ADDON_ID = "pt.liveconcerts.nuvio"
BASE_URL = os.environ.get(
    "BASE_URL",
    "https://live-concerts-new.onrender.com"
).rstrip("/")

MANIFEST = {
    "id": ADDON_ID,
    "version": "1.0.0",
    "name": "Live Concerts",
    "description": "Pesquisa de concertos completos e atuações ao vivo.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "idPrefixes": ["archive:"],
    "catalogs": [
        {
            "type": "movie",
            "id": "liveconcerts",
            "name": "Concertos ao Vivo",
            "extra": [
                {"name": "search", "isRequired": False}
            ]
        }
    ],
    "behaviorHints": {
        "adult": False,
        "configurable": False
    }
}

HEADERS = {
    "User-Agent": "LiveConcertsAddon/1.0"
}

def fetch_json(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def search_archive(query):
    params = {
        "q": (
            'mediatype:movies AND '
            '(subject:concert OR subject:music OR subject:live)'
        ),
        "fl[]": ["identifier", "title", "year", "description"],
        "rows": "100",
        "page": "1",
        "output": "json",
        "sort[]": "downloads desc"
    }

    if query:
        params["q"] += " AND " + query

    url = (
        "https://archive.org/advancedsearch.php?"
        + urllib.parse.urlencode(params, doseq=True)
    )

    data = fetch_json(url)
    return data.get("response", {}).get("docs", [])

def make_meta(item):
    identifier = item.get("identifier")
    title = item.get("title", identifier)

    return {
        "id": "archive:" + identifier,
        "type": "movie",
        "name": title,
        "description": item.get("description", ""),
        "year": item.get("year"),
        "poster": "https://archive.org/services/img/" + identifier,
        "background": "https://archive.org/services/img/" + identifier,
        "genres": ["Live Music", "Concert"]
    }

def get_files(identifier):
    url = (
        "https://archive.org/metadata/"
        + urllib.parse.quote(identifier, safe="")
    )

    data = fetch_json(url)
    files = data.get("files", [])

    allowed = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".mpeg", ".mpg")

    results = []

    for file in files:
        name = file.get("name", "")

        if name.lower().endswith(allowed):
            results.append(file)

    return results

def make_streams(identifier):
    streams = []

    for file in get_files(identifier):
        filename = file.get("name")
        size = file.get("size")

        url = (
            "https://archive.org/download/"
            + urllib.parse.quote(identifier, safe="")
            + "/"
            + urllib.parse.quote(filename, safe="/")
        )

        description = "Internet Archive"

        if size:
            try:
                description += " | " + str(round(int(size) / 1024**3, 2)) + " GB"
            except (ValueError, TypeError):
                pass

        streams.append({
            "name": "Live Concerts",
            "title": filename + "\n" + description,
            "url": url,
            "behaviorHints": {
                "notWebReady": False
            }
        })

    return streams

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
        path = urllib.parse.urlparse(self.path).path

        if path == "/":
            self.send_json({
                "name": "Live Concerts",
                "status": "online",
                "manifest": BASE_URL + "/manifest.json"
            })
            return

        if path == "/manifest.json":
            self.send_json(MANIFEST)
            return

        parts = path.strip("/").split("/")

        if len(parts) >= 3 and parts[0] == "catalog":
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query
            )

            search = query.get("search", [""])[0]

            if not search:
                match = re.search(r"search=(.*)", self.path)
                if match:
                    search = urllib.parse.unquote(match.group(1))

            if search:
                docs = search_archive(
                    'title:"' + search.replace('"', '') + '"'
                )
            else:
                docs = search_archive("")

            metas = [make_meta(item) for item in docs]

            self.send_json({"metas": metas})
            return

        if len(parts) >= 3 and parts[0] == "meta":
            identifier = urllib.parse.unquote(parts[2])

            if identifier.startswith("archive:"):
                identifier = identifier.split(":", 1)[1]

            try:
                data = fetch_json(
                    "https://archive.org/metadata/"
                    + urllib.parse.quote(identifier, safe="")
                )

                metadata = data.get("metadata", {})

                item = {
                    "identifier": identifier,
                    "title": metadata.get("title", identifier),
                    "description": metadata.get("description", ""),
                    "year": metadata.get("year")
                }

                self.send_json({"meta": make_meta(item)})

            except Exception:
                self.send_json({"meta": None})

            return

        if len(parts) >= 3 and parts[0] == "stream":
            identifier = urllib.parse.unquote(parts[2])

            if identifier.startswith("archive:"):
                identifier = identifier.split(":", 1)[1]

            try:
                streams = make_streams(identifier)
                self.send_json({"streams": streams})

            except Exception:
                self.send_json({"streams": []})

            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        print(format % args)

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Live Concerts iniciado na porta", PORT)
    server.serve_forever()
