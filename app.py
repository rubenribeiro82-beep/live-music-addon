
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote, quote, parse_qs
from urllib.request import Request, urlopen

BASE = "https://archive.org"

MANIFEST = {
    "id": "pt.ruben.liveconcerts",
    "version": "1.0.0",
    "name": "Live Music Concerts",
    "description": "Pesquisa concertos e gravações musicais no Internet Archive.",
    "resources": ["catalog", "stream"],
    "types": ["movie"],
    "catalogs": [{
        "type": "movie",
        "id": "liveconcerts",
        "name": "Concertos ao Vivo",
        "extra": [{"name": "search", "isRequired": False}]
    }]
}

def get_json(url):
    req = Request(url, headers={"User-Agent": "LiveMusicAddon/1.0"})
    with urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))

class Handler(BaseHTTPRequestHandler):
    def send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)

        if path == "/manifest.json":
            return self.send_json(MANIFEST)

        if path.startswith("/catalog/movie/liveconcerts"):
            search = parse_qs(urlparse(self.path).query).get("search", [""])[0]

            if not search:
                marker = "/search="
                if marker in path:
                    search = path.split(marker, 1)[1].replace(".json", "")

            if not search:
                search = "live concert"

            query = quote(
                f'title:({search}) AND mediatype:movies'
            )
            url = (
                f"{BASE}/advancedsearch.php?q={query}"
                "&fl[]=identifier&fl[]=title&fl[]=year"
                "&rows=30&page=1&output=json"
            )

            try:
                results = get_json(url)["response"]["docs"]
                metas = []
                for item in results:
                    ident = item.get("identifier")
                    if not ident:
                        continue
                    metas.append({
                        "id": ident,
                        "type": "movie",
                        "name": item.get("title", ident),
                        "description": "Gravação encontrada no Internet Archive"
                    })
                return self.send_json({"metas": metas})
            except Exception:
                return self.send_json({"metas": []})

        if path.startswith("/stream/movie/"):
            ident = path.split("/stream/movie/", 1)[1].replace(".json", "")
            try:
                data = get_json(f"{BASE}/metadata/{quote(ident)}")
                streams = []

                for file in data.get("files", []):
                    name = file.get("name", "")
                    fmt = file.get("format", "").lower()
                    if name.lower().endswith((".mp4", ".mkv", ".webm")):
                        if file.get("private") == "true":
                            continue
                        link = f"{BASE}/download/{quote(ident)}/{quote(name)}"
                        streams.append({
                            "name": "Internet Archive",
                            "title": f"{fmt or 'Vídeo'} - {name}",
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
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
          
