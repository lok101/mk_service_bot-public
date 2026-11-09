(function () {
  var sortKey = "";
  var sortDir = 1;

  function qs(id) {
    return document.getElementById(id);
  }

  function haystack(row) {
    return [
      row.getAttribute("data-name") || "",
      row.getAttribute("data-number") || "",
      row.getAttribute("data-catalog-code") || "",
      row.getAttribute("data-catalog-name") || "",
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
    var searchEl = qs("domain-products-search");
    var stateEl = qs("domain-products-state-filter");
    var table = qs("domain-products-table");
    if (!searchEl || !stateEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var state = stateEl.value || "all";
    var visible = 0;
    dataRows(table).forEach(function (row) {
      var show = true;
      if (search && haystack(row).indexOf(search) === -1) show = false;
      var rowState = row.getAttribute("data-state") || "";
      if (state !== "all" && rowState !== state) show = false;
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("domain-products-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function compare(left, right) {
    var attr = "data-name";
    if (sortKey === "state") attr = "data-state";
    else if (sortKey === "supplier") attr = "data-supplier";
    var leftKey = (left.getAttribute(attr) || "").toLowerCase();
    var rightKey = (right.getAttribute(attr) || "").toLowerCase();
    if (leftKey < rightKey) return -sortDir;
    if (leftKey > rightKey) return sortDir;
    var leftNumber = (left.getAttribute("data-number") || "").toLowerCase();
    var rightNumber = (right.getAttribute("data-number") || "").toLowerCase();
    if (leftNumber < rightNumber) return -1;
    if (leftNumber > rightNumber) return 1;
    return 0;
  }

  function sortRows() {
    var table = qs("domain-products-table");
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
    var searchEl = qs("domain-products-search");
    var stateEl = qs("domain-products-state-filter");
    var table = qs("domain-products-table");
    if (!searchEl || !stateEl || !table) return;
    searchEl.addEventListener("input", applyFilters);
    stateEl.addEventListener("change", applyFilters);
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
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
