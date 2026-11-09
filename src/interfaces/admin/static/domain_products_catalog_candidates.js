(function () {
  var sortKey = "";
  var sortDir = 1;

  function qs(id) {
    return document.getElementById(id);
  }

  function haystack(row) {
    return [
      row.getAttribute("data-name") || "",
      row.getAttribute("data-code") || "",
    ]
      .join(" ")
      .toLowerCase();
  }

  function dataRows(table) {
    if (!table.tBodies[0]) return [];
    return Array.prototype.filter.call(table.tBodies[0].rows, function (row) {
      return row.hasAttribute("data-name");
    });
  }

  function applyFilters() {
    var searchEl = qs("catalog-candidates-search");
    var table = qs("catalog-candidates-table");
    if (!searchEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var visible = 0;
    dataRows(table).forEach(function (row) {
      var show = true;
      if (search && haystack(row).indexOf(search) === -1) show = false;
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("catalog-candidates-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function compare(left, right) {
    var attr = sortKey === "code" ? "data-code" : "data-name";
    var leftKey = (left.getAttribute(attr) || "").toLowerCase();
    var rightKey = (right.getAttribute(attr) || "").toLowerCase();
    if (leftKey < rightKey) return -sortDir;
    if (leftKey > rightKey) return sortDir;
    return 0;
  }

  function sortRows() {
    var table = qs("catalog-candidates-table");
    if (!table || !table.tBodies[0]) return;
    var body = table.tBodies[0];
    dataRows(table)
      .sort(compare)
      .forEach(function (row) {
        body.appendChild(row);
      });
    applyFilters();
  }

  function selectVisible() {
    var table = qs("catalog-candidates-table");
    if (!table) return;
    dataRows(table).forEach(function (row) {
      if (row.hidden) return;
      var box = row.querySelector('input[type="checkbox"][name="code"]');
      if (box) box.checked = true;
    });
  }

  function init() {
    var searchEl = qs("catalog-candidates-search");
    var table = qs("catalog-candidates-table");
    var selectBtn = qs("catalog-candidates-select-visible");
    if (!searchEl || !table) return;
    searchEl.addEventListener("input", applyFilters);
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
    if (selectBtn) selectBtn.addEventListener("click", selectVisible);
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
