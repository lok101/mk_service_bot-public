(function () {
  var sortKey = "";
  var sortDir = 1;

  function qs(id) {
    return document.getElementById(id);
  }

  function haystack(row) {
    return [
      row.getAttribute("data-code") || "",
      row.getAttribute("data-name") || "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function dataRows(table) {
    if (!table.tBodies[0]) return [];
    return Array.prototype.filter.call(table.tBodies[0].rows, function (row) {
      return row.hasAttribute("data-code");
    });
  }

  function applyFilters() {
    var searchEl = qs("snack-planograms-search");
    var table = qs("snack-planograms-table");
    if (!searchEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var visible = 0;
    dataRows(table).forEach(function (row) {
      var show = !search || haystack(row).indexOf(search) !== -1;
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("snack-planograms-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function compare(left, right) {
    var attr = sortKey === "name" ? "data-name" : "data-code";
    var leftKey = (left.getAttribute(attr) || "").toLowerCase();
    var rightKey = (right.getAttribute(attr) || "").toLowerCase();
    if (leftKey < rightKey) return -sortDir;
    if (leftKey > rightKey) return sortDir;
    var leftCode = (left.getAttribute("data-code") || "").toLowerCase();
    var rightCode = (right.getAttribute("data-code") || "").toLowerCase();
    if (leftCode < rightCode) return -1;
    if (leftCode > rightCode) return 1;
    return 0;
  }

  function sortRows() {
    var table = qs("snack-planograms-table");
    if (!table || !table.tBodies[0]) return;
    var body = table.tBodies[0];
    dataRows(table)
      .sort(compare)
      .forEach(function (row) {
        body.appendChild(row);
      });
    applyFilters();
  }

  function init() {
    var searchEl = qs("snack-planograms-search");
    var table = qs("snack-planograms-table");
    if (!searchEl || !table) return;
    searchEl.addEventListener("input", applyFilters);
    table.querySelectorAll("th.sortable").forEach(function (header) {
      header.addEventListener("click", function () {
        var key = header.getAttribute("data-sort-key") || "code";
        if (key === sortKey) sortDir = -sortDir;
        else {
          sortKey = key;
          sortDir = 1;
        }
        sortRows();
      });
    });
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
