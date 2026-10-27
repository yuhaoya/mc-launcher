"""mclauncher - 一个轻量的 Minecraft 命令线启动器。

只使用 Python 标准库，支持：
  * 从 Mojang 官方源下载并安装任意正式版 / 快照
  * 自动补全 libraries、natives、assets、日志配置
  * 自动检测 / 下载 Mojang 官方 Java 运行时
  * 离线账号与微软正版账号（设备码登录）
  * 生成并执行正确的 JVM / 游戏参数
"""

__version__ = "1.0.0"
APP_NAME = "mclauncher"
