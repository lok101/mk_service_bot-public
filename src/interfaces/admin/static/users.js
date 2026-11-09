(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  function applyFilter() {
    var filterEl = qs("users-active-filter");
    var table = qs("users-table");
    if (!filterEl || !table || !table.tBodies[0]) return;
    var mode = filterEl.value || "active";
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      if (row.getAttribute("data-create") === "1") {
        row.hidden = false;
        return;
      }
      var active = row.getAttribute("data-active") === "true";
      if (mode === "all") {
        row.hidden = false;
      } else if (mode === "inactive") {
        row.hidden = active;
      } else {
        row.hidden = !active;
      }
    });
  }

  function syncRowActive(row) {
    var checkbox = row.querySelector('input[type="checkbox"][name^="is_active-"]');
    if (!checkbox) return;
    row.setAttribute("data-active", checkbox.checked ? "true" : "false");
  }

  function init() {
    var filterEl = qs("users-active-filter");
    var table = qs("users-table");
    if (!filterEl || !table) return;
    filterEl.addEventListener("change", applyFilter);
    table.addEventListener("change", function (event) {
      var target = event.target;
      if (!target || target.name === undefined) return;
      if (String(target.name).indexOf("is_active-") !== 0) return;
      var row = target.closest("tr");
      if (!row || row.getAttribute("data-create") === "1") return;
      syncRowActive(row);
      applyFilter();
    });
    applyFilter();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
