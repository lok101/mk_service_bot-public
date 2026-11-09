(function () {
  "use strict";

  var DEBOUNCE_MS = 350;
  var flushTimers = {};
  var inFlightFlushes = 0;
  var flushFailed = false;

  function qs(id) {
    return document.getElementById(id);
  }

  function hasPendingFlush() {
    return inFlightFlushes > 0 || Object.keys(flushTimers).length > 0;
  }

  function parseWeekdays(raw) {
    if (!raw) return [];
    return raw.split(",").map(function (part) {
      return part.trim();
    }).filter(Boolean);
  }

  function weekdaysFromRow(row) {
    var machineId = row.getAttribute("data-machine-id") || "";
    var days = [];
    for (var iso = 0; iso < 7; iso++) {
      var box = row.querySelector('input[name="wd-' + machineId + "-" + iso + '"]');
      if (box && box.checked) days.push(String(iso));
    }
    return days;
  }

  function syncRowWeekdaysAttr(row) {
    row.setAttribute("data-weekdays", weekdaysFromRow(row).join(","));
  }

  function sortedJoin(values) {
    return values.slice().sort().join(",");
  }

  function rowMatches(row, search, techFilter, dayFilter) {
    var machineId = (row.getAttribute("data-machine-id") || "").toLowerCase();
    var locationName = (row.getAttribute("data-location-name") || "").toLowerCase();
    var technicianId = row.getAttribute("data-technician-id") || "";
    var weekdays = parseWeekdays(row.getAttribute("data-weekdays") || "");

    if (search) {
      var hay = machineId + " " + locationName;
      if (hay.indexOf(search) === -1) return false;
    }
    if (techFilter === "unassigned") {
      if (technicianId !== "") return false;
    } else if (techFilter !== "all") {
      if (technicianId !== techFilter) return false;
    }
    if (dayFilter !== "all") {
      if (weekdays.indexOf(dayFilter) === -1) return false;
    }
    return true;
  }

  function notifyRowsUpdated() {
    window.dispatchEvent(new CustomEvent("roster:rows-updated"));
  }

  function applyFilters() {
    var searchEl = qs("roster-search");
    var techEl = qs("roster-technician-filter");
    var dayEl = qs("roster-weekday-filter");
    var countEl = qs("roster-visible-count");
    if (!searchEl || !techEl || !dayEl) return;

    var search = (searchEl.value || "").trim().toLowerCase();
    var techFilter = techEl.value || "all";
    var dayFilter = dayEl.value || "all";
    var rows = document.querySelectorAll("#roster-table tbody tr");
    var visible = 0;
    rows.forEach(function (row) {
      var show = rowMatches(row, search, techFilter, dayFilter);
      if (show) {
        row.removeAttribute("hidden");
        visible += 1;
      } else {
        row.setAttribute("hidden", "hidden");
      }
    });
    if (countEl) countEl.textContent = String(visible);
    notifyRowsUpdated();
  }

  function computeClientDirty() {
    var rows = document.querySelectorAll("#roster-table tbody tr");
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var tech = row.getAttribute("data-technician-id") || "";
      var appliedTech = row.getAttribute("data-applied-technician-id") || "";
      var weekdays = sortedJoin(parseWeekdays(row.getAttribute("data-weekdays") || ""));
      var appliedWeekdays = sortedJoin(
        parseWeekdays(row.getAttribute("data-applied-weekdays") || "")
      );
      if (tech !== appliedTech || weekdays !== appliedWeekdays) return true;
    }
    return false;
  }

  function setSaveButtonsDisabled(disabled) {
    var applyBtn = qs("roster-apply");
    var resetBtn = qs("roster-reset");
    var form = qs("roster-form");
    if (applyBtn) applyBtn.disabled = disabled;
    if (resetBtn) resetBtn.disabled = disabled;
    if (form) form.setAttribute("data-draft-dirty", disabled ? "false" : "true");
  }

  function refreshDirtyUi() {
    var dirty = computeClientDirty();
    setSaveButtonsDisabled(!dirty || hasPendingFlush() || flushFailed);
    var banner = qs("roster-dirty-banner");
    if (banner) {
      if (dirty) {
        banner.removeAttribute("hidden");
      } else {
        banner.setAttribute("hidden", "hidden");
      }
    }
  }

  function buildDraftFormData(row) {
    var machineId = row.getAttribute("data-machine-id") || "";
    var data = new URLSearchParams();
    data.append("machine_id", machineId);
    var sel = row.querySelector('select[name="technician-' + machineId + '"]');
    data.append("technician-" + machineId, sel ? sel.value || "" : "");
    for (var iso = 0; iso < 7; iso++) {
      var box = row.querySelector('input[name="wd-' + machineId + "-" + iso + '"]');
      if (box && box.checked) data.append("wd-" + machineId + "-" + iso, "on");
    }
    var expected = row.getAttribute("data-updated-at") || "";
    if (expected) data.append("expected_updated_at", expected);
    return data;
  }

  function updateExpectedTokens(row, updatedAt) {
    var machineId = row.getAttribute("data-machine-id") || "";
    row.setAttribute("data-updated-at", updatedAt);
    var hidden = row.querySelector(
      'input[name="expected_draft_updated_at-' + machineId + '"]'
    );
    if (hidden) hidden.value = updatedAt;
  }

  function flushDraft(row) {
    inFlightFlushes += 1;
    refreshDirtyUi();
    return fetch("/admin/roster/draft", {
      method: "POST",
      body: buildDraftFormData(row),
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (response.status === 409) {
          window.alert("Конфликт черновика — обновите страницу.");
          throw new Error("conflict");
        }
        if (!response.ok) {
          throw new Error("draft_failed");
        }
        return response.json();
      })
      .then(function (payload) {
        flushFailed = false;
        if (payload && payload.updated_at) {
          updateExpectedTokens(row, payload.updated_at);
        }
        refreshDirtyUi();
      })
      .catch(function (err) {
        if (err && err.message === "conflict") {
          return;
        }
        window.alert(
          "Не удалось сохранить черновик. Повторите правку или обновите страницу."
        );
        flushFailed = true;
        refreshDirtyUi();
      })
      .finally(function () {
        inFlightFlushes -= 1;
        refreshDirtyUi();
      });
  }

  function scheduleDraftFlush(row) {
    flushFailed = false;
    var machineId = row.getAttribute("data-machine-id") || "";
    if (flushTimers[machineId]) {
      window.clearTimeout(flushTimers[machineId]);
    }
    flushTimers[machineId] = window.setTimeout(function () {
      delete flushTimers[machineId];
      flushDraft(row);
    }, DEBOUNCE_MS);
    refreshDirtyUi();
  }

  function bindRowEditors() {
    document.querySelectorAll("#roster-table tbody select[name^='technician-']").forEach(
      function (sel) {
        sel.addEventListener("change", function () {
          var row = sel.closest("tr");
          if (!row) return;
          row.setAttribute("data-technician-id", sel.value || "");
          applyFilters();
          notifyRowsUpdated();
          refreshDirtyUi();
          scheduleDraftFlush(row);
        });
      }
    );
    document.querySelectorAll("#roster-table tbody input[type='checkbox'][name^='wd-']").forEach(
      function (box) {
        box.addEventListener("change", function () {
          var row = box.closest("tr");
          if (!row) return;
          syncRowWeekdaysAttr(row);
          applyFilters();
          notifyRowsUpdated();
          refreshDirtyUi();
          scheduleDraftFlush(row);
        });
      }
    );
  }

  function sortBy(key) {
    var tbody = document.querySelector("#roster-table tbody");
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    var attr = key === "machine-id" ? "data-machine-id" : "data-location-name";
    rows.sort(function (a, b) {
      var av = (a.getAttribute(attr) || "").toLowerCase();
      var bv = (b.getAttribute(attr) || "").toLowerCase();
      if (av < bv) return -1;
      if (av > bv) return 1;
      var aId = (a.getAttribute("data-machine-id") || "").toLowerCase();
      var bId = (b.getAttribute("data-machine-id") || "").toLowerCase();
      if (aId < bId) return -1;
      if (aId > bId) return 1;
      return 0;
    });
    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
    applyFilters();
  }

  function syncChromePinOffset() {
    var pin = qs("roster-chrome-pin");
    if (!pin) return;
    var height = Math.ceil(pin.getBoundingClientRect().height);
    document.documentElement.style.setProperty(
      "--admin-roster-chrome-pin-offset",
      height + "px"
    );
  }

  function bindBeforeUnload() {
    window.addEventListener("beforeunload", function (event) {
      if (!hasPendingFlush()) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  function bindResetConfirm() {
    var form = qs("roster-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      if (hasPendingFlush() || flushFailed) {
        event.preventDefault();
        window.alert(
          flushFailed
            ? "Черновик не сохранён. Повторите правку или обновите страницу, затем сбросьте."
            : "Дождитесь сохранения черновика и повторите."
        );
        return;
      }
      var submitter = event.submitter;
      if (!submitter) return;
      if (submitter.id !== "roster-reset") return;
      var ok = window.confirm(
        "Сбросить общий черновик к применённому roster? Правки коллег тоже будут потеряны."
      );
      if (!ok) event.preventDefault();
    });
  }

  function init() {
    var searchEl = qs("roster-search");
    var techEl = qs("roster-technician-filter");
    var dayEl = qs("roster-weekday-filter");
    if (!searchEl || !techEl || !dayEl) return;

    searchEl.addEventListener("input", applyFilters);
    techEl.addEventListener("change", applyFilters);
    dayEl.addEventListener("change", applyFilters);

    document.querySelectorAll("th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        sortBy(th.getAttribute("data-sort-key") || "machine-id");
      });
    });

    applyFilters();
    bindRowEditors();
    bindBeforeUnload();
    bindResetConfirm();
    refreshDirtyUi();
    syncChromePinOffset();
    window.addEventListener("resize", syncChromePinOffset);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
