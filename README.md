# mclauncher

一个只用 Python 标准库写成的 Minecraft 命令行启动器。

它不依赖官方启动器，也不依赖任何第三方库：从 Mojang 官方源下载版本清单、客户端、依赖库、natives 和资源文件，自动准备 Java 运行时，然后用正确的 JVM / 游戏参数把游戏拉起来。

```
python mcl.py versions
python mcl.py install 1.21.5
python mcl.py launch 1.21.5 --offline Steve
```

## 双前端

除了命令行，还提供了两个独立的前端，共用同一套启动核心：

- **GUI** —— 基于 PySide6 + QFluentWidgets（Fluent Design 2）的桌面窗口，支持 Mica 毛玻璃效果、版本浏览、安装进度、微软账号设备码登录。
- **TUI** —— 基于 Textual 的终端界面，支持键盘快捷键与安装日志，适合服务器/SSH 场景。

### 运行 GUI

```powershell
python -m mclauncher.gui.app --game-dir "D:\mc" --config-dir "D:\mc\config"
```

选项：

| 参数 | 说明 |
| --- | --- |
| `--game-dir` | 游戏目录 |
| `--config-dir` | 配置目录 |
| `--page home\|versions\|downloads\|account\|settings` | 启动后直接进入的页面 |
| `--screenshot PATH` | 渲染窗口后保存 PNG 并退出（测试用） |

### 运行 TUI

```powershell
python -m mclauncher.tui.app --game-dir "D:\mc" --config-dir "D:\mc\config"
```

快捷键：`q` 退出 · `r` 刷新 · `1`–`5` 切换标签页 · `i` 安装 · `l` 启动。

## 功能

- **下载安装任意原版版本**：正式版、快照和远古版本都可以，`latest` / `latest-snapshot` 也可以；老版本的 `virtual` / `map_to_resources` 资源会自动整理。
- **完整补全文件**：客户端 jar、libraries、natives 解压、assets 对象、log4j 配置。
- **Java 自动管理**：扫描 `JAVA_HOME`、PATH、注册表、常见安装目录和 Mojang 运行时；找不到合适的 Java 时自动下载 Mojang 官方运行时（约 90–150MB）。
- **离线账号**：按 Java 的 `UUID.nameUUIDFromBytes` 规则生成离线 UUID。
- **微软正版登录**：设备码流程（浏览器输入 8 位代码），保存 refresh token，过期自动刷新。
- **参数构建**：支持 `arguments` / `minecraftArguments` 两种格式，处理 OS / 架构 / demo / 自定义分辨率规则，自动附加 log4j 配置。
- **并发下载 + 进度条**：SHA1 校验、已完成文件跳过、失败重试。
- **可 dry-run**：只打印最终启动命令，方便排查。

## 环境要求

- Python 3.10+（不需要 `pip install` 任何东西）
- Windows / Linux / macOS；主要在 Windows 上测试
- 能访问 Mojang 与微软的域名

## 快速开始

在项目目录下运行：

```powershell
# 1. 看看有哪些版本
python mcl.py versions

# 2. 安装 1.21.5（第一次会下载约 500MB）
python mcl.py install 1.21.5

# 3. 离线启动
python mcl.py launch 1.21.5 --offline Steve
```

默认游戏目录是 `%APPDATA%\.minecraft`（Linux/macOS 为 `~/.minecraft`），可以直接复用官方启动器已经装好的文件。想用独立目录：

```powershell
python mcl.py --dir "D:\mc" install 1.21.5
python mcl.py --dir "D:\mc" launch 1.21.5 --offline Steve
```

也可以把它当命令安装：

```powershell
pip install -e .
mcl versions
```

## 微软正版登录

```powershell
python mcl.py login
python mcl.py launch 1.21.5
```

运行 `login` 后会：

1. 请求微软设备码，打印 `https://www.microsoft.com/link` 和 8 位代码；
2. 自动尝试打开浏览器（加 `--no-browser` 可关闭，手动打开链接即可）；
3. 输入代码并授权后，启动器会验证 Xbox Live 与 Minecraft 档案；
4. 把 refresh token 保存到配置目录，后续启动静默刷新。

登录前请确认：

- 微软账号已经创建 Xbox Live 档案（没有的话去 xbox.com 登录一次）；
- 账号已购买 Minecraft: Java Edition，或已经完成从 Mojang 账号的迁移。

默认使用官方启动器的 Xbox LIVE 客户端 ID（`00000000402b5328`）连接 `login.live.com`。如果微软以后关闭这个入口，可以注册自己的 Azure 应用：

