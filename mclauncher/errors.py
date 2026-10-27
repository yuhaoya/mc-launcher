class LauncherError(Exception):
    """所有可预期的、应友好展示给用户的错误。"""


class DownloadError(LauncherError):
    """网络下载失败。"""


class AuthError(LauncherError):
    """账号认证失败。"""
