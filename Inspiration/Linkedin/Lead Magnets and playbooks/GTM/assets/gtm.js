/* =============================================================================
   HypeLead GTM Playbook — behaviour (offline, no dependencies)
   -----------------------------------------------------------------------------
   1. Language switch  — flips data-lang EN<->CS, persists, swaps aria/title.
   2. Theme toggle     — flips data-theme light<->dark, persists.
   3. TOC              — active-section highlight + mobile open/collapse.
   All localStorage access is wrapped in try/catch: the page must never crash
   if storage is unavailable (private mode, file:// restrictions, etc.).
   ============================================================================= */
(function () {
  "use strict";

  var LANG_KEY = "hypelead-gtm-lang";
  var THEME_KEY = "hypelead-gtm-theme";
  var root = document.documentElement;

  /* -- tiny safe storage wrapper ---------------------------------------- */
  function readStore(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function writeStore(key, val) {
    try { window.localStorage.setItem(key, val); } catch (e) { /* no-op */ }
  }

  /* =====================================================================
     1. LANGUAGE
     ===================================================================== */
  function currentLang() {
    return root.getAttribute("data-lang") === "cs" ? "cs" : "en";
  }

  /* Swap aria-label / title on elements that carry a Czech alternate.
     Convention seeded by W0: data-cs-aria / data-cs-title hold the CS text;
     the default attribute holds the EN text. On first swap we stash EN into
     data-en-* so we can restore it when switching back. */
  function applyLangAttrs(lang) {
    var nodes = document.querySelectorAll("[data-cs-aria],[data-cs-title]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.hasAttribute("data-cs-aria")) {
        if (!el.hasAttribute("data-en-aria")) {
          el.setAttribute("data-en-aria", el.getAttribute("aria-label") || "");
        }
        el.setAttribute("aria-label",
          lang === "cs" ? el.getAttribute("data-cs-aria")
                        : el.getAttribute("data-en-aria"));
      }
      if (el.hasAttribute("data-cs-title")) {
        if (!el.hasAttribute("data-en-title")) {
          el.setAttribute("data-en-title", el.getAttribute("title") || "");
        }
        el.setAttribute("title",
          lang === "cs" ? el.getAttribute("data-cs-title")
                        : el.getAttribute("data-en-title"));
      }
    }
  }

  function setLang(lang, persist) {
    lang = lang === "cs" ? "cs" : "en";
    root.setAttribute("data-lang", lang);
    root.setAttribute("lang", lang === "cs" ? "cs" : "en");
    applyLangAttrs(lang);
    if (persist) writeStore(LANG_KEY, lang);
  }

  function toggleLang() {
    setLang(currentLang() === "cs" ? "en" : "cs", true);
  }

  /* =====================================================================
     2. THEME
     ===================================================================== */
  function effectiveTheme() {
    var t = root.getAttribute("data-theme");
    if (t === "dark" || t === "light") return t;
    // no explicit lock: follow OS
    try {
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
        return "dark";
      }
    } catch (e) { /* ignore */ }
    return "light";
  }

  function setTheme(theme, persist) {
    theme = theme === "dark" ? "dark" : "light";
    root.setAttribute("data-theme", theme);
    if (persist) writeStore(THEME_KEY, theme);
  }

  function toggleTheme() {
    setTheme(effectiveTheme() === "dark" ? "light" : "dark", true);
  }

  /* =====================================================================
     3. TOC — active highlight + mobile drawer
     ===================================================================== */
  function initToc() {
    var toc = document.querySelector(".toc");
    if (!toc) return;
    var links = toc.querySelectorAll('a[href^="#"]');
    if (!links.length) return;

    var byId = {};
    var targets = [];
    for (var i = 0; i < links.length; i++) {
      var id = decodeURIComponent(links[i].getAttribute("href").slice(1));
      var sec = document.getElementById(id);
      if (sec) { byId[id] = links[i]; targets.push(sec); }
    }

    var current = null;
    function activate(id) {
      if (id === current) return;
      current = id;
      for (var k in byId) {
        if (Object.prototype.hasOwnProperty.call(byId, k)) {
          byId[k].classList.toggle("is-active", k === id);
        }
      }
    }

    if ("IntersectionObserver" in window) {
      var visible = {};
      var io = new IntersectionObserver(function (entries) {
        for (var j = 0; j < entries.length; j++) {
          var e = entries[j];
          visible[e.target.id] = e.isIntersecting ? e.intersectionRatio : 0;
        }
        var bestId = null, best = 0;
        for (var id in visible) {
          if (visible[id] > best) { best = visible[id]; bestId = id; }
        }
        if (bestId) activate(bestId);
      }, { rootMargin: "-56px 0px -70% 0px", threshold: [0, 0.25, 0.6, 1] });
      for (var t = 0; t < targets.length; t++) io.observe(targets[t]);
    }

    // clicking a link closes the mobile drawer
    toc.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a");
      if (a) document.body.classList.remove("toc-open");
    });
  }

  /* =====================================================================
     WIRING
     ===================================================================== */
  function wire() {
    // initial state (head scripts already set attributes for no-flash;
    // re-assert here so aria/title get localised and lang attr is normalised)
    var storedLang = readStore(LANG_KEY);
    setLang(storedLang === "cs" ? "cs" : (currentLang()), false);

    var storedTheme = readStore(THEME_KEY);
    if (storedTheme === "dark" || storedTheme === "light") setTheme(storedTheme, false);

    var langBtns = document.querySelectorAll(".lang-switch");
    for (var i = 0; i < langBtns.length; i++) {
      langBtns[i].addEventListener("click", toggleLang);
    }
    var themeBtns = document.querySelectorAll(".theme-toggle");
    for (var j = 0; j < themeBtns.length; j++) {
      themeBtns[j].addEventListener("click", toggleTheme);
    }

    var tocToggle = document.querySelector(".toc-toggle");
    if (tocToggle) {
      tocToggle.addEventListener("click", function () {
        if (window.matchMedia && window.matchMedia("(max-width: 960px)").matches) {
          document.body.classList.toggle("toc-open");
        } else {
          document.body.classList.toggle("toc-collapsed");
        }
      });
    }
    var scrim = document.querySelector(".toc-scrim");
    if (scrim) scrim.addEventListener("click", function () {
      document.body.classList.remove("toc-open");
    });

    initToc();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
