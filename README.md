# Serenade

Self-hosted NetEase Cloud Music web player. Search songs, play full tracks with your own VIP account, and remotely switch songs from anywhere.

Built at midnight because someone wanted to hear a song.

## Features

- **Search** — NetEase Cloud Music catalog
- **Full playback** — Uses your own MUSIC_U cookie for VIP-quality streams
- **Server-side caching** — Songs are downloaded once and served locally
- **CDN fallback** — Automatically switches CDN nodes when blocked (overseas servers)
- **Remote play** — Push a song to the player from any device via API
- **Zero dependencies** — Pure Python stdlib server, vanilla JS frontend

## Quick start

```bash
git clone https://github.com/sebastianevan200-stack/serenade.git
cd serenade

# Add your NetEase Cloud Music cookie
echo "MUSIC_U=your_cookie_here" > server/.netease_cred

# Run
python3 server/serenade.py
```

Open http://localhost:8080

## Getting your MUSIC_U cookie

1. Open [music.163.com](https://music.163.com) in your browser and log in
2. Open DevTools → Application → Cookies
3. Find the `MUSIC_U` cookie and copy its value
4. Paste it into `server/.netease_cred`

## Remote play API

Push a song to the player from another device:

```bash
curl -X POST http://localhost:8080/api/remote \
  -H "Content-Type: application/json" \
  -d '{"name":"Song Name","artist":"Artist","cover":"https://...","songId":12345}'
```

The player polls every 3 seconds and auto-plays the pushed song.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/search?q=keyword` | GET | Search songs |
| `/api/url?id=songId` | GET | Cache and get playback URL |
| `/api/file/{id}.mp3` | GET | Serve cached audio |
| `/api/remote` | GET | Poll for remote play command |
| `/api/remote` | POST | Push a song to the player |

## How it works

```
Browser → /api/search → NetEase Search API → song list
Browser → /api/url    → NetEase Player API → download to cache → /api/file/xxx.mp3
Browser → <audio src="/api/file/xxx.mp3">  → plays from local cache
```

Some NetEase CDN nodes (m704, m804) block overseas IPs. Serenade automatically falls back to m701 when a download fails.

## License

MIT
