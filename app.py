
import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from yt_dlp import YoutubeDL

PORT = int(os.environ.get("PORT", 10000))

APP_NAME = "Live Concerts"
VERSION = "2.0.0"

PEERTUBE_HOSTS = [
    "peertube.cpy.re",
    "diode.zone",
    "tilvids.com"
]

CATEGORIES = {
    "concertos": "full live concert full show",
    "rock": "rock full concert live",
    "metal": "metal full concert live",
    "pop": "pop full concert live",
    "portugal": "concerto completo ao vivo Portugal",
    "festivais": "full music festival live performance",
    "classicos": "classic rock full concert live",
    "jazz": "jazz blues full live concert"
}

MANIFEST = {
    "id": "pt.liveconcerts.nuvio",
    "version": VERSION,
    "name": APP_NAME,
    "description": "Pesquisa mundial de concertos completos.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "idPrefixes": ["yt:", "archive:", "pt:"],
    "catalogs": [
        {
            "type": "movie",
            "id": category,
            "name": name,
            "extra": [
                {"name": "search", "isRequired": False}
            ]
        }
        for category, name in [
            ("concertos", "Todos os Concertos"),
            ("rock", "Rock"),
            ("metal", "Metal"),
            ("pop", "Pop"),
            ("portugal", "Concertos Portugueses"),
            ("festivais", "Festivais"),
            ("classicos", "Clássicos"),
            ("jazz", "Jazz e Blues")
        ]
    ]
}

CACHE = {}

HEADERS = {
    "User-Agent": "LiveConcertsAddon/2.0"
}


def fetch_json(url, timeout=15):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_query(value):
    return re.sub(r"[\r\n]+", " ", value).strip()[:150]


def youtube_search(query, limit=20):
    results = []

    options = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 15
    }

    try:
        with YoutubeDL(options) as ydl:
            data = ydl.extract_info(
                "ytsearch" + str(limit) + ":" + query,
                download=False
            )

        if not data:
            return results

        for video in data.get("entries", []):
            if not video:
                continue

            video_id = video.get("id")
            title = video.get("title", "")
            duration = video.get("duration") or 0

            # Excluir videoclipes e pequenos excertos.
            if not video_id or duration < 900:
                continue

            thumbnail = video.get("thumbnail")

            if not thumbnail:
                thumbnails = video.get("thumbnails") or []
                if thumbnails:
                    thumbnail = thumbnails[-1].get("url")

            item = {
                "id": "yt:" + video_id,
                "type": "movie",
                "name": title,
                "poster": thumbnail,
                "background": thumbnail,
                "description": (
                    "Fonte: YouTube\n"
                    "Canal: " + str(video.get("channel") or "Desconhecido")
                    + "\nDuração: "
                    + str(round(duration / 60)) + " minutos"
                ),
                "genres": ["Concerto", "Música ao vivo"]
            }

            CACHE[item["id"]] = item
            results.append(item)

    except Exception as error:
        print("Erro YouTube:", str(error))

    return results


def archive_search(query):
    results = []

    if query:
        query = clean_query(query).replace('"', " ")
        archive_query = (
            'mediatype:movies AND '
            '(title:("' + query + '") OR description:("' + query + '"))'
        )
    else:
        archive_query = (
            'mediatype:movies AND '
            '(subject:concert OR title:concert OR '
            'title:music OR description:concert)'
        )

    params = {
        "q": archive_query,
        "fl[]": ["identifier", "title", "year", "description"],
        "rows": 40,
        "page": 1,
        "output": "json",
        "sort[]": "downloads desc"
    }

    url = (
        "https://archive.org/advancedsearch.php?"
        + urllib.parse.urlencode(params, doseq=True)
    )

    try:
        data = fetch_json(url)
        documents = data.get("response", {}).get("docs", [])

        for doc in documents:
            identifier = doc.get("identifier")
            title = doc.get("title", identifier)

            if not identifier:
                continue

            item = {
                "id": "archive:" + identifier,
                "type": "movie",
                "name": title,
                "description": str(doc.get("description") or ""),
                "year": doc.get("year"),
                "poster": (
                    "https://archive.org/services/img/" + identifier
                ),
                "genres": ["Concerto", "Internet Archive"]
            }

            CACHE[item["id"]] = item
            results.append(item)

    except Exception as error:
        print("Erro Archive:", str(error))

    return results


