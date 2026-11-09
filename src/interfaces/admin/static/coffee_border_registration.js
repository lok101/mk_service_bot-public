/* Coffee border registration queue: ignore toggle + filter/sort. */
(function () {
  var table = document.getElementById("border-queue-table");
  var filterInput = document.getElementById("border-queue-filter");
  var countEl = document.getElementById("border-queue-count");
  if (!table) return;

  var sortKey = "code";
  var sortDir = 1;

  function rows() {
    return Array.prototype.slice.call(table.tBodies[0].rows);
  }

  function updateCount() {
    var all = rows();
    var visible = all.filter(function (tr) {
      return !tr.hidden;
    }).length;
    if (countEl) {
      countEl.textContent = "показано " + visible + " из " + all.length;
    }
  }

  function applyFilter() {
    var q = (filterInput && filterInput.value ? filterInput.value : "").trim().toLowerCase();
    rows().forEach(function (tr) {
      var hay = (tr.getAttribute("data-filter") || "").toLowerCase();
      tr.hidden = Boolean(q) && hay.indexOf(q) === -1;
    });
    updateCount();
  }

  function compare(a, b) {
    var ak = sortKey === "name" ? (a.cells[1].textContent || "") : (a.getAttribute("data-code") || "");
    var bk = sortKey === "name" ? (b.cells[1].textContent || "") : (b.getAttribute("data-code") || "");
    var an = String(ak).toLowerCase();
    var bn = String(bk).toLowerCase();
    if (an < bn) return -1 * sortDir;
    if (an > bn) return 1 * sortDir;
    return String(a.getAttribute("data-code") || "").localeCompare(
      String(b.getAttribute("data-code") || "")
    );
  }

  function resort() {
    var tbody = table.tBodies[0];
    rows()
      .slice()
      .sort(compare)
      .forEach(function (tr) {
        tbody.appendChild(tr);
      });
    Array.prototype.forEach.call(table.querySelectorAll("th.sortable"), function (th) {
      var key = th.getAttribute("data-sort");
      th.setAttribute(
        "aria-sort",
        key === sortKey ? (sortDir === 1 ? "ascending" : "descending") : "none"
      );
    });
  }

  function setIgnored(tr, ignored) {
    tr.setAttribute("data-ignored", ignored ? "true" : "false");
    tr.classList.toggle("demo-row-ignored", ignored);
    var mark = tr.querySelector(".border-ignore-mark");
    var picker = tr.querySelector(".border-product-picker");
    var ignoredField = tr.querySelector(".border-ignored-field");
    var idInput = tr.querySelector(".planogram-domain-product-id");
    var btn = tr.querySelector(".border-ignore-btn");
    if (ignoredField) ignoredField.value = ignored ? "1" : "0";
    if (mark) mark.hidden = !ignored;
    if (picker) picker.hidden = ignored;
    if (ignored && idInput) {
      idInput.value = "";
      var selected = picker && picker.querySelector(".planogram-product-selected");
      var search = picker && picker.querySelector(".planogram-product-search");
      var clearBtn = picker && picker.querySelector(".planogram-product-clear");
      var link = picker && picker.querySelector(".planogram-product-link");
      if (selected) selected.hidden = true;
      if (clearBtn) clearBtn.hidden = true;
      if (search) {
        search.hidden = false;
        search.value = "";
      }
      if (link) {
        link.textContent = "";
        link.removeAttribute("href");
      }
    }
    if (btn) btn.textContent = ignored ? "Вернуть" : "Игнорировать";
  }

  table.addEventListener("click", function (event) {
    var btn = event.target.closest(".border-ignore-btn");
    if (!btn) return;
    var tr = btn.closest("tr");
    if (!tr) return;
    setIgnored(tr, tr.getAttribute("data-ignored") !== "true");
  });

  Array.prototype.forEach.call(table.querySelectorAll("th.sortable"), function (th) {
    th.addEventListener("click", function () {
      var key = th.getAttribute("data-sort");
      if (sortKey === key) sortDir = -sortDir;
      else {
        sortKey = key;
        sortDir = 1;
      }
      resort();
      applyFilter();
    });
  });

  if (filterInput) filterInput.addEventListener("input", applyFilter);
  updateCount();
})();
