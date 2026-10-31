
import json
import os
import re
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, quote
from urllib.request import Request, urlopen

ARCHIVE = "https://archive.org"

logging.basicConfig(level=logging.INFO)

MANIFEST = {
    "id": "pt.ruben.liveconcerts",
    "version": "2.0.0",
    "name": "Live Music Concerts",
    "description": "Pesquisa concertos, DVDs musicais e gravações ao vivo.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "catalogs": [
        {
            "type": "movie",
            "id": "liveconcerts",
            "name": "Live Music Concerts",
            "extra": [
                {"name": "search", "isRequired": False}
            ]
        }
    ]
}

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".mpeg", ".mpg"
)


def fetch_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": "LiveMusicConcerts/2.0",
            "Accept": "application/json"
        }
    )
    with urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_text(value):
    if isinstance(value, list):
        return " ".join(str(x) for x in value[:5])
    if value is None:
        return ""
    return str(value)


def archive_search(term):
    phrase = " ".join(term.strip().split())
    phrase = phrase.replace('"', "").replace("\\", "")

    if not phrase:
        return []

    # Pesquisa pela expressão completa no título
    query = f'title:"{phrase}" AND mediatype:movies'

    url = (
        ARCHIVE + "/advancedsearch.php?q=" + quote(query)
        + "&fl[]=identifier"
        + "&fl[]=title"
        + "&fl[]=year"
        + "&fl[]=description"
        + "&rows=100&page=1&output=json"
    )

    data = fetch_json(url)
    documents = data.get("response", {}).get("docs", [])

    # Filtra novamente para evitar resultados irrelevantes
    filtered = []
    phrase_lower = phrase.casefold()

    for item in documents:
        title = clean_text(item.get("title", ""))
        if phrase_lower in title.casefold():
            filtered.append(item)

    return filtered


def get_item(identifier):
    url = ARCHIVE + "/metadata/" + quote(identifier, safe="")
    return fetch_json(url)


def image_url(identifier):
    return (
        ARCHIVE + "/services/img/"
        + quote(identifier, safe="")
    )


def make_meta(identifier, metadata):
    title = clean_text(metadata.get("title")) or identifier
    description = clean_text(metadata.get("description"))
    year = clean_text(metadata.get("year"))

    return {
        "id": identifier,
        "type": "movie",
        "name": title,
        "description": description[:1500],
        "poster": image_url(identifier),
        "background": image_url(identifier),
        "releaseInfo": year
    }


def get_streams(identifier):
    data = get_item(identifier)
    files = data.get("files", [])
    streams = []

    for file in files:
        filename = clean_text(file.get("name"))
        lower = filename.lower()

        if not lower.endswith(VIDEO_EXTENSIONS):
            continue

        if file.get("private") in (True, "true", 1):
            continue

        if file.get("source") == "original":
            pass

        download_url = (
            ARCHIVE + "/download/"
            + quote(identifier, safe="")
            + "/"
            + quote(filename, safe="")
        )

        size = file.get("size")
        size_text = ""

        try:
            if size:
                size_text = (
                    " | "
                    + str(round(int(size) / 1048576))
                    + " MB"
                )
        except (ValueError, TypeError):
            pass

        streams.append({
            "name": "Internet Archive",
            "title": filename + size_text,
            "url": download_url
        })

    # Primeiro os formatos mais comuns
    streams.sort(
        key=lambda item: (
            0 if item["title"].lower().split("|")[0].strip().endswith(".mp4")
            else 1
        )
    )

    return streams[:30]


class Handler(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        parts = path.strip("/").split("/")
        params = parse_qs(parsed.query)

        if path == "/":
            return self.send_json({
                "addon": "Live Music Concerts",
                "status": "online",
                "version": "2.0.0"
            })

        if path == "/manifest.json":
            return self.send_json(MANIFEST)

        # CATÁLOGO E PESQUISA
        if len(parts) >= 3 and parts[0] == "catalog":
            term = params.get("search", [""])[0]

            for part in parts[3:]:
                if part.startswith("search="):
                    term = part[len("search="):]
                    term = re.sub(r"\.json$", "", term)

            if not term:
                term = "live concert"

            try:
                documents = archive_search(term)
                metas = []

                for item in documents:
                    identifier = item.get("identifier")
                    if not identifier:
                        continue

                    metas.append(
                        make_meta(identifier, item)
                    )

                return self.send_json({"metas": metas})

            except Exception as error:
                logging.exception("Erro na pesquisa: %s", error)
                return self.send_json({"metas": []})

        # FICHA INDIVIDUAL DO CONCERTO
        if len(parts) >= 3 and parts[0] == "meta":
            identifier = re.sub(r"\.json$", "", parts[2])

            try:
                data = get_item(identifier)
                metadata = data.get("metadata", {})
                meta = make_meta(identifier, metadata)

                return self.send_json({"meta": meta})

            except Exception as error:
                logging.exception("Erro nos metadados: %s", error)
                return self.send_json({"meta": None})

        # FONTES DE REPRODUÇÃO
        if len(parts) >= 3 and parts[0] == "stream":
            identifier = re.sub(r"\.json$", "", parts[2])

            try:
                streams = get_streams(identifier)
                return self.send_json({"streams": streams})

            except Exception as error:
                logging.exception("Erro nos streams: %s", error)
                return self.send_json({"streams": []})

        return self.send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        logging.info("%s - %s", self.address_string(), format % args)


port = int(os.environ.get("PORT", 10000))

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    Handler
)

logging.info("Live Music Concerts iniciado na porta %s", port)

server.serve_forever()
