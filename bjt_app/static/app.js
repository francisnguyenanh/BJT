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
