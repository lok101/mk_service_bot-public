(function () {
  var sortKey = "";
  var sortDir = 1;
  var sortType = "text";

  var textAttr = {
    "machine-id": "data-machine-id",
    name: "data-name",
    technician: "data-technician",
    reason: "data-reason",
    "clear-kind": "data-clear-kind",
  };

  function qs(id) {
    return document.getElementById(id);
  }

  function dataRows(table) {
    if (!table.tBodies[0]) return [];
    return Array.prototype.filter.call(table.tBodies[0].rows, function (row) {
      return row.hasAttribute("data-machine-id");
    });
  }

  function haystack(row) {
    return [
      row.getAttribute("data-machine-id") || "",
      row.getAttribute("data-name") || "",
      row.getAttribute("data-technician") || "",
      row.getAttribute("data-reason") || "",
      row.getAttribute("data-clear-kind") || "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function matchesSelect(row, elementId, attr) {
    var element = qs(elementId);
    if (!element || element.value === "all") return true;
    return (row.getAttribute(attr) || "") === element.value;
  }

  function applyFilters() {
    var searchEl = qs("incident-history-search");
    var table = qs("incident-history-table");
    if (!searchEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var visible = 0;
    dataRows(table).forEach(function (row) {
      var show = true;
      if (search && haystack(row).indexOf(search) === -1) show = false;
      if (!matchesSelect(row, "incident-history-technician-filter", "data-technician")) {
        show = false;
      }
      if (!matchesSelect(row, "incident-history-reason-filter", "data-reason")) {
        show = false;
      }
      if (!matchesSelect(row, "incident-history-clear-filter", "data-clear-kind")) {
        show = false;
      }
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("incident-history-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function tie(left, right) {
    var aId = (left.getAttribute("data-machine-id") || "").toLowerCase();
    var bId = (right.getAttribute("data-machine-id") || "").toLowerCase();
    if (aId < bId) return -1;
    if (aId > bId) return 1;
    return 0;
  }

  function compare(left, right) {
    if (sortType === "moment") {
      var aMoment = left.getAttribute("data-" + sortKey) || "";
      var bMoment = right.getAttribute("data-" + sortKey) || "";
      var aEmpty = !aMoment;
      var bEmpty = !bMoment;
      if (aEmpty || bEmpty) {
        if (aEmpty && bEmpty) return tie(left, right);
        return aEmpty ? 1 : -1;
      }
      if (aMoment < bMoment) return -sortDir;
      if (aMoment > bMoment) return sortDir;
      return tie(left, right);
    }
    if (sortType === "number") {
      var aNumRaw = left.getAttribute("data-" + sortKey) || "";
      var bNumRaw = right.getAttribute("data-" + sortKey) || "";
      var aEmpty = !aNumRaw;
      var bEmpty = !bNumRaw;
      if (aEmpty || bEmpty) {
        if (aEmpty && bEmpty) return tie(left, right);
        return aEmpty ? 1 : -1;
      }
      var aNum = Number(aNumRaw);
      var bNum = Number(bNumRaw);
      if (aNum < bNum) return -sortDir;
      if (aNum > bNum) return sortDir;
      return tie(left, right);
    }
    var attr = textAttr[sortKey] || "data-machine-id";
    var aText = (left.getAttribute(attr) || "").toLowerCase();
    var bText = (right.getAttribute(attr) || "").toLowerCase();
    if (aText < bText) return -sortDir;
    if (aText > bText) return sortDir;
    return tie(left, right);
  }

  function markSort(table, active) {
    table.querySelectorAll("th.sortable").forEach(function (header) {
      if (header === active) {
        header.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
      } else {
        header.removeAttribute("aria-sort");
      }
    });
  }

  function sortRows(active) {
    var table = qs("incident-history-table");
    if (!table || !table.tBodies[0]) return;
    var body = table.tBodies[0];
    dataRows(table)
      .sort(compare)
      .forEach(function (row) {
        body.appendChild(row);
      });
    markSort(table, active);
    applyFilters();
  }

  function syncChromePinOffset() {
    var pin = qs("incident-history-chrome-pin");
    if (!pin) return;
    var height = Math.ceil(pin.getBoundingClientRect().height);
    document.documentElement.style.setProperty(
      "--admin-roster-chrome-pin-offset",
      height + "px"
    );
  }

  function init() {
    var searchEl = qs("incident-history-search");
    var technicianEl = qs("incident-history-technician-filter");
    var reasonEl = qs("incident-history-reason-filter");
    var clearEl = qs("incident-history-clear-filter");
    var table = qs("incident-history-table");
    if (!searchEl || !technicianEl || !reasonEl || !clearEl || !table) return;
    searchEl.addEventListener("input", applyFilters);
    technicianEl.addEventListener("change", applyFilters);
    reasonEl.addEventListener("change", applyFilters);
    clearEl.addEventListener("change", applyFilters);
    table.querySelectorAll("th.sortable").forEach(function (header) {
      header.addEventListener("click", function () {
        var key = header.getAttribute("data-sort-key") || "machine-id";
        if (key === sortKey) sortDir = -sortDir;
        else {
          sortKey = key;
          sortDir = 1;
          sortType = header.getAttribute("data-sort-type") || "text";
        }
        sortRows(header);
      });
    });
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
