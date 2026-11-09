(function () {
  function qs(id) {
    return document.getElementById(id);
  }

  function domainIdField(cell) {
    return cell.querySelector('input[name="planogram_domain_product_id"]');
  }

  function codeField(cell) {
    return cell.querySelector('input[name="planogram_product_code"]');
  }

  function spanToggleButton(cell) {
    return cell ? cell.querySelector(".planogram-span-toggle") : null;
  }

  function parseOptionsMap() {
    var el = qs("layout-product-options-json");
    if (!el) return {};
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (err) {
      return {};
    }
  }

  function productNamesFromOptions(optionsMap) {
    return [];
  }

  function syncCapacityFromCode(cell, optionsMap) {
    var codeInput = codeField(cell);
    var capacityChip = cell.querySelector(".chip-capacity");
    if (!capacityChip) return;
    var code = codeInput ? (codeInput.value || "").trim() : "";
    if (!code) {
      var idInput = domainIdField(cell);
      var domainId = idInput ? (idInput.value || "").trim() : "";
      var picker = cell.querySelector(".planogram-product-picker");
      var unlinked = Boolean(picker && picker.getAttribute("data-unlinked") === "true");
      if (domainId && !unlinked) {
        return;
      }
      capacityChip.textContent = "";
      return;
    }
    if (optionsMap && optionsMap[code]) {
      capacityChip.textContent = optionsMap[code].capacity || "—";
    } else {
      capacityChip.textContent = "—";
    }
  }

  function syncUnlinkedClass(cell) {
    if (!cell) return;
    var picker = cell.querySelector(".planogram-product-picker");
    var unlinked = Boolean(picker && picker.getAttribute("data-unlinked") === "true");
    cell.classList.toggle("planogram-product-unlinked", unlinked);
  }

  function cellHasData(cell) {
    if (!cell) return false;
    var idInput = domainIdField(cell);
    var codeInput = codeField(cell);
    var lineInput = cell.querySelector('input[name="planogram_line_number"]');
    var id = idInput ? (idInput.value || "").trim() : "";
    var code = codeInput ? (codeInput.value || "").trim() : "";
    var line = lineInput ? (lineInput.value || "").trim() : "";
    return Boolean(id || code || line);
  }

  function findCell(grid, shelfIndex, slotIndex) {
    return grid.querySelector(
      '.planogram-cell[data-shelf="' + shelfIndex + '"][data-slot="' + slotIndex + '"]'
    );
  }

  function clearCellFields(cell) {
    if (!cell) return;
    var idInput = domainIdField(cell);
    var codeInput = codeField(cell);
    var lineInput = cell.querySelector('input[name="planogram_line_number"]');
    if (idInput) idInput.value = "";
    if (codeInput) codeInput.value = "";
    if (lineInput) lineInput.value = "";
    var link = cell.querySelector(".planogram-product-link");
    if (link) {
      link.textContent = "";
      link.removeAttribute("href");
    }
    var search = cell.querySelector(".planogram-product-search");
    if (search) {
      search.value = "";
      search.hidden = false;
    }
    var selected = cell.querySelector(".planogram-product-selected");
    if (selected) selected.hidden = true;
    var clearBtn = cell.querySelector(".planogram-product-clear");
    if (clearBtn) clearBtn.hidden = true;
    var picker = cell.querySelector(".planogram-product-picker");
    if (picker) picker.removeAttribute("data-unlinked");
    cell.classList.remove("planogram-product-unlinked");
    var stockChip = cell.querySelector(".chip-stock");
    var capacityChip = cell.querySelector(".chip-capacity");
    if (stockChip) stockChip.textContent = "—";
    if (capacityChip) capacityChip.textContent = "";
    Array.prototype.forEach.call(
      cell.querySelectorAll(".chip-calculated, .chip-current"),
      function (chip) {
        chip.textContent = "—";
      }
    );
    cell.classList.remove("admin-planogram-duplicate");
  }

  function setSpanState(anchorCell, span) {
    var button = spanToggleButton(anchorCell);
    if (!button) return;
    button.setAttribute("data-span", span);
    button.textContent = span;
    if (span === "2") {
      anchorCell.classList.add("planogram-cell--double");
      anchorCell.style.gridColumn = "span 2";
    } else {
      anchorCell.classList.remove("planogram-cell--double");
      anchorCell.style.gridColumn = "span 1";
    }
  }

  function canMergeRight(shelfIndex, slotIndex, slotsPerShelf) {
    return slotIndex % 2 === 0 && slotIndex + 1 < slotsPerShelf;
  }

  function canMergeLeft(slotIndex) {
    return slotIndex % 2 === 1 && slotIndex > 0;
  }

  function buildPickerMarkup() {
    var root = document.createElement("div");
    root.className = "planogram-product-picker";

    var search = document.createElement("input");
    search.type = "search";
    search.className = "planogram-product-search admin-cell-input";
    search.placeholder = "Название товара…";
    search.setAttribute("autocomplete", "off");
    search.setAttribute("aria-label", "Поиск товара");
    search.setAttribute("aria-autocomplete", "list");
    root.appendChild(search);

    var selected = document.createElement("span");
    selected.className = "planogram-product-selected";
    selected.hidden = true;
    var link = document.createElement("a");
    link.className = "planogram-product-link";
    link.target = "_blank";
    link.rel = "noopener";
    selected.appendChild(link);
    root.appendChild(selected);

    var clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "planogram-product-clear";
    clearBtn.setAttribute("aria-label", "Убрать товар");
    clearBtn.textContent = "\u2715";
    clearBtn.hidden = true;
    root.appendChild(clearBtn);

    var idInput = document.createElement("input");
    idInput.type = "hidden";
    idInput.className = "planogram-domain-product-id";
    idInput.name = "planogram_domain_product_id";
    idInput.value = "";
    root.appendChild(idInput);

    var codeInput = document.createElement("input");
    codeInput.type = "hidden";
    codeInput.className = "planogram-legacy-product-code";
    codeInput.name = "planogram_product_code";
    codeInput.value = "";
    root.appendChild(codeInput);

    var options = document.createElement("ul");
    options.className = "planogram-product-options";
    options.hidden = true;
    options.setAttribute("role", "listbox");
    root.appendChild(options);
    return root;
  }

  function buildEmptyCell(shelfIndex, slotIndex, slotsPerShelf) {
    var mergeAnchorSlot = slotIndex % 2 === 0 ? slotIndex : slotIndex - 1;
    var mergeDirection = slotIndex % 2 === 0 ? "right" : "left";
    var article = document.createElement("article");
    article.className = "planogram-cell";
    article.setAttribute("data-shelf", String(shelfIndex));
    article.setAttribute("data-slot", String(slotIndex));
    article.style.gridColumn = "span 1";

    var shelfHidden = document.createElement("input");
    shelfHidden.type = "hidden";
    shelfHidden.name = "planogram_shelf_index";
    shelfHidden.value = String(shelfIndex);
    article.appendChild(shelfHidden);

    var slotHidden = document.createElement("input");
    slotHidden.type = "hidden";
    slotHidden.name = "planogram_slot_index";
    slotHidden.value = String(slotIndex);
    article.appendChild(slotHidden);

    article.appendChild(buildPickerMarkup());

    var metricsRow = document.createElement("div");
    metricsRow.className = "planogram-cell-row planogram-cell-row-metrics";

    var lineChip = document.createElement("span");
    lineChip.className = "chip chip-line";
    var lineInput = document.createElement("input");
    lineInput.name = "planogram_line_number";
    lineInput.value = "";
    lineInput.setAttribute("aria-label", "№ линии");
    lineChip.appendChild(lineInput);
    metricsRow.appendChild(lineChip);

    var stockGroup = document.createElement("span");
    stockGroup.className = "chip-group chip-group-stock";
    stockGroup.setAttribute("title", "ост · ёмк");
    var stockChip = document.createElement("span");
    stockChip.className = "chip chip-stock";
    stockChip.setAttribute("aria-label", "ост");
    stockChip.setAttribute("title", "загрузка = max(0, ёмк − ост)");
    stockChip.textContent = "—";
    var capacityChip = document.createElement("span");
    capacityChip.className = "chip chip-capacity";
    capacityChip.setAttribute("aria-label", "ёмк");
    capacityChip.setAttribute("title", "загрузка = max(0, ёмк − ост)");
    capacityChip.textContent = "";
    stockGroup.appendChild(stockChip);
    stockGroup.appendChild(capacityChip);
    metricsRow.appendChild(stockGroup);
    article.appendChild(metricsRow);

    var priceRow = document.createElement("div");
    priceRow.className = "planogram-cell-row planogram-cell-row-price";

    var spanToggle = document.createElement("button");
    spanToggle.type = "button";
    spanToggle.className = "planogram-span-toggle";
    spanToggle.setAttribute("data-span", "1");
    spanToggle.setAttribute("data-merge", shelfIndex + ":" + mergeAnchorSlot);
    spanToggle.setAttribute("data-merge-direction", mergeDirection);
    spanToggle.setAttribute("title", "Ширина: 1 = одинарная, 2 = двойная");
    spanToggle.setAttribute("aria-label", "Ширина ячейки");
    spanToggle.textContent = "1";
    priceRow.appendChild(spanToggle);

    var priceGroup = document.createElement("span");
    priceGroup.className = "chip-group chip-group-price";
    priceGroup.setAttribute("title", "расч · тек");
    ["расч", "тек"].forEach(function (label) {
      var chip = document.createElement("span");
      chip.className = label === "расч" ? "chip chip-calculated" : "chip chip-current";
      chip.setAttribute("aria-label", label);
      chip.textContent = "—";
      priceGroup.appendChild(chip);
    });
    priceRow.appendChild(priceGroup);
    article.appendChild(priceRow);
    return article;
  }

  function positionNameSuggestions(list, wrap) {
    if (!list || !wrap) return;
    var margin = 16;
    list.style.left = "";
    list.style.right = "";

    var listRect = list.getBoundingClientRect();
    var wrapRect = wrap.getBoundingClientRect();

    if (listRect.right > window.innerWidth - margin) {
      list.style.left = "auto";
      list.style.right = "0";
      listRect = list.getBoundingClientRect();
    }
    if (listRect.left < margin) {
      var maxLeft = window.innerWidth - listRect.width - margin;
      var leftPx = Math.max(margin, Math.min(wrapRect.left, maxLeft));
      list.style.right = "auto";
      list.style.left = leftPx - wrapRect.left + "px";
    }
  }

  function hideSuggestions(list) {
    list.hidden = true;
    list.innerHTML = "";
    list.style.left = "";
    list.style.right = "";
  }

  function bindNameAutocomplete(cell, optionsMap, allNames) {
    // SKU name autocomplete removed; domain-product picker owns selection.
  }

  function bindCellInputs(cell, optionsMap, allNames) {
    syncCapacityFromCode(cell, optionsMap);
    syncUnlinkedClass(cell);
  }

  function bindSpanToggle(button, grid, optionsMap, allNames) {
    button.addEventListener("click", function () {
      var direction = button.getAttribute("data-merge-direction") || "right";
      var parts = (button.getAttribute("data-merge") || "").split(":");
      if (parts.length !== 2) return;
      var shelfIndex = parseInt(parts[0], 10);
      var anchorSlot = parseInt(parts[1], 10);
      if (Number.isNaN(shelfIndex) || Number.isNaN(anchorSlot)) return;
      var slotsPerShelf = parseInt(grid.getAttribute("data-slots-per-shelf") || "10", 10);
      var current = button.getAttribute("data-span") === "2" ? "2" : "1";

      if (direction === "right") {
        var anchorCell = findCell(grid, shelfIndex, anchorSlot);
        if (!anchorCell) return;
        if (current === "1") {
          if (!canMergeRight(shelfIndex, anchorSlot, slotsPerShelf)) return;
          var rightCell = findCell(grid, shelfIndex, anchorSlot + 1);
          if (rightCell && cellHasData(rightCell)) {
            if (!window.confirm("Правый слот будет очищен")) {
              return;
            }
          }
          if (rightCell) {
            clearCellFields(rightCell);
            rightCell.remove();
          }
          setSpanState(anchorCell, "2");
          return;
        }
        setSpanState(anchorCell, "1");
        var restoredRight = findCell(grid, shelfIndex, anchorSlot + 1);
        if (!restoredRight) {
          restoredRight = buildEmptyCell(shelfIndex, anchorSlot + 1, slotsPerShelf);
          anchorCell.parentNode.insertBefore(restoredRight, anchorCell.nextSibling);
          bindCellInputs(restoredRight, optionsMap, allNames);
          var nestedToggle = restoredRight.querySelector(".planogram-span-toggle");
          if (nestedToggle) bindSpanToggle(nestedToggle, grid, optionsMap, allNames);
        }
        return;
      }

      var leftCell = findCell(grid, shelfIndex, anchorSlot);
      var selfCell = button.closest(".planogram-cell");
      if (!leftCell || !selfCell) return;
      if (current === "1") {
        if (!canMergeLeft(parseInt(selfCell.getAttribute("data-slot") || "-1", 10))) return;
        if (cellHasData(leftCell) || cellHasData(selfCell)) {
          if (!window.confirm("Слоты будут объединены, правый будет очищен")) {
            return;
          }
        }
        clearCellFields(selfCell);
        selfCell.remove();
        setSpanState(leftCell, "2");
      }
    });
  }

  function bindAllCells(grid, optionsMap, allNames) {
    Array.prototype.forEach.call(grid.querySelectorAll(".planogram-cell"), function (cell) {
      bindCellInputs(cell, optionsMap, allNames);
    });
    Array.prototype.forEach.call(
      grid.querySelectorAll(".planogram-span-toggle"),
      function (button) {
        bindSpanToggle(button, grid, optionsMap, allNames);
      }
    );
  }

  function clearDuplicateMarks(grid) {
    Array.prototype.forEach.call(grid.querySelectorAll(".planogram-cell"), function (cell) {
      cell.classList.remove("admin-planogram-duplicate");
    });
  }

  function validateDuplicates(grid, errorEl) {
    clearDuplicateMarks(grid);
    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
    var seen = {};
    var hasDup = false;
    Array.prototype.forEach.call(grid.querySelectorAll(".planogram-cell"), function (cell) {
      var idInput = domainIdField(cell);
      var codeInput = codeField(cell);
      var lineInput = cell.querySelector('input[name="planogram_line_number"]');
      if (!lineInput) return;
      var id = idInput ? (idInput.value || "").trim() : "";
      var code = codeInput ? (codeInput.value || "").trim() : "";
      if (!id && !code) return;
      var line = (lineInput.value || "").trim();
      if (!line) return;
      if (seen[line]) {
        hasDup = true;
        cell.classList.add("admin-planogram-duplicate");
        seen[line].classList.add("admin-planogram-duplicate");
      } else {
        seen[line] = cell;
      }
    });
    if (hasDup && errorEl) {
      errorEl.textContent = "Дублируется номер ячейки среди строк с товаром";
      errorEl.hidden = false;
    }
    return !hasDup;
  }

  function appendMergeHiddenFields(form, grid) {
    Array.prototype.forEach.call(
      form.querySelectorAll('input[name="planogram_merge_shelf"]'),
      function (node) {
        node.remove();
      }
    );
    Array.prototype.forEach.call(
      form.querySelectorAll('input[name="planogram_merge_slot"]'),
      function (node) {
        node.remove();
      }
    );
    Array.prototype.forEach.call(
      grid.querySelectorAll('.planogram-span-toggle[data-span="2"]'),
      function (button) {
        var parts = (button.getAttribute("data-merge") || "").split(":");
        if (parts.length !== 2) return;
        var shelfHidden = document.createElement("input");
        shelfHidden.type = "hidden";
        shelfHidden.name = "planogram_merge_shelf";
        shelfHidden.value = parts[0];
        form.appendChild(shelfHidden);
        var slotHidden = document.createElement("input");
        slotHidden.type = "hidden";
        slotHidden.name = "planogram_merge_slot";
        slotHidden.value = parts[1];
        form.appendChild(slotHidden);
      }
    );
  }

  function clampDimension(value, min, max) {
    if (Number.isNaN(value)) return min;
    return Math.min(max, Math.max(min, value));
  }

  // Keep in sync with planogram_resize.js (loaded only in node tests).
  function cellSnapshotHasData(cell) {
    if (!cell) return false;
    var product = String(cell.product || "").trim();
    var line = String(cell.line || "").trim();
    return Boolean(product || line || cell.merge);
  }

  function mergeCrossesCut(cell, newShelves, newSlots) {
    if (!cell || !cell.merge) return false;
    var shelf = Number(cell.shelf);
    var slot = Number(cell.slot);
    if (Number.isNaN(shelf) || Number.isNaN(slot)) return false;
    if (shelf >= newShelves) return false;
    if (slot >= newSlots) return false;
    return slot + 2 > newSlots;
  }

  function sliceHasData(cells, oldShelves, oldSlots, newShelves, newSlots) {
    if (newShelves >= oldShelves && newSlots >= oldSlots) return false;
    var list = cells || [];
    for (var i = 0; i < list.length; i += 1) {
      var cell = list[i];
      var shelf = Number(cell.shelf);
      var slot = Number(cell.slot);
      if (Number.isNaN(shelf) || Number.isNaN(slot)) continue;
      var inCutRegion = shelf >= newShelves || slot >= newSlots;
      if (inCutRegion && cellSnapshotHasData(cell)) return true;
      if (mergeCrossesCut(cell, newShelves, newSlots)) return true;
    }
    return false;
  }

  function applyResize(cells, oldShelves, oldSlots, newShelves, newSlots, confirmed) {
    var list = cells || [];
    var shrinking = newShelves < oldShelves || newSlots < oldSlots;
    if (
      shrinking &&
      sliceHasData(list, oldShelves, oldSlots, newShelves, newSlots) &&
      !confirmed
    ) {
      return {
        cells: list,
        shelves: oldShelves,
        slots: oldSlots,
        needsConfirm: true,
      };
    }

    var next = [];
    for (var i = 0; i < list.length; i += 1) {
      var cell = list[i];
      var shelf = Number(cell.shelf);
      var slot = Number(cell.slot);
      if (Number.isNaN(shelf) || Number.isNaN(slot)) continue;
      if (shelf >= newShelves || slot >= newSlots) continue;
      var copy = {
        shelf: shelf,
        slot: slot,
        product: cell.product,
        line: cell.line,
        merge: Boolean(cell.merge),
      };
      if (copy.merge && slot + 2 > newSlots) {
        copy.merge = false;
      }
      next.push(copy);
    }

    return {
      cells: next,
      shelves: newShelves,
      slots: newSlots,
      needsConfirm: false,
    };
  }

  function serializeGridCells(grid) {
    var snapshots = [];
    Array.prototype.forEach.call(grid.querySelectorAll(".planogram-cell"), function (cell) {
      var idInput = domainIdField(cell);
      var codeInput = codeField(cell);
      var lineInput = cell.querySelector('input[name="planogram_line_number"]');
      var btn = spanToggleButton(cell);
      var id = idInput ? (idInput.value || "").trim() : "";
      var code = codeInput ? (codeInput.value || "").trim() : "";
      snapshots.push({
        shelf: parseInt(cell.getAttribute("data-shelf") || "-1", 10),
        slot: parseInt(cell.getAttribute("data-slot") || "-1", 10),
        product: id || code,
        line: lineInput ? (lineInput.value || "").trim() : "",
        merge: btn ? btn.getAttribute("data-span") === "2" : false,
      });
    });
    return snapshots;
  }

  function slotCoveredByMerge(grid, shelfIndex, slotIndex) {
    if (slotIndex % 2 !== 1) return false;
    var left = findCell(grid, shelfIndex, slotIndex - 1);
    if (!left) return false;
    var btn = spanToggleButton(left);
    return Boolean(btn && btn.getAttribute("data-span") === "2");
  }

  function insertCellInGridOrder(grid, cell, shelfIndex, slotIndex, slotsPerShelf) {
    var cells = grid.querySelectorAll(".planogram-cell");
    var insertBefore = null;
    for (var i = 0; i < cells.length; i += 1) {
      var other = cells[i];
      var otherShelf = parseInt(other.getAttribute("data-shelf") || "-1", 10);
      var otherSlot = parseInt(other.getAttribute("data-slot") || "-1", 10);
      var otherOrder = otherShelf * slotsPerShelf + otherSlot;
      var selfOrder = shelfIndex * slotsPerShelf + slotIndex;
      if (otherOrder > selfOrder) {
        insertBefore = other;
        break;
      }
    }
    if (insertBefore) {
      grid.insertBefore(cell, insertBefore);
    } else {
      grid.appendChild(cell);
    }
  }

  function bindNewCell(cell, grid, optionsMap, allNames) {
    bindCellInputs(cell, optionsMap, allNames);
    var nestedToggle = cell.querySelector(".planogram-span-toggle");
    if (nestedToggle) bindSpanToggle(nestedToggle, grid, optionsMap, allNames);
  }

  function applyResizeToDom(grid, newShelves, newSlots, optionsMap, allNames) {
    Array.prototype.forEach.call(
      grid.querySelectorAll(".planogram-cell"),
      function (cell) {
        var shelf = parseInt(cell.getAttribute("data-shelf") || "-1", 10);
        var slot = parseInt(cell.getAttribute("data-slot") || "-1", 10);
        if (shelf >= newShelves || slot >= newSlots) {
          cell.remove();
          return;
        }
        var btn = spanToggleButton(cell);
        if (btn && btn.getAttribute("data-span") === "2" && slot + 2 > newSlots) {
          setSpanState(cell, "1");
        }
      }
    );

    for (var shelf = 0; shelf < newShelves; shelf += 1) {
      for (var slot = 0; slot < newSlots; slot += 1) {
        if (findCell(grid, shelf, slot)) continue;
        if (slotCoveredByMerge(grid, shelf, slot)) continue;
        var empty = buildEmptyCell(shelf, slot, newSlots);
        insertCellInGridOrder(grid, empty, shelf, slot, newSlots);
        bindNewCell(empty, grid, optionsMap, allNames);
      }
    }

    grid.style.setProperty("--planogram-cols", String(newSlots));
    grid.setAttribute("data-shelf-count", String(newShelves));
    grid.setAttribute("data-slots-per-shelf", String(newSlots));
  }

  function handleDimensionChange(grid, optionsMap, allNames) {
    var shelfInput = qs("planogram-shelf-count");
    var slotsInput = qs("planogram-slots-per-shelf");
    if (!shelfInput || !slotsInput) return;
    var newShelves = clampDimension(parseInt(shelfInput.value, 10), 1, 20);
    var newSlots = clampDimension(parseInt(slotsInput.value, 10), 1, 20);
    shelfInput.value = String(newShelves);
    slotsInput.value = String(newSlots);
    var currentShelves = parseInt(grid.getAttribute("data-shelf-count") || "0", 10);
    var currentSlots = parseInt(grid.getAttribute("data-slots-per-shelf") || "0", 10);
    if (newShelves === currentShelves && newSlots === currentSlots) return;

    var snapshots = serializeGridCells(grid);
    var result = applyResize(
      snapshots,
      currentShelves,
      currentSlots,
      newShelves,
      newSlots,
      false
    );
    if (result.needsConfirm) {
      var ok = window.confirm(
        "В срезаемой полосе есть данные (товар, № линии или объединение). " +
          "Удалить правую колонку и/или нижний ряд?"
      );
      if (!ok) {
        shelfInput.value = String(currentShelves);
        slotsInput.value = String(currentSlots);
        return;
      }
      result = applyResize(
        snapshots,
        currentShelves,
        currentSlots,
        newShelves,
        newSlots,
        true
      );
    }
    applyResizeToDom(grid, result.shelves, result.slots, optionsMap, allNames);
  }

  function init() {
    var grid = qs("planogram-grid");
    var form = qs("machine-planogram-form") || qs("machine-profile-form");
    if (!grid || !form) return;
    var optionsMap = parseOptionsMap();
    var allNames = productNamesFromOptions(optionsMap);
    var errorEl = qs("layout-client-error");

    bindAllCells(grid, optionsMap, allNames);

    document.addEventListener("click", function () {
      setTimeout(function () {
        Array.prototype.forEach.call(grid.querySelectorAll(".planogram-cell"), function (cell) {
          syncCapacityFromCode(cell, optionsMap);
          syncUnlinkedClass(cell);
        });
      }, 0);
    });

    var shelfInput = qs("planogram-shelf-count");
    var slotsInput = qs("planogram-slots-per-shelf");
    if (shelfInput) {
      shelfInput.addEventListener("change", function () {
        handleDimensionChange(grid, optionsMap, allNames);
      });
    }
    if (slotsInput) {
      slotsInput.addEventListener("change", function () {
        handleDimensionChange(grid, optionsMap, allNames);
      });
    }

    form.addEventListener("submit", function (event) {
      appendMergeHiddenFields(form, grid);
      if (!validateDuplicates(grid, errorEl)) {
        event.preventDefault();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
