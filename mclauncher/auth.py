from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable, TextIO

from .config import Config
from .errors import AuthError, DownloadError
from .net import get_json, post_form, post_json, post_json_status

DEVICE_CODE_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
LIVE_CONNECT_URL = "https://login.live.com/oauth20_connect.srf"
LIVE_TOKEN_URL = "https://login.live.com/oauth20_token.srf"
LIVE_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
SCOPE = "XboxLive.signin offline_access"
DEFAULT_CLIENT_ID = "00000000402b5328"

_XERR_MESSAGES = {
    2148916233: "该微软账号还没有 Xbox Live 档案，请先登录 xbox.com 创建档案。",
    2148916235: "该账号所在地区/国家不支持 Xbox Live。",
    2148916236: "该账号需要通过成人身份验证。",
    2148916237: "该账号需要通过成人身份验证。",
    2148916238: "该账号是未成年账号，需要先加入 Microsoft 家庭组。",
}


@dataclass
class Account:
    name: str
    uuid: str
    access_token: str
    user_type: str  # "msa" 或 "legacy"
    xuid: str = ""
    client_id: str = ""
    expires_at: float = 0.0
    offline: bool = False

    @property
    def uuid_hex(self) -> str:
        return self.uuid.replace("-", "")


def offline_uuid(name: str) -> str:
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def offline_account(name: str) -> Account:
    name = name.strip()
    if not name:
        raise AuthError("离线用户名不能为空")
    if len(name) > 16:
        raise AuthError("离线用户名最多 16 个字符")
    if re.search(r"\s", name):
        raise AuthError("离线用户名不能包含空格")
    fake_token = hashlib.sha1(f"offline:{name}".encode("utf-8")).hexdigest()
    return Account(
        name=name,
        uuid=offline_uuid(name),
        access_token=fake_token,
        user_type="legacy",
        offline=True,
    )


# ----------------------------------------------------------------------
# 微软设备码登录
# ----------------------------------------------------------------------
def _client_id(config: Config, explicit: str | None = None) -> str:
    return (
        explicit
        or os.environ.get("MCL_CLIENT_ID")
        or config.get("client_id")
        or DEFAULT_CLIENT_ID
    )


def _default_mode(client_id: str) -> str:
    """默认客户端 ID 是官方启动器的 Xbox LIVE 客户端，走 login.live.com。

    如果用户通过 MCL_CLIENT_ID / --client-id 提供了自己注册的 Azure 应用，
    则走 Microsoft Entra 的 v2 设备码流程。
    """
    override = os.environ.get("MCL_AUTH_MODE")
    if override in ("live", "azure"):
        return override
    return "live" if client_id == DEFAULT_CLIENT_ID else "azure"


def _request_device_code(client_id: str, mode: str, tenant: str) -> dict[str, Any]:
    if mode == "live":
        status, data = post_form(
            LIVE_CONNECT_URL,
            {
                "client_id": client_id,
                "scope": LIVE_SCOPE,
                "response_type": "device_code",
            },
        )
    else:
        status, data = post_form(
            DEVICE_CODE_URL.format(tenant=tenant),
            {"client_id": client_id, "scope": SCOPE},
        )
    if status != 200:
        message = data.get("error_description") or data.get("error") or f"HTTP {status}"
        raise AuthError(f"无法获取设备码: {message}")
    return data


