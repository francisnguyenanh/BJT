// Site-wide display preferences (theme, furigana size/color/visibility, main
// text size), persisted in localStorage so they survive navigation and
// reloads. Applied as early as possible (script is loaded in <head>, before
// body paint) to avoid a flash of the wrong theme.
(function () {
  var root = document.documentElement;

  function apply() {
    var theme = localStorage.getItem("bjt-theme") || "light";
    root.classList.toggle("dark", theme === "dark");

    var jpSize = localStorage.getItem("bjt-jp-size") || "17";
    root.style.setProperty("--jp-font-size", jpSize + "px");

    var furiSize = localStorage.getItem("bjt-furi-size") || "10";
    root.style.setProperty("--furigana-font-size", furiSize + "px");

    var furiColor = localStorage.getItem("bjt-furi-color") || "#059669";
    root.style.setProperty("--furigana-color", furiColor);

    var hideFurigana = localStorage.getItem("bjt-hide-furigana") === "1";
    root.classList.toggle("hide-furigana", hideFurigana);

    return { theme: theme, jpSize: jpSize, furiSize: furiSize, furiColor: furiColor, hideFurigana: hideFurigana };
  }

  function toggleTheme() {
    var next = root.classList.contains("dark") ? "light" : "dark";
    localStorage.setItem("bjt-theme", next);
    apply();
    return next;
  }

  window.BJT = { apply: apply, toggleTheme: toggleTheme };
  apply();
})();

// Shared reading-page interactions (star/favorite buttons, font-size /
// furigana toolbar, collapsible sections) used by both the daily passage
// page and the Life Style reading page, so the two don't duplicate this
// logic.
(function () {
  function getVar(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }
  function setPref(key, value) {
    localStorage.setItem(key, value);
    window.BJT.apply();
  }

  function loadStarred() {
    try { return JSON.parse(localStorage.getItem('bjt-starred') || '{}'); } catch (e) { return {}; }
  }
  function saveStarred(map) { localStorage.setItem('bjt-starred', JSON.stringify(map)); }

  // getContext() returns extra fields (e.g. {date, length, pageLevel, title}
  // or {source, title}) merged into each starred entry so the review page
  // can show where a term came from.
  function initStarButtons(getContext) {
    const starred = loadStarred();
    document.querySelectorAll('.star-btn').forEach(btn => {
      const key = btn.dataset.kind + ':' + btn.dataset.term;
      if (starred[key]) { btn.classList.add('starred'); btn.textContent = '★'; }

      btn.addEventListener('click', () => {
        const map = loadStarred();
        if (map[key]) {
          delete map[key];
          btn.classList.remove('starred');
          btn.textContent = '☆';
        } else {
          map[key] = Object.assign({
            kind: btn.dataset.kind,
            term: btn.dataset.term,
            reading: btn.dataset.reading || '',
            meaning: btn.dataset.meaning || '',
            example: btn.dataset.example || '',
            structure: btn.dataset.structure || '',
            wordLevel: btn.dataset.wordLevel || '',
            savedAt: Date.now()
          }, getContext ? getContext() : {});
          btn.classList.add('starred');
          btn.textContent = '★';
        }
        saveStarred(map);
      });
    });
  }

  function initSectionToggles() {
    document.querySelectorAll('.section-header').forEach(header => {
      header.addEventListener('click', () => {
        const body = document.getElementById(header.dataset.toggle);
        body.classList.toggle('collapsed');
        header.classList.toggle('collapsed');
      });
    });
  }

  function initReadingToolbar() {
    document.querySelector('[data-action="jp-inc"]').addEventListener('click', () => {
      const size = Math.min(parseInt(getVar('--jp-font-size', '17px'), 10) + 1, 28);
      setPref('bjt-jp-size', size);
    });
    document.querySelector('[data-action="jp-dec"]').addEventListener('click', () => {
      const size = Math.max(parseInt(getVar('--jp-font-size', '17px'), 10) - 1, 12);
      setPref('bjt-jp-size', size);
    });
    document.querySelector('[data-action="furi-inc"]').addEventListener('click', () => {
      const size = Math.min(parseInt(getVar('--furigana-font-size', '10px'), 10) + 1, 18);
      setPref('bjt-furi-size', size);
    });
    document.querySelector('[data-action="furi-dec"]').addEventListener('click', () => {
      const size = Math.max(parseInt(getVar('--furigana-font-size', '10px'), 10) - 1, 6);
      setPref('bjt-furi-size', size);
    });
    document.getElementById('furi-toggle').addEventListener('click', () => {
      const hidden = document.documentElement.classList.contains('hide-furigana');
      setPref('bjt-hide-furigana', hidden ? '0' : '1');
    });
    document.querySelectorAll('.swatch').forEach(sw => {
      sw.addEventListener('click', () => setPref('bjt-furi-color', sw.dataset.color));
    });
  }

  // Play/pause button for the AI-narrated audio of a reading. The <audio>
  // element's src is only set on first click (lazy), so opening a page
  // never triggers text-to-speech generation on its own — only actually
  // pressing play does. After that, the browser/mobile OS caches the
  // audio file itself (server sends a long-lived immutable Cache-Control
  // header), so replaying the same reading later doesn't re-fetch it.
  function initTtsButton() {
    const btn = document.getElementById('tts-play');
    const audioEl = document.getElementById('tts-audio');
    if (!btn || !audioEl) return;
    let loading = false;

    btn.addEventListener('click', () => {
      if (loading) return;
      if (!audioEl.src) {
        loading = true;
        btn.disabled = true;
        btn.textContent = '⏳ Đang tạo audio...';
        audioEl.src = btn.dataset.src;
        audioEl.play().catch(() => {});
        return;
      }
      if (audioEl.paused) audioEl.play(); else audioEl.pause();
    });
    audioEl.addEventListener('playing', () => {
      loading = false;
      btn.disabled = false;
      btn.textContent = '⏸ Tạm dừng';
    });
    audioEl.addEventListener('pause', () => {
      if (!loading) btn.textContent = '🔊 Nghe bài đọc';
    });
    audioEl.addEventListener('ended', () => {
      btn.textContent = '🔊 Nghe bài đọc';
    });
    audioEl.addEventListener('error', () => {
      loading = false;
      btn.disabled = false;
      btn.textContent = '⚠️ Lỗi tạo audio, thử lại';
    });
  }

  window.BJT.loadStarred = loadStarred;
  window.BJT.saveStarred = saveStarred;
  window.BJT.initStarButtons = initStarButtons;
  window.BJT.initSectionToggles = initSectionToggles;
  window.BJT.initReadingToolbar = initReadingToolbar;
  window.BJT.initTtsButton = initTtsButton;
})();
