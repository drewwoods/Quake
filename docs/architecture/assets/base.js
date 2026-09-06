(function () {
  "use strict";

  /* ---------------------------------------------------- syntax highlight */
  var KW = /^(?:if|else|for|while|do|switch|case|default|break|continue|return|goto|sizeof|struct|union|enum|typedef|static|extern|const|register|volatile|void|int|float|double|char|short|long|unsigned|signed|qboolean|byte)$/;
  var TOKEN = /(\/\*[\s\S]*?\*\/|\/\/[^\n]*)|("(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*')|^[ \t]*(#[a-zA-Z]+)|\b(0[xX][0-9a-fA-F]+|\d+\.?\d*[fF]?)\b|\b([A-Za-z_][A-Za-z0-9_]*)\b/gm;

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function highlight(el) {
    var src = el.textContent, out = "", last = 0, m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(src)) !== null) {
      if (m.index > last) out += esc(src.slice(last, m.index));
      var t = m[0], cls = null;
      if (m[1]) cls = "tk-com";
      else if (m[2]) cls = "tk-str";
      else if (m[3]) { out += esc(t.slice(0, t.indexOf("#"))); t = m[3]; cls = "tk-pp"; }
      else if (m[4]) cls = "tk-num";
      else if (m[5]) {
        if (KW.test(m[5])) cls = "tk-kw";
        else if (/_t$/.test(m[5]) || /^[A-Z][A-Z0-9_]+$/.test(m[5])) cls = "tk-typ";
      }
      out += cls ? '<span class="' + cls + '">' + esc(t) + "</span>" : esc(t);
      last = m.index + m[0].length;
    }
    out += esc(src.slice(last));
    el.innerHTML = out;
  }

  function highlightAsm(el) {
    var src = el.textContent;
    var token = /(\/\/[^\n]*)|(%(?:st\(\d\)|[a-z][a-z0-9]*))|(\$(?:0x[0-9a-fA-F]+|\d+))|^(\s*[A-Za-z_][A-Za-z0-9_]*:)|^([ \t]+[a-z][a-z0-9]*)/gm;
    var out = "", last = 0, m;
    while ((m = token.exec(src)) !== null) {
      out += esc(src.slice(last, m.index));
      var cls = m[1] ? "tk-com" : m[2] ? "tk-typ" : m[3] ? "tk-num" : m[4] ? "tk-pp" : "tk-kw";
      out += '<span class="' + cls + '">' + esc(m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    el.innerHTML = out + esc(src.slice(last));
  }

  var pending = [].slice.call(document.querySelectorAll("pre code.lang-c, pre code.lang-asm"));
  (function chunk() {
    var t0 = Date.now();
    while (pending.length && Date.now() - t0 < 40) {
      var el = pending.shift();
      if (el.classList.contains("lang-asm")) highlightAsm(el);
      else highlight(el);
    }
    if (pending.length) setTimeout(chunk, 0);
  })();

  /* ---------------------------------------------------- code fold */
  var FOLD_ALL_KEY = "lof-fold-all";

  function loadPref(key, fallback) {
    try {
      var v = localStorage.getItem(key);
      return v === null ? fallback : v === "1";
    } catch (e) { return fallback; }
  }
  function savePref(key, val) {
    try { localStorage.setItem(key, val ? "1" : "0"); } catch (e) {}
  }

  var codeFigs = [].slice.call(document.querySelectorAll("figure.code"));
  var globalFoldDefault = loadPref(FOLD_ALL_KEY, true);
  [].slice.call(document.querySelectorAll("details.code")).forEach(function (detail) { detail.open = !globalFoldDefault; });

  function setCollapsed(fig, bar, collapsed) {
    fig.classList.toggle("collapsed", collapsed);
    bar.setAttribute("aria-expanded", String(!collapsed));
  }

  codeFigs.forEach(function (fig) {
    var bar = fig.querySelector(".code-bar");
    if (!bar) return;
    var id = fig.dataset.foldId;
    var collapsed = loadPref(id ? "lof-fold-" + id : FOLD_ALL_KEY, globalFoldDefault);
    bar.setAttribute("role", "button");
    bar.setAttribute("tabindex", "0");
    setCollapsed(fig, bar, collapsed);
    function toggle() {
      var next = !fig.classList.contains("collapsed");
      setCollapsed(fig, bar, next);
      if (id) savePref("lof-fold-" + id, next);
    }
    bar.addEventListener("click", function (e) {
      // the file:line ref in the bar is a link out to GitHub; following it
      // must not also fold the snippet behind you
      if (e.target.closest && e.target.closest("a")) return;
      toggle();
    });
    bar.addEventListener("keydown", function (e) {
      if (e.target !== bar) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });

  var foldAllBtn = document.getElementById("fold-all-btn");
  if (foldAllBtn) {
    foldAllBtn.setAttribute("aria-pressed", String(globalFoldDefault));
    foldAllBtn.textContent = globalFoldDefault ? "Expand all code" : "Collapse all code";
    foldAllBtn.addEventListener("click", function () {
      var next = foldAllBtn.getAttribute("aria-pressed") !== "true";
      codeFigs.forEach(function (fig) {
        var bar = fig.querySelector(".code-bar");
        if (!bar) return;
        setCollapsed(fig, bar, next);
        var id = fig.dataset.foldId;
        if (id) savePref("lof-fold-" + id, next);
      });
      [].slice.call(document.querySelectorAll("details.code")).forEach(function (detail) { detail.open = !next; });
      savePref(FOLD_ALL_KEY, next);
      foldAllBtn.setAttribute("aria-pressed", String(next));
      foldAllBtn.textContent = next ? "Expand all code" : "Collapse all code";
    });
  }

  /* ---------------------------------------------------- nav filter */
  var search = document.getElementById("nav-search");
  var empty = document.getElementById("nav-empty");
  var navSecs = [].slice.call(document.querySelectorAll(".nav-sec"));

  search.addEventListener("input", function () {
    var q = search.value.trim().toLowerCase();
    var anyShown = false;
    navSecs.forEach(function (sec) {
      var items = [].slice.call(sec.querySelectorAll("li"));
      var titleHit = sec.querySelector("summary").textContent.toLowerCase().indexOf(q) > -1;
      var hits = 0;
      items.forEach(function (li) {
        var hit = !q || titleHit || li.textContent.toLowerCase().indexOf(q) > -1;
        li.classList.toggle("filtered-out", !hit);
        if (hit) hits++;
      });
      var show = !q || titleHit || hits > 0;
      sec.classList.toggle("filtered-out", !show);
      if (show) anyShown = true;
      if (q && show) sec.open = true;
      if (!q) sec.open = sec.dataset.sec === "sec-1";
    });
    empty.classList.toggle("on", !anyShown);
  });

  /* ---------------------------------------------------- scroll spy */
  var links = {}, heads = [];
  [].slice.call(document.querySelectorAll(".nav-sec li a")).forEach(function (a) {
    links[a.dataset.nav] = a;
  });
  [].slice.call(document.querySelectorAll("main h3[id], main h4[id]")).forEach(function (h) {
    if (links[h.id]) heads.push(h);
  });

  var current = null, ticking = false;
  function spy() {
    ticking = false;
    var best = null;
    for (var i = 0; i < heads.length; i++) {
      if (heads[i].getBoundingClientRect().top <= 120) best = heads[i]; else break;
    }
    var id = best ? best.id : null;
    if (id === current) return;
    if (current && links[current]) links[current].classList.remove("current");
    current = id;
    if (id && links[id]) {
      links[id].classList.add("current");
      var sec = links[id].closest(".nav-sec");
      if (sec && !sec.open && !search.value) {
        navSecs.forEach(function (s) { s.open = (s === sec); });
      }
    }
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(spy); }
  }, { passive: true });
  spy();

  /* ---------------------------------------------------- mobile rail */
  var rail = document.getElementById("rail");
  var railToggle = document.getElementById("rail-toggle");
  railToggle.addEventListener("click", function () {
    var open = rail.classList.toggle("open");
    railToggle.setAttribute("aria-expanded", String(open));
  });

  /* ---------------------------------------------------- diagram */
  var pipe = document.getElementById("pipe");
  if (!pipe) return;              /* guides without the frame map stop here */

  function applyMode(mode) {
    pipe.setAttribute("data-mode", mode);
    [].slice.call(pipe.querySelectorAll("[data-modes]")).forEach(function (g) {
      var on = g.getAttribute("data-modes").split(/\s+/).indexOf(mode) > -1;
      g.classList.toggle("dim", !on);
      if (g.classList.contains("stage")) {
        g.setAttribute("tabindex", on ? "0" : "-1");
        g.setAttribute("aria-disabled", on ? "false" : "true");
      }
    });
  }

  [].slice.call(document.querySelectorAll(".modeswitch button")).forEach(function (b) {
    b.addEventListener("click", function () {
      [].slice.call(document.querySelectorAll(".modeswitch button")).forEach(function (o) {
        o.setAttribute("aria-pressed", String(o === b));
      });
      applyMode(b.dataset.mode);
    });
  });

  function findHeading(secId, fragment) {
    var wrap = document.getElementById(secId + "-wrap");
    if (!wrap) return null;
    if (fragment) {
      var hs = wrap.querySelectorAll("[data-h]");
      var f = fragment.toLowerCase();
      for (var i = 0; i < hs.length; i++) {
        if (hs[i].getAttribute("data-h").toLowerCase().indexOf(f) > -1) return hs[i];
      }
    }
    return document.getElementById(secId);
  }

  function goTo(stage) {
    if (stage.classList.contains("dim")) return;
    var target = findHeading(stage.dataset.sec, stage.dataset.h);
    if (!target) return;
    var p = target.parentElement;
    while (p && p !== document.body) {
      if (p.tagName === "DETAILS") p.open = true;
      p = p.parentElement;
    }
    var navSec = document.querySelector('.nav-sec[data-sec="' + stage.dataset.sec + '"]');
    if (navSec) { navSecs.forEach(function (s) { s.open = (s === navSec); }); }
    target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    target.classList.remove("target-flash");
    void target.offsetWidth;
    target.classList.add("target-flash");
    if (history.replaceState && target.id) history.replaceState(null, "", "#" + target.id);
  }

  [].slice.call(pipe.querySelectorAll(".stage")).forEach(function (stage) {
    stage.addEventListener("click", function () { goTo(stage); });
    stage.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goTo(stage); }
    });
  });

  applyMode("listen");
})();