def peertube_search_host(host, query):
    results = []

    params = urllib.parse.urlencode({
        "search": query,
        "count": 20,
        "sort": "-views",
        "nsfw": "false"
    })

    url = (
        "https://" + host
        + "/api/v1/search/videos?"
        + params
    )

    try:
        data = fetch_json(url)

        for video in data.get("data", []):
            uuid = video.get("uuid")
            title = video.get("name", "")

            if not uuid:
                continue

            thumbnail_path = video.get("thumbnailPath")

            poster = None
            if thumbnail_path:
                poster = urllib.parse.urljoin(
                    "https://" + host,
                    thumbnail_path
                )

            item = {
                "id": "pt:" + host + ":" + uuid,
                "type": "movie",
                "name": title,
                "description": video.get("description", ""),
                "poster": poster,
                "background": poster,
                "genres": ["Concerto", "PeerTube"]
            }

            CACHE[item["id"]] = item
            results.append(item)

    except Exception as error:
        print("Erro PeerTube", host, str(error))

    return results


def peertube_search(query):
    results = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        tasks = [
            executor.submit(peertube_search_host, host, query)
            for host in PEERTUBE_HOSTS
        ]

        for task in tasks:
            try:
                results.extend(task.result())
            except Exception:
                pass

    return results


def search_all(query):
    query = clean_query(query)

    if not query:
        query = "full live concert"

    youtube_query = query

    if len(query.split()) <= 3:
        youtube_query += " full concert live"

    with ThreadPoolExecutor(max_workers=3) as executor:
        tasks = [
            executor.submit(youtube_search, youtube_query, 20),
            executor.submit(archive_search, query),
            executor.submit(peertube_search, query)
        ]

        results = []

        for task in tasks:
            try:
                results.extend(task.result())
            except Exception as error:
                print("Erro de pesquisa:", str(error))

    unique = {}
    for item in results:
        unique[item["id"]] = item

    return list(unique.values())[:100]


def get_youtube_info(video_id):
    options = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "socket_timeout": 15
    }

    with YoutubeDL(options) as ydl:
        return ydl.extract_info(
            "https://www.youtube.com/watch?v=" + video_id,
            download=False
        )


def get_archive_metadata(identifier):
    url = (
        "https://archive.org/metadata/"
        + urllib.parse.quote(identifier, safe="")
    )

    return fetch_json(url)


def get_peertube_metadata(host, uuid):
    url = (
        "https://" + host
        + "/api/v1/videos/"
        + urllib.parse.quote(uuid, safe="")
    )

    return fetch_json(url)


def get_streams(identifier):
    streams = []

    if identifier.startswith("yt:"):
        video_id = identifier[3:]

        streams.append({
            "name": "YouTube",
            "title": "Reprodução no Nuvio",
            "ytId": video_id
        })

    elif identifier.startswith("archive:"):
        archive_id = identifier.split(":", 1)[1]
        data = get_archive_metadata(archive_id)

        for file in data.get("files", []):
            filename = file.get("name", "")

            if not filename.lower().endswith(
                (".mp4", ".mkv", ".webm", ".mov", ".avi", ".mpeg", ".mpg")
            ):
                continue

            url = (
                "https://archive.org/download/"
                + urllib.parse.quote(archive_id, safe="")
                + "/"
                + urllib.parse.quote(filename, safe="/")
            )

            streams.append({
                "name": "Internet Archive",
                "title": filename,
                "url": url,
                "behaviorHints": {
                    "notWebReady": not filename.lower().endswith(".mp4")
                }
            })

    elif identifier.startswith("pt:"):
        parts = identifier.split(":", 2)

        if len(parts) != 3:
            return streams

        host = parts[1]
        uuid = parts[2]

        data = get_peertube_metadata(host, uuid)

        for file in data.get("files", []):
            file_url = file.get("fileUrl")

            if file_url:
                streams.append({
                    "name": "PeerTube",
                    "title": (
                        str(file.get("resolution", {}).get("label", "Vídeo"))
                    ),
                    "url": file_url,
                    "behaviorHints": {
                        "notWebReady": True
                    }
                })

        for playlist in data.get("streamingPlaylists", []):
            playlist_url = playlist.get("playlistUrl")

            if playlist_url:
                streams.append({
                    "name": "PeerTube HLS",
                    "title": "Reprodução adaptativa",
                    "url": playlist_url,
                    "behaviorHints": {
                        "notWebReady": True
                    }
                })

    return streams