1. Azure Portal → Microsoft Entra ID → 应用注册 → 新注册；
2. 账户类型选择支持“个人 Microsoft 账户”；
3. 身份验证 → 允许公共客户端流（Allow public client flows）= 是；
4. 用环境变量或参数传入客户端 ID：

```powershell
$env:MCL_CLIENT_ID = "<你的客户端ID>"
python mcl.py login
# 或者
python mcl.py login --client-id "<你的客户端ID>"
```

自定义客户端 ID 会改走 `login.microsoftonline.com/consumers` 的 v2 设备码流程。如果流程需要调整，可以用 `MCL_AUTH_MODE=live|azure` 强制指定。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `python mcl.py versions [--type release\|snapshot\|all] [--limit N]` | 列出可安装版本，并标记已安装 |
| `python mcl.py install <版本> [--with-java] [--skip-assets] [--force]` | 下载并安装版本 |
| `python mcl.py list` | 列出已安装版本 |
| `python mcl.py launch <版本> --offline <名字>` | 离线启动 |
| `python mcl.py launch <版本>` | 使用已登录的微软账号启动 |
| `python mcl.py launch <版本> --dry-run` | 只打印启动命令 |
| `python mcl.py login` / `logout` / `whoami` | 微软账号管理 |
| `python mcl.py java` | 查看检测到的 Java |
| `python mcl.py java --install 21` | 下载 Mojang 的 Java 21 运行时 |
| `python mcl.py dir` | 显示游戏/配置目录 |

### 启动选项

```powershell
python mcl.py launch 1.21.5 --offline Steve `
  --memory 6G `
  --width 1280 --height 720 `
  --jvm-arg "-Dfoo=bar" `
  --game-arg "--fullscreen"
```

| 参数 | 说明 |
| --- | --- |
| `--offline <名字>` | 离线模式，最多 16 个字符，不能包含空格 |
| `--demo` | 试玩模式 |
| `--width` / `--height` | 自定义窗口分辨率 |
| `--memory` | 最大堆内存，支持 `4096` / `4G` / `512M` |
| `--java <路径>` | 手动指定 java.exe |
| `--jvm-arg` / `--game-arg` | 追加参数，可重复 |
| `--no-install` | 未安装时不自动下载 |
| `--no-auto-java` | 缺少 Java 时不自动下载 |
| `--dry-run` | 只打印命令，不启动 |

## 目录结构

```
<游戏目录>/
  versions/<版本>/<版本>.json   版本元数据
  versions/<版本>/<版本>.jar    客户端
  versions/<版本>/natives/      老版本解压出来的 native 库
  libraries/                    Maven 依赖
  assets/indexes/               资源索引
  assets/objects/               资源对象（按 SHA1 存放）
  assets/log_configs/           log4j 配置
  runtime/                      Mojang Java 运行时
  logs/                         游戏日志

<配置目录>/                     默认 %APPDATA%\mclauncher
  config.json                   游戏目录、Java、内存、账号 token
  cache/version_manifest_v2.json
```

配置目录可以用 `MCL_CONFIG_DIR` 或 `--config-dir` 覆盖。

## 工作方式（简要）

1. 读取 `version_manifest_v2.json`，拿到目标版本的 JSON 地址；
2. 把 JSON 存到 `versions/<id>/<id>.json`；
3. 按 `libraries[].rules` 过滤当前系统，下载 artifact 和 native classifier；
4. 老版本（带 `natives` 字段）解压到 `versions/<id>/natives`，新版本（1.19+）的 natives 直接进 classpath，由 LWJGL 自己解压；
5. 下载资源索引和所有 objects，必要时映射到 `assets/virtual/<id>` 或 `resources/`；
6. 下载 log4j 配置；
7. 启动时计算 classpath、替换 `${...}` 变量、处理 `arguments` 规则，拼接 JVM 与游戏参数；
8. `Popen` 启动游戏，等待退出。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖规则匹配、Maven 坐标、离线 UUID、启动命令构建、natives 解压、Java 运行时选择。

## 已知限制

- 只支持**原版**。带 `inheritsFrom` 的 Forge / Fabric / Quilt 版本会明确报错；当前没有模组加载器安装功能。
- 1.6 以前的老版本只做了基础兼容（legacy 参数、`resources/` 资源映射），未逐一实机验证；建议优先使用 1.12.2 及以上版本。
- 不实现自动更新、版本隔离、Mod 管理、皮肤、多人服务器列表等启动器周边功能。
- 不做 token 加密，`config.json` 里的 refresh token 是明文，注意不要分享这个文件。
- 资源文件较多，第一次安装会下载几千个小文件，耗时取决于网络。
- 只在 Windows 上做了完整验证；Linux/macOS 的路径与 Java 检测逻辑已做兼容，但未实机测试。

## 许可

MIT
