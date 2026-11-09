(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  function table() {
    return qs("incident-live-table");
  }

  function sections() {
    var root = table();
    if (!root) return [];
    return Array.prototype.slice.call(root.querySelectorAll("tbody[data-incident-group]"));
  }

  function dataRows(section) {
    return Array.prototype.filter.call(section.rows, function (row) {
      return row.hasAttribute("data-machine-id");
    });
  }

  function haystack(row) {
    return [
      row.getAttribute("data-machine-id") || "",
      row.getAttribute("data-name") || "",
      row.getAttribute("data-note") || "",
      row.getAttribute("data-reason") || "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function matchesSelect(row, elementId, attr) {
    var element = qs(elementId);
    if (!element || element.value === "all") return true;
    return (row.getAttribute(attr) || "") === element.value;
  }

  function rowVisible(row, search) {
    if (search && haystack(row).indexOf(search) === -1) return false;
    if (!matchesSelect(row, "incident-live-note-filter", "data-note")) return false;
    if (!matchesSelect(row, "incident-live-reason-filter", "data-reason")) return false;
    return true;
  }

  function applyFilters() {
    var searchEl = qs("incident-live-search");
    if (!searchEl) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var visible = 0;
    var total = 0;
    sections().forEach(function (section) {
      var shown = 0;
      dataRows(section).forEach(function (row) {
        total += 1;
        var show = rowVisible(row, search);
        row.hidden = !show;
        if (show) shown += 1;
      });
      section.hidden = shown === 0;
      visible += shown;
    });
    var countEl = qs("incident-live-visible-count");
    if (countEl) countEl.textContent = String(visible);
    var totalEl = qs("incident-live-total-count");
    if (totalEl) totalEl.textContent = String(total);
  }

  function tie(left, right) {
    var aId = (left.getAttribute("data-machine-id") || "").toLowerCase();
    var bId = (right.getAttribute("data-machine-id") || "").toLowerCase();
    if (aId < bId) return -1;
    if (aId > bId) return 1;
    return 0;
  }

  function bindTable(root) {
    var sortKey = "";
    var sortDir = 1;

    function compare(left, right) {
      var attr = "data-" + sortKey;
      var aText = (left.getAttribute(attr) || "").toLowerCase();
      var bText = (right.getAttribute(attr) || "").toLowerCase();
      if (aText < bText) return -sortDir;
      if (aText > bText) return sortDir;
      return tie(left, right);
    }

    function markSort(active) {
      root.querySelectorAll("th.sortable").forEach(function (header) {
        if (header === active) {
          header.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
        } else {
          header.removeAttribute("aria-sort");
        }
      });
    }

    root.querySelectorAll("th.sortable").forEach(function (header) {
      header.addEventListener("click", function () {
        var key = header.getAttribute("data-sort-key") || "machine-id";
        if (key === sortKey) sortDir = -sortDir;
        else {
          sortKey = key;
          sortDir = 1;
        }
        sections().forEach(function (section) {
          dataRows(section)
            .sort(compare)
            .forEach(function (row) {
              section.appendChild(row);
            });
        });
        markSort(header);
        applyFilters();
      });
    });
  }

  function syncChromePinOffset() {
    var pin = qs("incident-live-chrome-pin");
    if (!pin) return;
    var height = Math.ceil(pin.getBoundingClientRect().height);
    document.documentElement.style.setProperty(
      "--admin-roster-chrome-pin-offset",
      height + "px"
    );
  }

  function init() {
    var searchEl = qs("incident-live-search");
    var noteEl = qs("incident-live-note-filter");
    var reasonEl = qs("incident-live-reason-filter");
    var root = table();
    if (!searchEl || !noteEl || !reasonEl || !root) return;
    searchEl.addEventListener("input", applyFilters);
    noteEl.addEventListener("change", applyFilters);
    reasonEl.addEventListener("change", applyFilters);
    bindTable(root);
    applyFilters();
    syncChromePinOffset();
    window.addEventListener("resize", syncChromePinOffset);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
