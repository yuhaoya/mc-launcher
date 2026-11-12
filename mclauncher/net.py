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


def _bundled_ca_file() -> Path | None:
    """随应用分发的 CA 证书包。

    老系统（尤其是停止更新的 Windows 7）根证书库缺少 2017 年后签发的根证书，
    例如 Mojang 现在用 "Microsoft RSA Root Certificate Authority 2017"，
    直接校验会失败。这里优先使用内置的 CA 包，找不到才退回系统证书库。
    """
    candidates = [
        Path(__file__).with_name("assets") / "cacert.pem",
        Path(sys._MEIPASS) / "mclauncher" / "assets" / "cacert.pem" if hasattr(sys, "_MEIPASS") else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _make_ssl_context() -> ssl.SSLContext:
    """构造 SSL 上下文。

    内置 CA 包 + 系统根证书库合并加载：
    - 内置包带来 2017 年后的新根证书（Mojang/Microsoft 在用）
    - 系统库覆盖企业代理、杀毒软件注入的私有根证书
    两者各缺一半，合并后覆盖面最广。

    应急开关：``MCL_INSECURE_TLS=1`` 或命令行 ``--insecure-tls``
    会关闭证书校验，用于代理无法绕过的情况（会显著降低安全性）。
    """
    context = ssl.create_default_context()
    ca_file = _bundled_ca_file()
    if ca_file is not None:
        try:
            context.load_verify_locations(cafile=str(ca_file))
        except (ssl.SSLError, OSError):
            pass

    # 老系统可能需要放宽到 TLS1.2（Mojang 已不支持更低版本）
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    except (AttributeError, ValueError):
        pass

    if os.environ.get("MCL_INSECURE_TLS") == "1":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    return context


_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """延迟创建 SSL 上下文，允许调用方先设置 ``MCL_INSECURE_TLS``。"""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = _make_ssl_context()
    return _SSL_CONTEXT


_JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


@dataclass
class DownloadTask:
    url: str
    dest: Path
    sha1: str | None = None
    size: int | None = None
    fallbacks: tuple[str, ...] = ()


def with_fallback(primary: str, official: str) -> tuple[str, tuple[str, ...]]:
    """构造 (主地址, 备用地址列表)。

    镜像转换后地址会变，原官方地址就是天然的备用源：镜像挂了就回退官方，
    避免一个镜像服务不可用导致整个安装失败。
    """
    if official and official != primary:
        return primary, (official,)
    return primary, ()


def apply_mirror_task(task: DownloadTask, mirror_func) -> DownloadTask:
    """把任务地址替换成镜像地址，同时保留官方地址作为回退。"""
    original = task.url
    mirrored = mirror_func(original)
    if mirrored == original:
        return task
    fallbacks = tuple(dict.fromkeys((*task.fallbacks, original)))
    return DownloadTask(mirrored, task.dest, task.sha1, task.size, fallbacks)


def _open(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 30.0):
    merged = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        merged.update({k: v for k, v in headers.items() if v is not None})
    request = urllib.request.Request(url, data=data, headers=merged, method="POST" if data is not None else "GET")
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", "replace")
    except Exception:
        body = ""
    return f"HTTP {exc.code} {exc.reason}" + (f": {body[:300]}" if body.strip() else "")


def _describe_error(exc: Exception) -> str:
    """把底层异常翻译成可操作的提示（尤其是老系统上的 TLS 问题）。"""
    text = str(exc)
    cause = getattr(exc, "reason", None)
    if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            "HTTPS 证书校验失败：系统根证书可能过旧（Windows 7 常见），"
            "或网络中的代理/杀毒软件正在替换证书。"
            "启动器已内置新版 CA 证书包，请确认程序目录完整；"
            "若仍失败，请检查系统时间、代理设置或关闭 HTTPS 扫描后重试。"
        )
    if isinstance(cause, ssl.SSLError) or "SSL" in text:
        return f"TLS 握手失败（{text}）。可能是网络代理或系统加密组件过旧。"
    if "getaddrinfo" in text or "Name or service not known" in text:
        return "域名解析失败，请检查网络连接或 DNS 设置。"
    if isinstance(cause, (TimeoutError,)) or "timed out" in text:
        return "连接超时，请检查网络或代理设置。"
    return text


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
    raise DownloadError(f"请求失败: {url} ({_describe_error(last_error) if last_error else '未知错误'})")


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
    raise DownloadError(f"请求失败: {url} ({_describe_error(last_error) if last_error else '未知错误'})")


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
    fallbacks: tuple[str, ...] | list[str] = (),
) -> int:
    """下载单个文件到 dest，返回本次实际下载的字节数（跳过时为 0）。

    ``fallbacks`` 里的地址会在主地址反复失败后依次尝试，
    用于「镜像优先、官方兜底」的场景。
    """
    if file_matches(dest, sha1, size):
        return 0
    if progress is not None and progress.cancelled:
        raise DownloadError("操作已取消")

    candidates = [url]
    for extra in fallbacks:
        if extra and extra not in candidates:
            candidates.append(extra)

    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        try:
            return _download_one(
                candidate, dest, sha1, size, progress, retries, timeout
            )
        except DownloadError as exc:
            last_error = exc
            if index + 1 < len(candidates):
                if progress is not None and progress.cancelled:
                    raise DownloadError("操作已取消") from exc
                time.sleep(0.6)

    raise DownloadError(f"下载失败: {url}\n  -> {last_error}")


def _download_one(
    url: str,
    dest: Path,
    sha1: str | None,
    size: int | None,
    progress: Progress | None,
    retries: int,
    timeout: float,
) -> int:
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

    raise DownloadError(f"{url}\n  -> {last_error}")


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
        download_file(
            task.url,
            task.dest,
            task.sha1,
            task.size,
            progress,
            timeout=timeout,
            fallbacks=task.fallbacks,
        )

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
