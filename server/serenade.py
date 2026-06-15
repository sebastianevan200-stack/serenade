#!/usr/bin/env python3
"""Serenade — self-hosted NetEase Cloud Music web player.

Features:
  - Search songs via NetEase Cloud Music API
  - Stream full tracks using your own VIP cookie
  - Server-side caching with automatic CDN fallback
  - Remote playback control (change songs from another device)

Usage:
  1. Put your MUSIC_U cookie in .netease_cred:  MUSIC_U=<your_cookie>
  2. python3 serenade.py
  3. Open http://localhost:8080
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
CLIENT_DIR = HERE.parent / "client"
CACHE_DIR = HERE / "cache"
CRED_FILE = HERE / ".netease_cred"
REMOTE_FILE = HERE / "remote.json"

PORT = 8080
BITRATE = 128000
CDN_FALLBACK = "m701.music.126.net"


def _cookie() -> str:
    try:
        for line in CRED_FILE.read_text().splitlines():
            if line.startswith("MUSIC_U="):
                return f"MUSIC_U={line.split('=', 1)[1].strip()}"
    except OSError:
        pass
    return ""


def _netease_req(url: str, data: bytes | None = None, timeout: int = 10) -> dict:
    headers = {
        "Cookie": _cookie(),
        "Referer": "https://music.163.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CLIENT_DIR), **kwargs)

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/search":
            return self._search()
        if path == "/api/url":
            return self._get_url()
        if path == "/api/remote":
            return self._remote_get()
        if path.startswith("/api/file/"):
            return self._serve_cached(path)

        # Fall through to static file serving
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/remote":
            return self._remote_set()
        self._json(404, {"error": "not found"})

    def _search(self):
        qs = parse_qs(urlparse(self.path).query)
        keyword = qs.get("q", [""])[0]
        if not keyword:
            return self._json(400, {"error": "missing q"})
        try:
            post_data = urllib.parse.urlencode(
                {"s": keyword, "type": "1", "limit": "6", "offset": "0"}
            ).encode()
            raw = _netease_req("https://music.163.com/api/search/get", data=post_data)
            result = raw.get("result", {})
            if not isinstance(result, dict):
                return self._json(200, {"ok": True, "songs": []})
            raw_songs = result.get("songs", [])[:6]
            # Fetch covers
            ids = [s.get("id") for s in raw_songs if s.get("id")]
            covers: dict = {}
            if ids:
                try:
                    detail_url = f"https://music.163.com/api/song/detail?ids=[{','.join(str(i) for i in ids)}]"
                    detail = _netease_req(detail_url)
                    for ds in detail.get("songs", []):
                        al = ds.get("album", {}) or {}
                        if al.get("picUrl"):
                            covers[ds.get("id")] = al["picUrl"]
                except Exception:
                    pass
            songs = []
            for s in raw_songs:
                artists = ", ".join(a.get("name", "") for a in s.get("artists", []))
                album = s.get("album", {}) or {}
                cover = covers.get(s.get("id"), album.get("picUrl", "") or "")
                if cover and not cover.startswith("http"):
                    cover = "https:" + cover
                songs.append({
                    "id": s.get("id"),
                    "name": s.get("name", ""),
                    "artist": artists,
                    "album": album.get("name", ""),
                    "cover": cover,
                })
            self._json(200, {"ok": True, "songs": songs})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def _get_url(self):
        qs = parse_qs(urlparse(self.path).query)
        song_id = qs.get("id", [""])[0]
        if not song_id:
            return self._json(400, {"error": "missing id"})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{song_id}.mp3"
        if cache_file.exists() and cache_file.stat().st_size > 0:
            return self._json(200, {"ok": True, "url": f"/api/file/{song_id}.mp3"})
        try:
            raw = _netease_req(
                f"https://music.163.com/api/song/enhance/player/url?ids=[{song_id}]&br={BITRATE}"
            )
            data_list = raw.get("data", [])
            audio_url = data_list[0].get("url") if data_list else None
            if not audio_url:
                return self._json(200, {"ok": False, "error": "no url, may need VIP or region-locked"})

            def _download(dl_url: str):
                areq = urllib.request.Request(dl_url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://music.163.com",
                    "Cookie": _cookie(),
                })
                tmp = cache_file.with_suffix(".tmp")
                with urllib.request.urlopen(areq, timeout=120) as aresp:
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = aresp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                tmp.rename(cache_file)

            try:
                _download(audio_url)
            except urllib.request.HTTPError:
                fallback = re.sub(r"m\d+\.music\.126\.net", CDN_FALLBACK, audio_url)
                _download(fallback)
            self._json(200, {"ok": True, "url": f"/api/file/{song_id}.mp3"})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def _serve_cached(self, path: str):
        filename = path.split("/")[-1]
        fp = CACHE_DIR / filename
        if not fp.exists() or not fp.name.endswith(".mp3"):
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(fp.stat().st_size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(fp, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _remote_get(self):
        if REMOTE_FILE.exists():
            data = json.loads(REMOTE_FILE.read_text())
            REMOTE_FILE.unlink()
            self._json(200, {"ok": True, "song": data})
        else:
            self._json(200, {"ok": False})

    def _remote_set(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            song = json.loads(body)
            REMOTE_FILE.write_text(json.dumps(song, ensure_ascii=False))
            self._json(200, {"ok": True})
        except Exception as e:
            self._json(400, {"error": str(e)})

    def log_message(self, fmt, *args):
        pass  # quiet


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not CRED_FILE.exists():
        print(f"⚠  Put your NetEase MUSIC_U cookie in {CRED_FILE}")
        print(f"   Format: MUSIC_U=your_cookie_value_here")
        print()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🎵 Serenade running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
