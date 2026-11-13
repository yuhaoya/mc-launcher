# Micalith Launcher 官网

纯静态站点，没有任何构建步骤，也没有外部依赖（不用 CDN、不用框架、不用网络字体）。

## 本地预览

直接双击 `index.html` 可以看，但用静态服务器更接近真实环境：

```powershell
python -m http.server 8765 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8765/index.html
```

## 目录

```
site/
  index.html          页面结构与全部文案
  styles.css          样式与主题变量
  script.js           主题切换、滚动进场、截图灯箱
  assets/
    app.png           应用图标
    shots/*.png       启动器界面截图
```

## URL 参数

方便截图、分享和排查：

| 参数 | 作用 |
| --- | --- |
| `?theme=light` / `?theme=dark` | 强制指定配色，覆盖系统偏好与本地记忆 |
| `?still=1` | 关闭滚动进场动画（截图、打印时用） |

正常访问时主题按「本地记忆 → 系统偏好」的顺序决定，右上角按钮可手动切换并记住选择。

## 发布前要做的事

1. **填下载地址**：`index.html` 里两个 `data-placeholder` 的按钮，把 `href="#"` 换成真实地址，例如：

   ```html
   <a class="btn btn-primary btn-block"
      href="https://github.com/yuhaoya/micalith-launcher/releases/download/v1.0.0/Micalith-Launcher.exe">
     下载 Micalith-Launcher.exe
   </a>
   ```

   没填之前点击会提示「下载地址待补充」，不会静默失败。

2. **核对版本号与大小**：页面上写的是 v1.0.0 / 约 90 MB，发新版时同步更新。

3. **补 SHA256**：`下载 → Windows 版` 下方的 `.dl-hint` 位置。

4. **换截图**（可选）：截图在 `assets/shots/`，保持文件名即可直接替换。当前统一使用浅色 + 绿色强调色。

## 部署

任意静态托管都能直接用：

- **GitHub Pages**：仓库 Settings → Pages → Source 选分支，目录填 `/site`
- **Cloudflare Pages / Vercel / Netlify**：构建命令留空，输出目录填 `site`
- **自有服务器**：把 `site/` 里的文件拷到 web 根目录

站内全部用相对路径，放在子目录（如 `example.com/launcher/`）也能正常工作。

## 设计说明

- 配色沿用启动器本身：中性层叠背景 + 单一强调色，浅色默认 `#107C10` 绿，深色自动提亮到 `#4BD44B`
- 间距、圆角、阴影幅度参照 Fluent Design 2，与客户端观感保持一致
- 进场动画用 CSS `animation` 而不是把元素初始设为 `opacity: 0`，所以即使 JS 不执行、或截图环境冻结动画，内容也始终可见
- 尊重 `prefers-reduced-motion`
