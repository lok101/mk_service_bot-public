(function () {
  var sortKey = "name";
  var sortDir = 1;

  function qs(id) {
    return document.getElementById(id);
  }

  function dataRows(table) {
    if (!table.tBodies[0]) return [];
    return Array.prototype.filter.call(table.tBodies[0].rows, function (row) {
      return row.hasAttribute("data-name");
    });
  }

  function haystack(row) {
    return [
      row.getAttribute("data-name") || "",
      row.getAttribute("data-number") || "",
      row.getAttribute("data-codes") || "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function applyFilters() {
    var searchEl = qs("coffee-ingredients-search");
    var unitEl = qs("coffee-ingredients-unit-filter");
    var linkEl = qs("coffee-ingredients-link-filter");
    var table = qs("coffee-ingredients-table");
    if (!searchEl || !unitEl || !linkEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var unit = unitEl.value || "all";
    var link = linkEl.value || "all";
    var visible = 0;
    dataRows(table).forEach(function (row) {
      var show = true;
      if (search && haystack(row).indexOf(search) === -1) show = false;
      if (unit !== "all" && (row.getAttribute("data-unit") || "") !== unit) show = false;
      var linked = row.getAttribute("data-linked") === "1";
      if (link === "linked" && !linked) show = false;
      if (link === "unlinked" && linked) show = false;
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("coffee-ingredients-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function compare(left, right) {
    var attr = "data-" + (sortKey === "pack" ? "pack" : sortKey);
    if (sortKey === "pack") {
      var ln = Number(left.getAttribute("data-pack") || 0);
      var rn = Number(right.getAttribute("data-pack") || 0);
      if (ln !== rn) return (ln - rn) * sortDir;
    } else {
      var leftKey = (left.getAttribute(attr) || "").toLowerCase();
      var rightKey = (right.getAttribute(attr) || "").toLowerCase();
      if (leftKey < rightKey) return -sortDir;
      if (leftKey > rightKey) return sortDir;
    }
    var leftNumber = (left.getAttribute("data-number") || "").toLowerCase();
    var rightNumber = (right.getAttribute("data-number") || "").toLowerCase();
    if (leftNumber < rightNumber) return -1;
    if (leftNumber > rightNumber) return 1;
    return 0;
  }

  function updateSortMarks(table) {
    table.querySelectorAll("th.sortable").forEach(function (header) {
      var key = header.getAttribute("data-sort-key") || "";
      if (key === sortKey) {
        header.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
      } else {
        header.setAttribute("aria-sort", "none");
      }
    });
  }

  function sortRows() {
    var table = qs("coffee-ingredients-table");
    if (!table || !table.tBodies[0]) return;
    var body = table.tBodies[0];
    dataRows(table)
      .sort(compare)
      .forEach(function (row) {
        body.appendChild(row);
      });
    updateSortMarks(table);
    applyFilters();
  }

  function init() {
    var searchEl = qs("coffee-ingredients-search");
    var unitEl = qs("coffee-ingredients-unit-filter");
    var linkEl = qs("coffee-ingredients-link-filter");
    var table = qs("coffee-ingredients-table");
    if (!searchEl || !unitEl || !linkEl || !table) return;
    searchEl.addEventListener("input", applyFilters);
    unitEl.addEventListener("change", applyFilters);
    linkEl.addEventListener("change", applyFilters);
    table.querySelectorAll("th.sortable").forEach(function (header) {
      header.addEventListener("click", function () {
        var key = header.getAttribute("data-sort-key") || "name";
        if (key === sortKey) sortDir = -sortDir;
        else {
          sortKey = key;
          sortDir = 1;
        }
        sortRows();
      });
    });
    updateSortMarks(table);
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
