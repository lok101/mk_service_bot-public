(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  function applyFilter() {
    var filterEl = qs("matrix-sku-archived-filter");
    var table = qs("matrix-sku-catalog-table");
    if (!filterEl || !table || !table.tBodies[0]) return;
    var mode = filterEl.value || "active";
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      var archived = row.getAttribute("data-archived") === "true";
      if (mode === "all") {
        row.hidden = false;
      } else if (mode === "archived") {
        row.hidden = !archived;
      } else {
        row.hidden = archived;
      }
    });
  }

  function init() {
    var filterEl = qs("matrix-sku-archived-filter");
    if (!filterEl) return;
    filterEl.addEventListener("change", applyFilter);
    applyFilter();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
