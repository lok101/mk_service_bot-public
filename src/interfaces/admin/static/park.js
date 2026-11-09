(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  function uniqueCities(rows) {
    var set = {};
    rows.forEach(function (row) {
      var c = (row.getAttribute("data-city") || "").trim();
      if (c) set[c] = true;
    });
    return Object.keys(set).sort();
  }

  function uniqueCompanyNames(rows) {
    var set = {};
    rows.forEach(function (row) {
      var c = (row.getAttribute("data-company-name") || "").trim();
      if (c) set[c] = true;
    });
    return Object.keys(set).sort();
  }

  function populateCityFilter(select, rows) {
    var existing = select.value || "all";
    while (select.options.length > 1) {
      select.remove(1);
    }
    uniqueCities(rows).forEach(function (city) {
      var opt = document.createElement("option");
      opt.value = city;
      opt.textContent = city;
      select.appendChild(opt);
    });
    var stillThere = false;
    for (var i = 0; i < select.options.length; i += 1) {
      if (select.options[i].value === existing) {
        stillThere = true;
        break;
      }
    }
    select.value = stillThere ? existing : "all";
  }

  function populateCompanyFilter(select, rows) {
    var existing = select.value || "all";
    while (select.options.length > 1) {
      select.remove(1);
    }
    uniqueCompanyNames(rows).forEach(function (company) {
      var opt = document.createElement("option");
      opt.value = company;
      opt.textContent = company;
      select.appendChild(opt);
    });
    var stillThere = false;
    for (var i = 0; i < select.options.length; i += 1) {
      if (select.options[i].value === existing) {
        stillThere = true;
        break;
      }
    }
    select.value = stillThere ? existing : "all";
  }

  function rowMatches(row, search, kindFilter, cityFilter, companyFilter) {
    var machineId = (row.getAttribute("data-machine-id") || "").toLowerCase();
    var locationName = (row.getAttribute("data-location-name") || "").toLowerCase();
    var city = (row.getAttribute("data-city") || "").toLowerCase();
    var companyName = (row.getAttribute("data-company-name") || "").toLowerCase();
    var kind = (row.getAttribute("data-kind") || "").toLowerCase();
    if (search) {
      var hay = machineId + " " + locationName + " " + city + " " + companyName;
      if (hay.indexOf(search) === -1) return false;
    }
    if (kindFilter && kindFilter !== "all" && kind !== kindFilter) return false;
    if (cityFilter && cityFilter !== "all") {
      var rawCity = (row.getAttribute("data-city") || "").trim();
      if (rawCity !== cityFilter) return false;
    }
    if (companyFilter && companyFilter !== "all") {
      var rawCompany = (row.getAttribute("data-company-name") || "").trim();
      if (rawCompany !== companyFilter) return false;
    }
    return true;
  }

  function applyFilters() {
    var searchEl = qs("park-search");
    var kindEl = qs("park-kind-filter");
    var cityEl = qs("park-city-filter");
    var companyEl = qs("park-company-filter");
    var table = qs("park-machines-table");
    if (!searchEl || !kindEl || !cityEl || !companyEl || !table) return;
    var search = (searchEl.value || "").trim().toLowerCase();
    var kindFilter = kindEl.value || "all";
    var cityFilter = cityEl.value || "all";
    var companyFilter = companyEl.value || "all";
    var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
    var visible = 0;
    rows.forEach(function (row) {
      if (!row.getAttribute("data-machine-id")) return;
      var show = rowMatches(row, search, kindFilter, cityFilter, companyFilter);
      row.hidden = !show;
      if (show) visible += 1;
    });
    var countEl = qs("park-visible-count");
    if (countEl) countEl.textContent = String(visible);
  }

  function init() {
    var searchEl = qs("park-search");
    var kindEl = qs("park-kind-filter");
    var cityEl = qs("park-city-filter");
    var companyEl = qs("park-company-filter");
    var table = qs("park-machines-table");
    if (!searchEl || !kindEl || !cityEl || !companyEl || !table) return;
    var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
    populateCityFilter(cityEl, rows);
    populateCompanyFilter(companyEl, rows);
    searchEl.addEventListener("input", applyFilters);
    kindEl.addEventListener("change", applyFilters);
    cityEl.addEventListener("change", applyFilters);
    companyEl.addEventListener("change", applyFilters);
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
