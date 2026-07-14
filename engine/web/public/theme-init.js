// Ratified "Ink & Emerald" is dark-only. Always apply `.dark` before React
// loads so there is never a flash of (or regression to) light mode.
(function () {
  document.documentElement.classList.add("dark");
})();
