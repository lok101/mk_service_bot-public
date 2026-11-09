(function () {
  "use strict";

  var form = document.getElementById("problems-filters-form");
  var dayIso = document.getElementById("problems-day-iso");
  var dayDisplay = document.getElementById("problems-day-display");
  var dayPicker = document.getElementById("problems-day-picker");
  var dayCal = document.getElementById("problems-day-cal");
  var lightbox = document.getElementById("problems-lightbox");
  var shell = document.getElementById("problems-lightbox-shell");
  var photo = document.getElementById("problems-lightbox-photo");
  var caption = document.getElementById("problems-lightbox-caption");
  var message = document.getElementById("problems-lightbox-message");
  var closeBtn = document.getElementById("problems-lightbox-close");
  var groupSelect = document.getElementById("problems-group");
  var problemSelect = document.getElementById("problems-defect");
  var catalogEl = document.getElementById("problems-filter-groups");
  var filterTable = document.getElementById("problems-filter-table");
  var headerTable = document.getElementById("problems-header-table");
  var dataTable = document.getElementById("problems-table");
  var problemsPanel = document.querySelector('.admin-workspace-panel[data-tab="problems"]');
  var filterGroups = [];

  if (!form || !lightbox) {
    return;
  }

  if (catalogEl && catalogEl.textContent) {
    try {
      filterGroups = JSON.parse(catalogEl.textContent);
    } catch (_err) {
      filterGroups = [];
    }
  }

  function dayFilterToIso(raw) {
    var s = String(raw || "").trim();
    if (!s) {
      return "";
    }
    var m = /^(\d{1,2})\.(\d{1,2})\.(\d{2})$/.exec(s);
    if (!m) {
      return null;
    }
    var dd = m[1].padStart(2, "0");
    var mm = m[2].padStart(2, "0");
    var yy = String(2000 + Number(m[3]));
    return yy + "-" + mm + "-" + dd;
  }

  function isoToDayDisplay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
    if (!m) {
      return "";
    }
    return m[3] + "." + m[2] + "." + m[1].slice(2);
  }

  function syncIsoFromDisplay() {
    var raw = dayDisplay.value.trim();
    if (!raw) {
      dayIso.value = "all";
      return true;
    }
    var iso = dayFilterToIso(raw);
    if (iso === null) {
      return false;
    }
    dayIso.value = iso;
    if (dayPicker) {
      dayPicker.value = iso;
    }
    return true;
  }

  function openLightbox(href, captionText) {
    if (!href) {
      photo.removeAttribute("src");
      photo.hidden = true;
      caption.hidden = true;
      if (message) {
        message.hidden = false;
      }
    } else {
      photo.hidden = false;
      caption.hidden = false;
      if (message) {
        message.hidden = true;
      }
      photo.src = href;
      caption.textContent = captionText || "";
    }
    lightbox.hidden = false;
    if (closeBtn) {
      closeBtn.focus();
    }
  }

  function closeLightbox() {
    lightbox.hidden = true;
    photo.removeAttribute("src");
  }

  function defectsForGroup(groupId) {
    for (var i = 0; i < filterGroups.length; i += 1) {
      if (filterGroups[i].group_id === groupId) {
        return filterGroups[i].defects || [];
      }
    }
    return [];
  }

  function rebuildProblemSelect() {
    if (!groupSelect || !problemSelect) {
      return;
    }
    var groupId = groupSelect.value;
    var defects = defectsForGroup(groupId);
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "все";
    problemSelect.replaceChildren(blank);
    defects.forEach(function (defect) {
      var opt = document.createElement("option");
      opt.value = defect.code;
      opt.textContent = defect.label;
      problemSelect.appendChild(opt);
    });
    problemSelect.value = "";
    problemSelect.disabled = !groupId;
    if (groupId) {
      problemSelect.removeAttribute("title");
    } else {
      problemSelect.title = "Сначала выберите группу фото";
    }
  }

  var lastContainerWidth = -1;

  function syncProblemColumns() {
    if (!filterTable || !headerTable || !dataTable || !problemsPanel) {
      return;
    }
    if (problemsPanel.hasAttribute("hidden")) {
      lastContainerWidth = -1;
      return;
    }
    var container = dataTable.getBoundingClientRect().width;
    if (container < 1) {
      return;
    }
    if (
      Math.abs(container - lastContainerWidth) < 0.5 &&
      dataTable.style.tableLayout === "fixed"
    ) {
      return;
    }
    lastContainerWidth = container;

    var filterCols = filterTable.querySelectorAll("col");
    var headerCols = headerTable.querySelectorAll("col");
    var dataCols = dataTable.querySelectorAll("col");
    [filterCols, headerCols, dataCols].forEach(function (cols) {
      cols.forEach(function (col) {
        col.style.width = "";
      });
    });
    dataTable.style.tableLayout = "auto";
    dataTable.style.width = "100%";
    headerTable.style.tableLayout = "auto";
    headerTable.style.width = "max-content";

    var body = document.getElementById("problems-body");
    var row = body ? body.querySelector("tr") : null;
    var bodyCells = row ? row.querySelectorAll("td") : [];
    var headerCells = headerTable.querySelectorAll("th");
    var widths = [];
    for (var i = 0; i < headerCells.length; i += 1) {
      var bodyWidth = bodyCells[i] ? bodyCells[i].getBoundingClientRect().width : 0;
      var headerWidth = headerCells[i].getBoundingClientRect().width;
      widths.push(Math.max(bodyWidth, headerWidth));
    }
    var sum = widths.reduce(function (total, width) {
      return total + width;
    }, 0);
    if (sum < 1) {
      return;
    }
    var filterBox = filterTable.parentElement
      ? filterTable.parentElement.getBoundingClientRect().width
      : container;
    if (filterBox < 1) {
      filterBox = container;
    }

    function apply(cols, target) {
      var scale = target / sum;
      widths.forEach(function (width, index) {
        if (cols[index]) {
          cols[index].style.width = width * scale + "px";
        }
      });
    }

    apply(dataCols, container);
    apply(headerCols, container);
    apply(filterCols, filterBox);
    filterTable.style.tableLayout = "fixed";
    filterTable.style.width = "100%";
    headerTable.style.tableLayout = "fixed";
    headerTable.style.width = "100%";
    dataTable.style.tableLayout = "fixed";
    dataTable.style.width = "100%";
  }

  function scheduleColumnSync() {
    requestAnimationFrame(syncProblemColumns);
  }

  form.addEventListener("change", function (ev) {
    var target = ev.target;
    if (target && target.name === "group_id") {
      rebuildProblemSelect();
    }
    if (syncIsoFromDisplay()) {
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", function (ev) {
    if (!syncIsoFromDisplay()) {
      ev.preventDefault();
    }
  });

  if (dayCal && dayPicker) {
    dayCal.addEventListener("click", function () {
      syncIsoFromDisplay();
      if (typeof dayPicker.showPicker === "function") {
        dayPicker.showPicker();
      } else {
        dayPicker.style.pointerEvents = "auto";
        dayPicker.focus();
        dayPicker.click();
        dayPicker.style.pointerEvents = "none";
      }
    });

    dayPicker.addEventListener("change", function () {
      var display = isoToDayDisplay(dayPicker.value);
      if (display) {
        dayDisplay.value = display;
        dayIso.value = dayPicker.value;
        form.requestSubmit();
      }
    });
  }

  document.querySelectorAll(".admin-thumb[data-photo-href]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openLightbox(btn.getAttribute("data-photo-href") || "", btn.getAttribute("data-caption") || "");
    });
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", closeLightbox);
  }
  lightbox.addEventListener("click", function (ev) {
    if (ev.target === lightbox) {
      closeLightbox();
    }
  });
  if (shell) {
    shell.addEventListener("click", function (ev) {
      ev.stopPropagation();
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !lightbox.hidden) {
      closeLightbox();
    }
  });

  document.querySelectorAll(".admin-workspace-tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      if (tab.getAttribute("data-tab") === "problems") {
        scheduleColumnSync();
      }
    });
  });
  window.addEventListener("resize", scheduleColumnSync);
  if (typeof ResizeObserver === "function" && dataTable) {
    var columnObserver = new ResizeObserver(scheduleColumnSync);
    columnObserver.observe(dataTable.parentElement || dataTable);
  }
  scheduleColumnSync();
})();
