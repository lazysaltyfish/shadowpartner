from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

YOUTUBE_ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")


@dataclass
class PlaylistInfo:
    title: str
    description: Optional[str]
    cover_image: Optional[str]
    entries: List[str]


class ApiError(Exception):
    def __init__(self, status: int, data: Any, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.data = data
        self.url = url


class ApiClient:
    def __init__(self, base_url: str, cli_token: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not cli_token:
            raise ValueError("CLI token is required")
        self.headers = {"X-CLI-Token": cli_token}

    def request_json(
        self, path: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = raw
            raise ApiError(exc.code, data, url) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Request failed: {exc.reason}") from exc

    def process_url(self, url: str) -> Dict[str, Any]:
        return self.request_json("/api/process", method="POST", payload={"url": url})

    def get_status(self, task_id: str) -> Dict[str, Any]:
        return self.request_json(f"/api/status/{task_id}")

    def create_playlist(self, title: str, description: Optional[str], cover_image: Optional[str]) -> str:
        payload: Dict[str, Any] = {"title": title}
        if description is not None:
            payload["description"] = description
        if cover_image is not None:
            payload["cover_image"] = cover_image
        data = self.request_json("/api/playlists", method="POST", payload=payload)
        if not data or "id" not in data:
            raise RuntimeError("Playlist creation returned no id")
        return data["id"]

    def get_playlist(self, playlist_id: str) -> Dict[str, Any]:
        data = self.request_json(f"/api/playlists/{playlist_id}")
        if not isinstance(data, dict):
            raise RuntimeError("Playlist lookup returned unexpected response")
        return data

    def add_playlist_item(self, playlist_id: str, asset_id: str, position: Optional[int]) -> None:
        payload: Dict[str, Any] = {"asset_id": asset_id}
        if position is not None:
            payload["position"] = position
        self.request_json(f"/api/playlists/{playlist_id}/items", method="POST", payload=payload)


def extract_youtube_id(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None
    if YOUTUBE_ID_RE.match(raw):
        return raw
    if not raw.startswith("http"):
        return None

    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc.lower()

    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0][:11] or None

    if "youtube.com" in host:
        if parsed.path == "/watch":
            query = urllib.parse.parse_qs(parsed.query)
            if "v" in query and query["v"]:
                return query["v"][0][:11]
        for prefix in ("/shorts/", "/embed/", "/v/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix) :].split("/")[0][:11]

    return None


def normalize_youtube_url(raw: str) -> Optional[str]:
    video_id = extract_youtube_id(raw)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def extract_playlist_id(raw: str) -> Optional[str]:
    if not raw or not raw.startswith("http"):
        return None
    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc.lower()
    if "youtube.com" not in host and not host.endswith("youtu.be"):
        return None
    query = urllib.parse.parse_qs(parsed.query)
    playlist_values = query.get("list") or []
    if not playlist_values:
        return None
    playlist_id = playlist_values[0].strip()
    return playlist_id or None


def build_playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def normalize_playlist_url(raw: str) -> Optional[str]:
    playlist_id = extract_playlist_id(raw)
    if not playlist_id:
        return None
    return build_playlist_url(playlist_id)


def prompt_playlist_upload(url: str, playlist_id: str, logger: logging.Logger) -> bool:
    if not sys.stdin.isatty():
        logger.info("Detected playlist in URL but stdin is not interactive; using single video.")
        return False

    prompt = (
        f"Detected playlist (list={playlist_id}) in URL. "
        "Upload the entire playlist instead of a single video? [y/N]: "
    )
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'.")


def read_url_list(path: str) -> List[str]:
    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith(";") or stripped.startswith("//"):
                continue
            if "#" in stripped:
                stripped = stripped.split("#", 1)[0].strip()
            if stripped:
                urls.append(stripped)
    return urls


def _fetch_playlist_info_with_ytdlp(playlist_url: str) -> Dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed; install it or use the yt-dlp binary") from exc

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned unexpected playlist data")
    return info


def _fetch_playlist_info_with_binary(playlist_url: str) -> Dict[str, Any]:
    cmd = ["yt-dlp", "--flat-playlist", "-J", playlist_url]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("yt-dlp binary not found in PATH") from exc

    if result.returncode != 0:
        message = result.stderr.strip() or "yt-dlp failed"
        raise RuntimeError(message)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse yt-dlp output") from exc


def fetch_youtube_playlist(playlist_url: str, logger: logging.Logger) -> PlaylistInfo:
    normalized = normalize_playlist_url(playlist_url)
    if normalized:
        playlist_url = normalized
    try:
        info = _fetch_playlist_info_with_ytdlp(playlist_url)
    except RuntimeError:
        info = _fetch_playlist_info_with_binary(playlist_url)

    title = info.get("title") or info.get("playlist_title") or "YouTube Playlist"
    description = info.get("description")

    cover_image = info.get("thumbnail")
    if not cover_image:
        thumbnails = info.get("thumbnails") or []
        if thumbnails:
            cover_image = thumbnails[-1].get("url")

    entries: List[str] = []
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        candidate = entry.get("id") or entry.get("url") or ""
        video_id = extract_youtube_id(candidate)
        if not video_id:
            logger.warning("Skipping playlist entry without video id: %s", candidate)
            continue
        entries.append(f"https://www.youtube.com/watch?v={video_id}")

    return PlaylistInfo(
        title=str(title).strip() or "YouTube Playlist",
        description=description,
        cover_image=cover_image,
        entries=entries,
    )


def poll_task(
    client: ApiClient,
    task_id: str,
    poll_interval: float,
    timeout: float,
) -> Dict[str, Any]:
    start = time.time()
    while True:
        data = client.get_status(task_id)
        status = data.get("status")
        if status == "completed":
            return data.get("result") or {}
        if status == "failed":
            message = data.get("error") or data.get("message") or "Processing failed"
            raise RuntimeError(message)
        if timeout and (time.time() - start) > timeout:
            raise TimeoutError("Polling timed out")
        time.sleep(poll_interval)


def process_video(
    client: ApiClient,
    url: str,
    poll_interval: float,
    timeout: float,
    logger: logging.Logger,
) -> Optional[str]:
    try:
        response = client.process_url(url)
        task_id = response.get("task_id") if response else None
        if not task_id:
            raise RuntimeError("Missing task_id in response")
    except ApiError as exc:
        if exc.status == 409 and isinstance(exc.data, dict):
            detail = exc.data.get("detail")
            if isinstance(detail, dict) and detail.get("asset_id"):
                logger.info("Video already exists: %s", detail.get("asset_id"))
                return str(detail.get("asset_id"))
        raise

    result = poll_task(client, task_id, poll_interval, timeout)
    asset_id = result.get("asset_id") if isinstance(result, dict) else None
    if not asset_id:
        raise RuntimeError("No asset_id returned after processing")
    return str(asset_id)


def configure_logger(log_file: Optional[str], verbose: bool) -> logging.Logger:
    logger = logging.getLogger("auto_uploader")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ShadowPartner auto uploader")
    parser.add_argument("--base-url", default=os.getenv("BACKEND_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--cli-token", default=os.getenv("CLI_MAGIC_TOKEN"))
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--log-file", default="auto_uploader.log")
    parser.add_argument("--verbose", action="store_true")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url")
    input_group.add_argument("--list")
    input_group.add_argument("--youtube-playlist")

    parser.add_argument("--playlist-id")
    parser.add_argument("--playlist-title")
    parser.add_argument("--playlist-description")
    parser.add_argument("--playlist-cover-image")

    return parser


def log_playlist_metadata(
    logger: logging.Logger,
    label: str,
    playlist_id: Optional[str],
    title: Optional[str],
    description: Optional[str],
    cover_image: Optional[str],
    item_count: Optional[int] = None,
) -> None:
    logger.info(
        "%s playlist meta: id=%s title=%s description=%s cover_image=%s items=%s",
        label,
        playlist_id or "unknown",
        title or "",
        description or "",
        cover_image or "",
        item_count if item_count is not None else "",
    )


def resolve_playlist_id(
    client: ApiClient,
    args: argparse.Namespace,
    playlist_info: Optional[PlaylistInfo],
    logger: logging.Logger,
) -> tuple[Optional[str], bool, Optional[Dict[str, Any]]]:
    if args.playlist_id and (
        args.playlist_title or args.playlist_description or args.playlist_cover_image
    ):
        raise RuntimeError("Do not combine --playlist-id with playlist metadata options")

    if args.playlist_id:
        return args.playlist_id, False, None

    title = args.playlist_title
    description = args.playlist_description
    cover_image = args.playlist_cover_image

    if playlist_info:
        title = title or playlist_info.title
        description = description if description is not None else playlist_info.description
        cover_image = cover_image if cover_image is not None else playlist_info.cover_image

    if title:
        playlist_id = client.create_playlist(title, description, cover_image)
        meta = {
            "id": playlist_id,
            "title": title,
            "description": description,
            "cover_image": cover_image,
        }
        log_playlist_metadata(
            logger,
            "Backend (created)",
            playlist_id,
            title,
            description,
            cover_image,
            None,
        )
        return playlist_id, True, meta

    return None, False, None


def iter_urls(
    single_url: Optional[str],
    list_path: Optional[str],
    playlist_info: Optional[PlaylistInfo],
) -> Iterable[str]:
    if single_url:
        return [single_url]
    if list_path:
        return read_url_list(list_path)
    if playlist_info is not None:
        return playlist_info.entries
    return []


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logger = configure_logger(args.log_file, args.verbose)

    if not args.cli_token:
        logger.error("CLI token missing. Set --cli-token or CLI_MAGIC_TOKEN.")
        return 1

    client = ApiClient(args.base_url, args.cli_token)

    playlist_source = args.youtube_playlist
    single_url = args.url
    if args.url:
        playlist_id = extract_playlist_id(args.url)
        if playlist_id:
            if prompt_playlist_upload(args.url, playlist_id, logger):
                playlist_source = build_playlist_url(playlist_id)
                single_url = None
                logger.info("Using playlist from URL: %s", playlist_source)

    playlist_info = None
    if playlist_source:
        playlist_info = fetch_youtube_playlist(playlist_source, logger)
        if not playlist_info.entries:
            logger.error("No URLs found for playlist: %s", playlist_source)
            return 1
        log_playlist_metadata(
            logger,
            "YouTube",
            None,
            playlist_info.title,
            playlist_info.description,
            playlist_info.cover_image,
            len(playlist_info.entries),
        )

    try:
        playlist_id, playlist_is_new, playlist_meta = resolve_playlist_id(
            client, args, playlist_info, logger
        )
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    urls = list(iter_urls(single_url, args.list, playlist_info))
    if not urls:
        logger.error("No URLs provided")
        return 1

    playlist_title = None
    if playlist_id and playlist_meta:
        playlist_title = playlist_meta.get("title")
    elif playlist_id:
        try:
            existing = client.get_playlist(playlist_id)
            playlist_title = existing.get("title")
            log_playlist_metadata(
                logger,
                "Backend (existing)",
                playlist_id,
                existing.get("title"),
                existing.get("description"),
                existing.get("cover_image"),
                None,
            )
        except ApiError as exc:
            logger.warning("Failed to fetch playlist metadata for %s: %s", playlist_id, exc)
            log_playlist_metadata(
                logger,
                "Backend (existing)",
                playlist_id,
                None,
                None,
                None,
                None,
            )

    total = len(urls)
    success = 0
    for index, raw in enumerate(urls):
        position = index + 1
        cleaned = normalize_youtube_url(raw)
        if not cleaned:
            logger.error("Invalid YouTube URL: %s", raw)
            continue

        logger.info("[%s/%s] Uploading: %s", position, total, cleaned)
        try:
            asset_id = process_video(client, cleaned, args.poll_interval, args.timeout, logger)
        except Exception as exc:
            logger.error("[%s/%s] Upload failed for %s: %s", position, total, cleaned, exc)
            continue

        if playlist_id and asset_id:
            try:
                playlist_position = index if playlist_is_new else None
                client.add_playlist_item(playlist_id, asset_id, playlist_position)
                logger.info(
                    "[%s/%s] Added asset %s to playlist %s (%s)",
                    position,
                    total,
                    asset_id,
                    playlist_id,
                    playlist_title or "unknown",
                )
            except ApiError as exc:
                if exc.status == 409:
                    logger.info(
                        "[%s/%s] Asset already in playlist %s (%s): %s",
                        position,
                        total,
                        playlist_id,
                        playlist_title or "unknown",
                        asset_id,
                    )
                else:
                    logger.error("Failed to add asset to playlist: %s", exc)
        success += 1

        if args.sleep:
            time.sleep(args.sleep)

    logger.info("Completed: %s/%s succeeded", success, len(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