def _poll_token(
    client_id: str,
    mode: str,
    tenant: str,
    device_code: str,
    interval: int,
    expires_in: int,
    stream: TextIO,
    on_status: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    deadline = time.time() + expires_in
    stream.write("    等待授权 ")
    stream.flush()
    if on_status is not None:
        on_status("waiting")
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise AuthError("登录已取消")
        time.sleep(max(1, interval))
        if cancel_event is not None and cancel_event.is_set():
            raise AuthError("登录已取消")
        token_url = LIVE_TOKEN_URL if mode == "live" else TOKEN_URL.format(tenant=tenant)
        status, data = post_form(
            token_url,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )
        if status == 200 and data.get("access_token"):
            stream.write(" 完成\n")
            stream.flush()
            if on_status is not None:
                on_status("authorized")
            return data
        error = data.get("error")
        if error == "authorization_pending":
            stream.write(".")
            stream.flush()
            continue
        if error == "slow_down":
            interval += 5
            stream.write(".")
            stream.flush()
            continue
        if error == "authorization_declined":
            raise AuthError("用户拒绝了授权")
        if error == "expired_token":
            raise AuthError("设备码已过期，请重新登录")
        detail = data.get("error_description") or error or f"HTTP {status}"
        raise AuthError(f"登录失败: {detail}")
    raise AuthError("等待授权超时，请重新登录")


def login_device_code(
    config: Config,
    client_id: str | None = None,
    stream: TextIO | None = None,
    open_browser: bool = True,
    on_code: Callable[[dict], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    stream = stream or sys.stdout
    client_id = _client_id(config, client_id)
    mode = _default_mode(client_id)

    last_error: AuthError | None = None
    data: dict[str, Any] | None = None
    tenant = "consumers"
    tenants = ("consumers", "common") if mode == "azure" else ("",)
    for candidate in tenants:
        try:
            data = _request_device_code(client_id, mode, candidate)
            tenant = candidate or "live"
            break
        except AuthError as exc:
            last_error = exc
    if data is None:
        raise AuthError(
            f"微软设备码登录不可用。请确认客户端 ID 正确（当前: {client_id}），"
            f"或改用 --offline 离线启动。\n  详情: {last_error}"
        )

    verification_uri = data.get("verification_uri") or data.get("verification_url") or "https://microsoft.com/link"
    user_code = data.get("user_code", "")
    interval = int(data.get("interval") or 5)
    expires_in = int(data.get("expires_in") or 900)

    stream.write("\n")
    stream.write(f"    请在浏览器打开: {verification_uri}\n")
    stream.write(f"    输入代码:       {user_code}\n")
    stream.write(f"    有效期:         {expires_in // 60} 分钟\n\n")
    stream.flush()
    if on_code is not None:
        try:
            on_code(
                {
                    "verification_uri": verification_uri,
                    "user_code": user_code,
                    "expires_in": expires_in,
                }
            )
        except Exception:
            pass
    if open_browser:
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

    token = _poll_token(
        client_id,
        mode,
        tenant,
        data["device_code"],
        interval,
        expires_in,
        stream,
        on_status=on_status,
        cancel_event=cancel_event,
    )
    token["_client_id"] = client_id
    token["_mode"] = mode
    token["_tenant"] = tenant
    return token


def refresh_ms_token(
    config: Config,
    refresh_token: str,
    client_id: str | None = None,
    tenant: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    client_id = _client_id(config, client_id)
    stored = config.get("msa") or {}
    mode = mode or stored.get("mode") or _default_mode(client_id)
    tenant = tenant or stored.get("tenant") or "consumers"
    if mode == "live":
        status, data = post_form(
            LIVE_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": LIVE_SCOPE,
            },
        )
    else:
        status, data = post_form(
            TOKEN_URL.format(tenant=tenant),
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": SCOPE,
            },
        )
    if status != 200 or not data.get("access_token"):
        detail = data.get("error_description") or data.get("error") or f"HTTP {status}"
        raise AuthError(f"微软登录已失效，请重新运行 `mcl login`。\n  详情: {detail}")
    data["_client_id"] = client_id
    data["_tenant"] = tenant
    data["_mode"] = mode
    return data


# ----------------------------------------------------------------------
# Xbox Live -> Minecraft 服务
# ----------------------------------------------------------------------
def _xbox_user_token(ms_access_token: str) -> tuple[str, str]:
    status, data = post_json_status(
        XBL_URL,
        {
            "Properties": {"RpsTicket": f"d={ms_access_token}", "AuthMethod": "RPS"},
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        },
        headers={"x-xbl-contract-version": "1", "Accept": "application/json"},
    )
    if status != 200:
        err_msg = data.get("Message") if isinstance(data, dict) else data
        raise AuthError(f"Xbox Live 用户认证失败 (HTTP {status}): {err_msg}")
    try:
        return data["Token"], data["DisplayClaims"]["xui"][0]["uhs"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AuthError("Xbox Live 返回数据异常") from exc


def _xsts_token(xbl_token: str) -> tuple[str, str]:
    status, data = post_json_status(
        XSTS_URL,
        {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
        headers={"x-xbl-contract-version": "1", "Accept": "application/json"},
    )
    if status != 200:
        xerr = data.get("XErr") if isinstance(data, dict) else None
        try:
            xerr = int(xerr)
        except (TypeError, ValueError):
            pass
        message = _XERR_MESSAGES.get(xerr)
        if message:
            raise AuthError(f"Xbox 授权失败: {message}")
        raise AuthError(f"Xbox 授权失败 (HTTP {status}): {data.get('Message') or data}")
    try:
        token = data["Token"]
        claims = data["DisplayClaims"]["xui"][0]
        return token, str(claims.get("xid") or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AuthError("Xbox 授权返回数据异常") from exc


def authenticate_minecraft(ms_access_token: str) -> dict[str, Any]:
    """用微软 access token 换取 Minecraft 档案与 Minecraft access token。"""
    xbl_token, uhs = _xbox_user_token(ms_access_token)
    xsts_token, xuid = _xsts_token(xbl_token)
    try:
        mc = post_json(
            MC_LOGIN_URL,
            {"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
            headers={"Accept": "application/json"},
        )
    except DownloadError as exc:
        raise AuthError(f"Minecraft 服务登录失败: {exc}") from exc
    access_token = mc.get("access_token")
    if not access_token:
        raise AuthError("Minecraft 服务没有返回 access token")
    try:
        profile = get_json(MC_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})
    except DownloadError as exc:
        if "404" in str(exc):
            raise AuthError(
                "该微软账号没有 Minecraft: Java Edition 的档案（可能未购买或未迁移）。"
            ) from exc
        raise AuthError(f"读取 Minecraft 档案失败: {exc}") from exc
    if not profile.get("id") or not profile.get("name"):
        raise AuthError("该账号没有可用的 Minecraft Java 版档案")
    return {
        "access_token": access_token,
        "expires_at": time.time() + int(mc.get("expires_in") or 86400) - 60,
        "uuid": profile["id"],
        "name": profile["name"],
        "xuid": xuid,
    }


# ----------------------------------------------------------------------
# 配置持久化
# ----------------------------------------------------------------------
def _save(config: Config, data: dict[str, Any]) -> None:
    config.set("msa", data)
    config.save()


def login(
    config: Config,
    client_id: str | None = None,
    stream: TextIO | None = None,
    open_browser: bool = True,
    on_code: Callable[[dict], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Account:
    stream = stream or sys.stdout
    token = login_device_code(
        config,
        client_id,
        stream,
        open_browser=open_browser,
        on_code=on_code,
        on_status=on_status,
        cancel_event=cancel_event,
    )
    client = token["_client_id"]
    tenant = token["_tenant"]
    mode = token["_mode"]

    # 先保存 refresh token：即使后续 Xbox 步骤失败，也不用重新扫码。
    _save(
        config,
        {
            "client_id": client,
            "tenant": tenant,
            "mode": mode,
            "refresh_token": token.get("refresh_token"),
        },
    )
    stream.write("[*] 正在验证 Xbox / Minecraft 档案...\n")
    stream.flush()
    if on_status is not None:
        on_status("authenticating")
    mc = authenticate_minecraft(token["access_token"])
    data = {
        "client_id": client,
        "tenant": tenant,
        "mode": mode,
        "refresh_token": token.get("refresh_token"),
        "access_token": mc["access_token"],
        "expires_at": mc["expires_at"],
        "uuid": mc["uuid"],
        "name": mc["name"],
        "xuid": mc["xuid"],
    }
    _save(config, data)
    stream.write(f"[+] 登录成功: {mc['name']} ({mc['uuid']})\n")
    if on_status is not None:
        on_status("done")
    return Account(
        name=mc["name"],
        uuid=mc["uuid"],
        access_token=mc["access_token"],
        user_type="msa",
        xuid=mc["xuid"],
        client_id=client,
        expires_at=mc["expires_at"],
    )


def get_account(config: Config) -> Account:
    """读取已保存账号；必要时刷新微软 / Minecraft token。"""
    msa = config.get("msa") or {}
    refresh_token = msa.get("refresh_token")
    client_id = msa.get("client_id") or config.get("client_id") or DEFAULT_CLIENT_ID
    if not refresh_token:
        raise AuthError("还没有登录微软账号。请先运行 `mcl login`，或在启动时加 `--offline <名字>`。")

    if (
        msa.get("access_token")
        and float(msa.get("expires_at") or 0) > time.time() + 60
        and msa.get("uuid")
        and msa.get("name")
    ):
        return Account(
            name=msa["name"],
            uuid=msa["uuid"],
            access_token=msa["access_token"],
            user_type="msa",
            xuid=str(msa.get("xuid") or ""),
            client_id=client_id,
            expires_at=float(msa.get("expires_at") or 0),
        )

    try:
        token = refresh_ms_token(
            config,
            refresh_token,
            client_id,
            tenant=msa.get("tenant"),
            mode=msa.get("mode") or _default_mode(client_id),
        )
        mc = authenticate_minecraft(token["access_token"])
    except AuthError as exc:
        # 一旦刷新失败，直接清空坏掉的微软缓存，防止一直卡死
        logout(config)
        raise AuthError(f"微软账号已失效，请重新登录。详情: {exc}") from exc
    data = {
        "client_id": client_id,
        "tenant": token.get("_tenant") or msa.get("tenant") or "consumers",
        "mode": token.get("_mode") or msa.get("mode") or _default_mode(client_id),
        "refresh_token": token.get("refresh_token") or refresh_token,
        "access_token": mc["access_token"],
        "expires_at": mc["expires_at"],
        "uuid": mc["uuid"],
        "name": mc["name"],
        "xuid": mc["xuid"],
    }
    _save(config, data)
    return Account(
        name=mc["name"],
        uuid=mc["uuid"],
        access_token=mc["access_token"],
        user_type="msa",
        xuid=mc["xuid"],
        client_id=client_id,
        expires_at=mc["expires_at"],
    )


def cached_profile(config: Config) -> dict[str, Any] | None:
    msa = config.get("msa") or {}
    if not msa.get("name"):
        return None
    return {
        "name": msa.get("name"),
        "uuid": msa.get("uuid"),
        "expires_at": msa.get("expires_at"),
        "client_id": msa.get("client_id") or DEFAULT_CLIENT_ID,
        "tenant": msa.get("tenant") or "consumers",
        "mode": msa.get("mode") or _default_mode(msa.get("client_id") or DEFAULT_CLIENT_ID),
    }


def logout(config: Config) -> None:
    config.clear_msa()
