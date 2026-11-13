// Micalith Launcher 官网交互
(function () {
  "use strict";

  const root = document.documentElement;
  const THEME_KEY = "micalith-site-theme";

  // ---------- 主题 ----------
  function preferredTheme() {
    // ?theme=light / ?theme=dark 可强制指定，方便分享链接和截图验证
    const forced = new URLSearchParams(location.search).get("theme");
    if (forced === "light" || forced === "dark") return forced;
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function setTheme(theme) {
    root.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      /* 隐私模式下 localStorage 会抛错，忽略即可 */
    }
  }

  setTheme(preferredTheme());

  const toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      setTheme(root.dataset.theme === "dark" ? "light" : "dark");
    });
  }

  // ---------- 导航滚动状态 ----------
  const nav = document.getElementById("nav");
  function onScroll() {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---------- 滚动进场 ----------
  // ?still=1 关闭进场动画，便于截图与打印
  const params = new URLSearchParams(location.search);
  const still = params.get("still") === "1" || params.has("still");

  const revealTargets = [
    ...document.querySelectorAll(".card"),
    ...document.querySelectorAll(".shot"),
    ...document.querySelectorAll(".dl-card"),
    ...document.querySelectorAll(".faq details"),
    ...document.querySelectorAll(".section-head"),
  ];

  if (still) {
    revealTargets.forEach((el) => el.classList.remove("reveal"));
  } else {
    revealTargets.forEach((el, i) => {
      el.classList.add("reveal");
      el.style.transitionDelay = `${Math.min(i % 6, 5) * 55}ms`;
    });
  }

  function revealAll() {
    revealTargets.forEach((el) => el.classList.add("in"));
  }

  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );
    revealTargets.forEach((el) => io.observe(el));
    // 兜底：无法滚动/截图环境下 IntersectionObserver 可能不回调，
    // 超时后直接显示，保证内容永远不隐形。
    window.setTimeout(revealAll, 1600);
  } else {
    revealAll();
  }

  // ---------- 截图灯箱 ----------
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = document.getElementById("lightboxImg");
  const lightboxCap = document.getElementById("lightboxCap");
  const lightboxClose = document.getElementById("lightboxClose");
  let lastFocused = null;

  function openLightbox(src, caption, alt) {
    if (!lightbox) return;
    lastFocused = document.activeElement;
    lightboxImg.src = src;
    lightboxImg.alt = alt || caption || "";
    lightboxCap.textContent = caption || "";
    lightbox.hidden = false;
    document.body.style.overflow = "hidden";
    lightboxClose.focus();
  }

  function closeLightbox() {
    if (!lightbox || lightbox.hidden) return;
    lightbox.hidden = true;
    lightboxImg.src = "";
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  document.querySelectorAll(".shot").forEach((figure) => {
    figure.addEventListener("click", () => {
      const img = figure.querySelector("img");
      openLightbox(
        figure.dataset.shot || (img && img.src),
        figure.dataset.caption || "",
        img && img.alt
      );
    });
  });

  if (lightboxClose) lightboxClose.addEventListener("click", closeLightbox);
  if (lightbox) {
    lightbox.addEventListener("click", (event) => {
      if (event.target === lightbox) closeLightbox();
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeLightbox();
  });

  // ---------- 下载占位提示 ----------
  // 发布时把真实地址填进 href 即可；未填时给个明确反馈，避免点了没反应。
  document.querySelectorAll("[data-placeholder]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (!link.getAttribute("href") || link.getAttribute("href") === "#") {
        event.preventDefault();
        const label = link.textContent.trim();
        const note = document.createElement("span");
        note.textContent = ` · ${link.dataset.placeholder}`;
        if (!link.dataset.noted) {
          link.dataset.noted = "1";
          link.appendChild(note);
          setTimeout(() => {
            note.remove();
            delete link.dataset.noted;
          }, 2600);
        }
      }
    });
  });
})();
