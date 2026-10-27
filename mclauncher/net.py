from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO

from . import __version__
from .errors import DownloadError
from .progress import Progress
from .util import ensure_dir, file_matches

USER_AGENT = f"mclauncher/{__version__} (Python {sys.version_info.major}.{sys.version_info.minor})"
_SSL_CONTEXT = ssl.create_default_context()
_JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


@dataclass
class DownloadTask:
    url: str
    dest: Path
    sha1: str | None = None
    size: int | None = None


def _open(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 30.0):
    merged = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        merged.update({k: v for k, v in headers.items() if v is not None})
    request = urllib.request.Request(url, data=data, headers=merged, method="POST" if data is not None else "GET")
    return urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT)


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", "replace")
    except Exception:
        body = ""
    return f"HTTP {exc.code} {exc.reason}" + (f": {body[:300]}" if body.strip() else "")


def get_bytes(url: str, timeout: float = 60.0, retries: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with _open(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = DownloadError(_http_error_detail(exc))
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
        time.sleep(0.6 * (attempt + 1) + random.random() * 0.3)
    raise DownloadError(f"请求失败: {url} ({last_error})")


def get_json(url: str, timeout: float = 60.0, retries: int = 4, headers: dict[str, str] | None = None) -> Any:
    data = get_bytes(url, timeout=timeout, retries=retries) if not headers else _get_with_headers(url, headers, timeout, retries)
    try:
        return json.loads(data.decode("utf-8-sig"))
    except ValueError as exc:
        raise DownloadError(f"返回的不是合法 JSON: {url} ({exc})") from exc


def _get_with_headers(url: str, headers: dict[str, str], timeout: float, retries: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with _open(url, headers=headers, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = DownloadError(_http_error_detail(exc))
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
        time.sleep(0.6 * (attempt + 1) + random.random() * 0.3)
    raise DownloadError(f"请求失败: {url} ({last_error})")


def post_json_status(
    url: str,
    payload: Any,
    headers: dict[str, str] | None = None,
    timeout: float = 40.0,
) -> tuple[int, Any]:
    """POST JSON，返回 (HTTP 状态码, JSON)。错误响应体也尝试解析。"""
    body = json.dumps(payload).encode("utf-8")
    merged = dict(_JSON_HEADERS)
    if headers:
        merged.update(headers)
    try:
        with _open(url, data=body, headers=merged, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8-sig") or "null")
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:
            pass
        try:
            data = json.loads(raw.decode("utf-8-sig") or "null")
        except ValueError:
            data = {"error": f"http_{exc.code}", "error_description": raw.decode("utf-8", "replace")[:300]}
        return exc.code, data
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
        raise DownloadError(f"请求失败: {url} ({exc})") from exc


def post_json(url: str, payload: Any, headers: dict[str, str] | None = None, timeout: float = 40.0) -> Any:
    status, data = post_json_status(url, payload, headers=headers, timeout=timeout)
    if status >= 400:
        raise DownloadError(f"请求失败: {url} (HTTP {status}: {data})")
    return data


def post_form(url: str, form: dict[str, str], timeout: float = 40.0) -> tuple[int, Any]:
    """POST 表单，返回 (状态码, JSON)。OAuth 的错误响应也带 JSON，需要读取。"""
    body = urllib.parse.urlencode(form).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        with _open(url, data=body, headers=headers, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:
            pass
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            payload = {"error": f"http_{exc.code}", "error_description": raw.decode("utf-8", "replace")[:300]}
        return exc.code, payload
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as exc:
        raise DownloadError(f"请求失败: {url} ({exc})") from exc


def download_file(
    url: str,
    dest: Path,
    sha1: str | None = None,
    size: int | None = None,
    progress: Progress | None = None,
    retries: int = 3,
    timeout: float = 40.0,
) -> int:
    """下载单个文件到 dest，返回本次实际下载的字节数（跳过时为 0）。"""
    if file_matches(dest, sha1, size):
        return 0
    if progress is not None and progress.cancelled:
        raise DownloadError("操作已取消")

    ensure_dir(dest.parent)
    last_error: Exception | None = None
    part_suffix = f".part{os.getpid()}-{threading.get_ident()}"

    for attempt in range(1, retries + 1):
        part = dest.with_name(dest.name + part_suffix)
        received = 0
        success = False
        digest = hashlib.sha1() if sha1 else None
        try:
            with _open(url, timeout=timeout) as response:
                with part.open("wb") as fh:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        received += len(chunk)
                        if digest is not None:
                            digest.update(chunk)
                        if progress is not None:
                            progress.advance(len(chunk))
                            if progress.cancelled:
                                raise DownloadError("操作已取消")
            if size is not None and received != size:
                raise DownloadError(f"大小不符（期望 {size}，实际 {received}）")
            if digest is not None and digest.hexdigest() != sha1.lower():
                raise DownloadError("SHA1 校验失败")
            os.replace(part, dest)
            success = True
            return received
        except urllib.error.HTTPError as exc:
            last_error = DownloadError(_http_error_detail(exc))
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError, DownloadError) as exc:
            last_error = exc
        finally:
            if not success:
                if progress is not None and received:
                    progress.advance(-received)
                try:
                    part.unlink()
                except OSError:
                    pass
        if attempt < retries:
            time.sleep(0.5 * attempt + random.random() * 0.5)

    raise DownloadError(f"下载失败: {url}\n  -> {last_error}")


def download_many(
    tasks: Iterable[DownloadTask],
    workers: int = 8,
    label: str = "下载",
    stream: TextIO | None = None,
    enabled: bool = True,
    timeout: float = 40.0,
    callback=None,
    cancel_event: threading.Event | None = None,
) -> dict[str, int]:
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadError("操作已取消")
    task_list = list(tasks)
    pending = [task for task in task_list if not file_matches(task.dest, task.sha1, task.size)]
    skipped = len(task_list) - len(pending)
    total = sum(task.size or 0 for task in pending)
    progress = (
        Progress(
            label,
            total,
            stream=stream,
            enabled=enabled,
            callback=callback,
            cancel_event=cancel_event,
        )
        if pending
        else None
    )
    if progress is None:
        return {"total": len(task_list), "skipped": skipped, "downloaded": 0, "failed": 0}

    errors: list[tuple[DownloadTask, Exception]] = []

    def run(task: DownloadTask) -> None:
        download_file(task.url, task.dest, task.sha1, task.size, progress, timeout=timeout)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
        futures = {pool.submit(run, task): task for task in pending}
        for future in as_completed(futures):
            exc = future.exception()
            if exc is not None:
                errors.append((futures[future], exc))

    progress.finish()
    if errors:
        lines = "\n".join(f"  - {task.dest}: {exc}" for task, exc in errors[:5])
        raise DownloadError(f"{len(errors)} 个文件下载失败：\n{lines}")

    return {
        "total": len(task_list),
        "skipped": skipped,
        "downloaded": len(pending),
        "failed": 0,
    }