class Handler(BaseHTTPRequestHandler):

    def send_json(self, data):
        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_json({
                "name": APP_NAME,
                "version": VERSION,
                "status": "online"
            })
            return

        if path == "/manifest.json":
            self.send_json(MANIFEST)
            return

        parts = path.strip("/").split("/")

        if len(parts) >= 3 and parts[0] == "catalog":
            catalog_id = parts[2]

            extra = "/".join(parts[3:])
            if extra.endswith(".json"):
                extra = extra[:-5]

            args = urllib.parse.parse_qs(extra)
            search = args.get("search", [""])[0]

            if search:
                results = search_all(search)
            else:
                category_query = CATEGORIES.get(
                    catalog_id,
                    "full live concert"
                )
                results = search_all(category_query)

            self.send_json({"metas": results})
            return

        if len(parts) >= 3 and parts[0] == "meta":
            identifier = urllib.parse.unquote(parts[2])

            if identifier in CACHE:
                self.send_json({"meta": CACHE[identifier]})
                return

            try:
                if identifier.startswith("yt:"):
                    info = get_youtube_info(identifier[3:])

                    if not info:
                        raise Exception("Vídeo indisponível")

                    item = {
                        "id": identifier,
                        "type": "movie",
                        "name": info.get("title", "Concerto"),
                        "description": info.get("description", ""),
                        "poster": info.get("thumbnail"),
                        "genres": ["Concerto", "YouTube"]
                    }

                elif identifier.startswith("archive:"):
                    archive_id = identifier.split(":", 1)[1]
                    data = get_archive_metadata(archive_id)
                    metadata = data.get("metadata", {})

                    item = {
                        "id": identifier,
                        "type": "movie",
                        "name": metadata.get("title", archive_id),
                        "description": metadata.get("description", ""),
                        "poster": (
                            "https://archive.org/services/img/"
                            + archive_id
                        )
                    }

                elif identifier.startswith("pt:"):
                    _, host, uuid = identifier.split(":", 2)
                    data = get_peertube_metadata(host, uuid)

                    item = {
                        "id": identifier,
                        "type": "movie",
                        "name": data.get("name", "Concerto"),
                        "description": data.get("description", ""),
                        "poster": data.get("thumbnailPath")
                    }

                    if item["poster"]:
                        item["poster"] = urllib.parse.urljoin(
                            "https://" + host,
                            item["poster"]
                        )

                else:
                    raise Exception("Identificador desconhecido")

                CACHE[identifier] = item
                self.send_json({"meta": item})

            except Exception as error:
                print("Erro metadata:", str(error))
                self.send_json({"meta": None})

            return

        if len(parts) >= 3 and parts[0] == "stream":
            identifier = urllib.parse.unquote(parts[2])

            try:
                streams = get_streams(identifier)
                self.send_json({"streams": streams})

            except Exception as error:
                print("Erro streams:", str(error))
                self.send_json({"streams": []})

            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        print(format % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        Handler
    )

    print(APP_NAME, "iniciado na porta", PORT)
    server.serve_forever()
