// Dashboard keyboard shortcuts + UI helpers
//
// Highlights one row at a time (j/k navigation), lets the user log
// outcomes with single-key shortcuts (i/l/v/n/x/b), expands the "why"
// panel (e), opens the property page (o), or shows help (?).

(function () {
  "use strict";

  const SHORTCUT_TO_OUTCOME = {
    // Call-mode outcomes
    i: { call: "interested",     knock: "interested" },
    l: { call: "talk_later",     knock: "talk_later" },
    v: { call: "left_voicemail", knock: "left_flyer" },
    n: { call: "no_answer",      knock: "nobody_home" },
    x: { call: "not_interested", knock: "not_interested" },
    b: { call: "bad_number",     knock: null }, // bad-number only valid for calls
  };

  function isTyping(target) {
    if (!target) return false;
    const tag = (target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" ||
           target.isContentEditable;
  }

  function visibleRows() {
    return Array.from(document.querySelectorAll("tr.queue-row[data-parcel-id]"));
  }

  function activeRow() {
    return document.querySelector("tr.queue-row.is-active");
  }

  function moveActive(delta) {
    const rows = visibleRows();
    if (!rows.length) return;
    let i = rows.findIndex(r => r.classList.contains("is-active"));
    if (i === -1) i = (delta > 0 ? -1 : 0);
    const next = Math.max(0, Math.min(rows.length - 1, i + delta));
    rows.forEach(r => r.classList.remove("is-active"));
    rows[next].classList.add("is-active");
    rows[next].scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function getMode() {
    const tab = document.querySelector(".mode-tab.active");
    return tab ? tab.dataset.mode : "call";
  }

  function clickOutcome(row, outcome) {
    if (!row || !outcome) return;
    const btn = row.querySelector(`button[data-outcome="${outcome}"]`);
    if (btn) btn.click();
  }

  function toggleDetail(row) {
    if (!row) return;
    const btn = row.querySelector(".detail-toggle");
    if (btn) btn.click();
  }

  window.toggleRowDetail = function (btn) {
    const targetId = btn.getAttribute("data-row-id");
    const url = btn.getAttribute("data-detail-url");
    const target = document.getElementById(targetId);
    if (!target || !url) return;
    const next = target.nextElementSibling;
    if (next && next.classList.contains("row-detail")) {
      next.remove();
      btn.textContent = "▸ Why?";
      return;
    }
    btn.textContent = "▾ Why?";
    if (window.htmx) {
      window.htmx.ajax("GET", url, { target: "#" + targetId, swap: "afterend" });
    }
  };

  function openProperty(row) {
    if (!row) return;
    const link = row.querySelector("a.property-link");
    if (link) window.open(link.href, "_blank");
  }

  function showHelp() {
    document.getElementById("kb-help-modal").classList.remove("hidden");
  }

  function hideHelp() {
    document.getElementById("kb-help-modal").classList.add("hidden");
  }

  document.addEventListener("keydown", function (ev) {
    if (isTyping(ev.target)) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const key = ev.key;
    if (key === "j") { ev.preventDefault(); moveActive(1); return; }
    if (key === "k") { ev.preventDefault(); moveActive(-1); return; }
    if (key === "e") { ev.preventDefault(); toggleDetail(activeRow()); return; }
    if (key === "o") { ev.preventDefault(); openProperty(activeRow()); return; }
    if (key === "?") { ev.preventDefault(); showHelp(); return; }
    if (key === "Escape") {
      const modal = document.getElementById("kb-help-modal");
      if (modal && !modal.classList.contains("hidden")) { hideHelp(); return; }
      // collapse expanded detail rows
      document.querySelectorAll("tr.row-detail").forEach(r => r.remove());
      return;
    }
    const k = key.toLowerCase();
    const mapping = SHORTCUT_TO_OUTCOME[k];
    if (mapping) {
      ev.preventDefault();
      const mode = getMode();
      const outcome = mapping[mode];
      if (!outcome) return;
      const row = activeRow();
      if (row) {
        clickOutcome(row, outcome);
        // After logging, advance to next row
        setTimeout(() => moveActive(1), 150);
      }
    }
  });

  document.addEventListener("click", function (ev) {
    if (ev.target && ev.target.id === "kb-help-trigger") {
      ev.preventDefault();
      showHelp();
    }
  });

  // After HTMX swaps in a new fragment, re-highlight if no active row,
  // and refresh the bulk-bar state (new content = no checkboxes selected).
  document.body.addEventListener("htmx:afterSwap", function () {
    if (!activeRow()) {
      const first = visibleRows()[0];
      if (first) first.classList.add("is-active");
    }
    if (window.updateBulkBar) window.updateBulkBar();
  });

  // On initial load, highlight the first row so j/k work immediately.
  document.addEventListener("DOMContentLoaded", function () {
    const first = visibleRows()[0];
    if (first) first.classList.add("is-active");
  });

  // ----- County chip removal helper (used inline by chips) -----
  window.removeCountyChip = function (county) {
    const form = document.getElementById("filter-form");
    if (!form) return;
    form.querySelectorAll(`input[name="counties"][value="${county}"]`)
        .forEach(el => el.remove());
    htmx.trigger(form, "change");
  };

  // ----- County chip add helper (autocomplete adds hidden input) -----
  window.addCountyChip = function (county) {
    const form = document.getElementById("filter-form");
    if (!form || !county) return;
    if (form.querySelector(`input[name="counties"][value="${county}"]`)) return;
    const inp = document.createElement("input");
    inp.type = "hidden";
    inp.name = "counties";
    inp.value = county;
    form.appendChild(inp);
    htmx.trigger(form, "change");
  };

  // ----- Bulk select helpers -----
  window.updateBulkBar = function () {
    const checked = document.querySelectorAll("input.bulk-check:checked").length;
    const bar = document.getElementById("bulk-bar");
    const cnt = document.getElementById("bulk-count");
    if (!bar) return;
    if (checked > 0) {
      bar.classList.remove("hidden");
      if (cnt) cnt.textContent = checked;
    } else {
      bar.classList.add("hidden");
    }
  };

  window.clearBulkSelection = function () {
    document.querySelectorAll("input.bulk-check:checked").forEach(c => c.checked = false);
    window.updateBulkBar();
  };

  window.applyBulkOutcome = function (outcome) {
    const checked = Array.from(document.querySelectorAll("input.bulk-check:checked"));
    if (!checked.length) return;
    const mode = getMode();
    const url = mode === "knock" ? "/doorknocks/log/bulk" : "/calls/log/bulk";
    const form = document.createElement("form");
    form.method = "post";
    form.action = url;
    function add(name, value) {
      const i = document.createElement("input");
      i.type = "hidden";
      i.name = name;
      i.value = value;
      form.appendChild(i);
    }
    add("outcome", outcome);
    checked.forEach(c => {
      const row = c.closest("tr");
      if (!row) return;
      add("parcel_ids", row.dataset.parcelId || "");
      add("counties", row.dataset.county || "");
      add("owners", row.dataset.owner || "");
      add("addrs", row.dataset.addr || "");
    });
    document.body.appendChild(form);
    form.submit();
  };
})();
