/* Micromarket planogram shelves: per-shelf enroll, alpha insert, shelf DnD,
 * select move, collapse (session-only), clear empty shelf, reindex on submit.
 *
 * Product rows are not draggable. Sort key via MicromarketPlanogramSortKey.
 */
(function (root) {
  var SHELVES_ID = "micromarket-planogram-shelves";
  var FORM_ID = "micromarket-planogram-form";
  // Indexed field prefixes: domain_product_id- product_code- target_qty-
  // price_rub- kit_group_id- pending_exit- ; shelves: shelf_kit_group_id-
  var INDEXED_NAME_RE =
    /^(domain_product_id|product_code|target_qty|price_rub|kit_group_id|pending_exit)-(\d+)$/;
  var SHELF_NAME_RE = /^(shelf_kit_group_id)-(\d+)$/;

  var dragShelf = null;
  var installed = false;

  function sortApi() {
    if (root && root.MicromarketPlanogramSortKey) return root.MicromarketPlanogramSortKey;
    if (typeof window !== "undefined" && window.MicromarketPlanogramSortKey) {
      return window.MicromarketPlanogramSortKey;
    }
    return null;
  }

  function shelvesRoot() {
    return document.getElementById(SHELVES_ID);
  }

  function shelfSections() {
    var root = shelvesRoot();
    if (!root) return [];
    return Array.prototype.filter.call(root.children, function (el) {
      return (
        el.classList &&
        el.classList.contains("planogram-shelf") &&
        !el.classList.contains("planogram-ungrouped")
      );
    });
  }

  function shelfOf(el) {
    return el ? el.closest(".planogram-shelf") : null;
  }

  function shelfTbody(shelf) {
    if (!shelf) return null;
    var table = shelf.querySelector("table.planogram-shelf-table");
    return table ? table.tBodies[0] : null;
  }

  function rowHasProduct(row) {
    var idInput = row.querySelector(".planogram-domain-product-id");
    var codeInput = row.querySelector(".planogram-legacy-product-code");
    var idVal = idInput ? String(idInput.value || "").trim() : "";
    var codeVal = codeInput ? String(codeInput.value || "").trim() : "";
    return idVal !== "" || codeVal !== "";
  }

  function productRows(tbody) {
    if (!tbody) return [];
    return Array.prototype.filter.call(tbody.rows, function (row) {
      return !row.classList.contains("planogram-enroll-row") && rowHasProduct(row);
    });
  }

  function rowDisplayName(row) {
    var link = row.querySelector(".planogram-product-link");
    if (link && String(link.textContent || "").trim()) {
      return String(link.textContent || "").trim();
    }
    var legacy = row.querySelector(".planogram-product-legacy");
    if (legacy && String(legacy.textContent || "").trim()) {
      return String(legacy.textContent || "").trim();
    }
    var codeInput = row.querySelector(".planogram-legacy-product-code");
    return codeInput ? String(codeInput.value || "").trim() : "";
  }

  function rowPendingExit(row) {
    if (!row) return false;
    if (row.classList.contains("planogram-pending-exit")) return true;
    var pendingExit = row.querySelector('input[name^="pending_exit-"]');
    return pendingExit ? String(pendingExit.value || "").trim() !== "" : false;
  }

  function rowSortLine(row) {
    var idInput = row.querySelector(".planogram-domain-product-id");
    var codeInput = row.querySelector(".planogram-legacy-product-code");
    return {
      name: rowDisplayName(row),
      domainProductId: idInput ? String(idInput.value || "").trim() : "",
      productCode: codeInput ? String(codeInput.value || "").trim() : "",
      pendingExit: rowPendingExit(row),
    };
  }

  function setClearButtonMode(row, mode) {
    var picker = row.querySelector(".planogram-product-picker");
    if (!picker) return;
    var btn =
      picker.querySelector(".planogram-product-clear, .planogram-product-restore") || null;
    if (!btn) return;
    if (mode === "restore") {
      btn.classList.remove("planogram-product-clear");
      btn.classList.add("planogram-product-restore");
      btn.setAttribute("aria-label", "Вернуть товар");
      btn.textContent = "↩";
      btn.hidden = false;
    } else {
      btn.classList.remove("planogram-product-restore");
      btn.classList.add("planogram-product-clear");
      btn.setAttribute("aria-label", "Убрать товар");
      btn.textContent = "✕";
    }
  }

  function softRemovePersistedRow(row) {
    if (!row || row.getAttribute("data-persisted") !== "1") return;
    var pendingExit = row.querySelector('input[name^="pending_exit-"]');
    if (pendingExit) pendingExit.value = "1";
    row.classList.add("planogram-pending-exit");
    setClearButtonMode(row, "restore");
    var shelf = shelfOf(row);
    if (shelf && !shelf.classList.contains("planogram-ungrouped")) {
      insertRowBySortKey(shelf, row);
      updateShelfClearButton(shelf);
    }
    reindexRowNames();
  }

  function restorePersistedRow(row) {
    if (!row) return;
    var pendingExit = row.querySelector('input[name^="pending_exit-"]');
    if (pendingExit) pendingExit.value = "";
    row.classList.remove("planogram-pending-exit");
    setClearButtonMode(row, "clear");
    var shelf = shelfOf(row);
    if (shelf && !shelf.classList.contains("planogram-ungrouped")) {
      insertRowBySortKey(shelf, row);
      updateShelfClearButton(shelf);
    }
    reindexRowNames();
  }

  function clearPickerState(picker) {
    if (!picker) return;
    var idInput = picker.querySelector(".planogram-domain-product-id");
    var codeInput = picker.querySelector(".planogram-legacy-product-code");
    var link = picker.querySelector(".planogram-product-link");
    var search = picker.querySelector(".planogram-product-search");
    var selected = picker.querySelector(".planogram-product-selected");
    var clearBtn = picker.querySelector(".planogram-product-clear");
    var moveBtn = picker.querySelector(".planogram-product-move");
    var options = picker.querySelector(".planogram-product-options");
    if (idInput) idInput.value = "";
    if (codeInput) codeInput.value = "";
    if (link) {
      link.textContent = "";
      link.removeAttribute("href");
    }
    var legacy = picker.querySelector(".planogram-product-legacy");
    if (legacy) legacy.remove();
    if (!link && selected) {
      selected.textContent = "";
      link = document.createElement("a");
      link.className = "planogram-product-link";
      link.target = "_blank";
      link.rel = "noopener";
      selected.appendChild(link);
    }
    picker.removeAttribute("data-unlinked");
    if (search) {
      search.hidden = false;
      search.value = "";
    }
    if (selected) selected.hidden = true;
    if (clearBtn) clearBtn.hidden = true;
    if (moveBtn) moveBtn.hidden = true;
    if (options) {
      options.hidden = true;
      options.innerHTML = "";
    }
  }

  function resetRowToEmpty(row) {
    clearPickerState(row.querySelector(".planogram-product-picker"));
    row.classList.remove("planogram-product-unlinked", "planogram-pending-exit");
    var target = row.querySelector('input[name^="target_qty-"]');
    var price = row.querySelector('input[name^="price_rub-"]');
    var pendingExit = row.querySelector('input[name^="pending_exit-"]');
    var groupHidden = row.querySelector(
      'input.planogram-kit-group-id, input[type="hidden"][name^="kit_group_id-"]',
    );
    var moveSelect = row.querySelector("select.planogram-move-shelf");
    if (target) target.value = "0";
    if (price) price.value = "";
    if (pendingExit) pendingExit.value = "";
    if (groupHidden) groupHidden.value = "";
    if (moveSelect) moveSelect.value = "";
  }

  function syncQtySteppers(root) {
    // AdminQuantityStepper uses document click/blur delegation; re-sync
    // disabled buttons after enroll clone / reindex.
    var api = window.AdminQuantityStepper;
    if (api && typeof api.initAll === "function") {
      api.initAll(root || document);
    }
  }

  function cloneEmptyRow(templateRow) {
    var clone = templateRow.cloneNode(true);
    resetRowToEmpty(clone);
    clone.removeAttribute("data-persisted");
    clone.classList.add("planogram-enroll-row");
    clone.classList.remove("planogram-dragging", "planogram-drop-target", "planogram-pending-exit");
    setClearButtonMode(clone, "clear");
    var clearBtn = clone.querySelector(".planogram-product-clear, .planogram-product-restore");
    if (clearBtn) clearBtn.hidden = true;
    var moveBtn = clone.querySelector(".planogram-product-move");
    if (moveBtn) moveBtn.hidden = true;
    syncQtySteppers(clone);
    return clone;
  }

  function shelfKitGroupId(shelf) {
    if (!shelf) return "";
    var fromData = shelf.getAttribute("data-kit-group-id");
    if (fromData) return String(fromData);
    var hidden = shelf.querySelector('input[name^="shelf_kit_group_id-"]');
    return hidden ? String(hidden.value || "") : "";
  }

  function setRowShelfSelect(row, kitGroupId) {
    var groupHidden = row.querySelector(
      'input.planogram-kit-group-id, input[type="hidden"][name^="kit_group_id-"]',
    );
    var moveSelect = row.querySelector("select.planogram-move-shelf");
    var value = kitGroupId == null ? "" : String(kitGroupId);
    if (groupHidden) groupHidden.value = value;
    if (moveSelect) {
      moveSelect.value = "";
      Array.prototype.forEach.call(moveSelect.options, function (option) {
        if (!option.value) return;
        option.hidden = option.value === value;
        if (option.value === value) option.selected = false;
      });
    }
  }

  function updateShelfClearButton(shelf) {
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) return;
    var btn = shelf.querySelector(".planogram-shelf-clear");
    if (!btn) return;
    var tbody = shelfTbody(shelf);
    var hasProduct = productRows(tbody).length > 0;
    btn.disabled = hasProduct;
  }

  function ensureShelfEnrollRow(shelf) {
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) return;
    var tbody = shelfTbody(shelf);
    if (!tbody) return;

    var enrolls = Array.prototype.filter.call(tbody.rows, function (row) {
      return row.classList.contains("planogram-enroll-row") || !rowHasProduct(row);
    });
    var productCount = productRows(tbody).length;
    var emptyRows = Array.prototype.filter.call(tbody.rows, function (row) {
      return !rowHasProduct(row);
    });

    while (emptyRows.length > 1) {
      var lastEmpty = emptyRows[emptyRows.length - 1];
      tbody.removeChild(lastEmpty);
      emptyRows.pop();
    }

    if (emptyRows.length === 0) {
      var template =
        tbody.rows.length > 0 ? tbody.rows[tbody.rows.length - 1] : null;
      if (!template && enrolls.length) template = enrolls[0];
      if (template) {
        var enroll = cloneEmptyRow(template);
        setRowShelfSelect(enroll, shelfKitGroupId(shelf));
        tbody.appendChild(enroll);
      }
    } else {
      var enrollRow = emptyRows[0];
      enrollRow.classList.add("planogram-enroll-row");
      setRowShelfSelect(enrollRow, shelfKitGroupId(shelf));
      if (enrollRow !== tbody.rows[tbody.rows.length - 1]) {
        tbody.appendChild(enrollRow);
      }
    }

    void productCount;
    updateShelfClearButton(shelf);
  }

  function ensureAllShelfEnrollRows() {
    shelfSections().forEach(ensureShelfEnrollRow);
  }

  function insertRowBySortKey(shelf, row) {
    var tbody = shelfTbody(shelf);
    var api = sortApi();
    if (!tbody || !row) return;
    row.classList.remove("planogram-enroll-row");
    setRowShelfSelect(row, shelfKitGroupId(shelf));

    var enroll = Array.prototype.find.call(tbody.rows, function (r) {
      return r.classList.contains("planogram-enroll-row") || !rowHasProduct(r);
    });

    if (!api || !api.comparePlanogramLines) {
      if (enroll) tbody.insertBefore(row, enroll);
      else tbody.appendChild(row);
      ensureShelfEnrollRow(shelf);
      return;
    }

    var line = rowSortLine(row);
    var inserted = false;
    var products = productRows(tbody).filter(function (r) {
      return r !== row;
    });
    for (var i = 0; i < products.length; i++) {
      if (api.comparePlanogramLines(line, rowSortLine(products[i])) < 0) {
        tbody.insertBefore(row, products[i]);
        inserted = true;
        break;
      }
    }
    if (!inserted) {
      if (enroll) tbody.insertBefore(row, enroll);
      else tbody.appendChild(row);
    }
    ensureShelfEnrollRow(shelf);
  }

  function shelfOptionLabel(kitGroupId) {
    var want = String(kitGroupId || "");
    var root = shelvesRoot();
    if (!root || !want) return want;
    var source = root.querySelector("select.planogram-move-shelf");
    if (!source) return want;
    var match = Array.prototype.find.call(source.options, function (option) {
      return String(option.value || "") === want;
    });
    if (match && String(match.textContent || "").trim()) {
      return String(match.textContent || "").trim();
    }
    return want;
  }

  function createShelfSection(kitGroupId) {
    var template = document.getElementById("planogram-shelf-template");
    var root = shelvesRoot();
    if (!template || !root || !template.content) return null;
    var fragment =
      typeof document.importNode === "function"
        ? document.importNode(template.content, true)
        : template.content.cloneNode(true);
    var shelf = fragment.querySelector(".planogram-shelf");
    if (!shelf) return null;
    var groupId = String(kitGroupId || "");
    shelf.setAttribute("data-kit-group-id", groupId);
    var hidden = shelf.querySelector('input[name^="shelf_kit_group_id-"]');
    if (hidden) hidden.value = groupId;
    var label = shelf.querySelector(".planogram-shelf-label");
    if (label) label.textContent = shelfOptionLabel(groupId);
    var ungrouped = root.querySelector(".planogram-ungrouped");
    if (ungrouped) root.insertBefore(shelf, ungrouped);
    else root.appendChild(shelf);
    bindShelfChrome(shelf);
    ensureShelfEnrollRow(shelf);
    var tbody = shelfTbody(shelf);
    if (tbody) {
      Array.prototype.forEach.call(tbody.rows, bindShelfMove);
    }
    return shelf;
  }

  function removeEmptyUngrouped() {
    var root = shelvesRoot();
    if (!root || shelfSections().length === 0) return;
    var ungrouped = root.querySelector(".planogram-ungrouped");
    if (!ungrouped) return;
    if (productRows(shelfTbody(ungrouped)).length > 0) return;
    ungrouped.parentNode.removeChild(ungrouped);
  }

  function findShelfByKitGroupId(kitGroupId) {
    var want = String(kitGroupId || "");
    return (
      shelfSections().find(function (shelf) {
        return shelfKitGroupId(shelf) === want;
      }) || null
    );
  }

  function moveRowToShelf(row, targetKitGroupId) {
    var sourceShelf = shelfOf(row);
    var targetShelf = findShelfByKitGroupId(targetKitGroupId);
    if (!row || !targetShelf) return;
    if (sourceShelf === targetShelf) {
      setRowShelfSelect(row, targetKitGroupId);
      insertRowBySortKey(targetShelf, row);
      return;
    }
    setRowShelfSelect(row, targetKitGroupId);
    insertRowBySortKey(targetShelf, row);
    if (sourceShelf) ensureShelfEnrollRow(sourceShelf);
    updateShelfClearButton(sourceShelf);
    updateShelfClearButton(targetShelf);
  }

  function reindexRowNames() {
    var root = shelvesRoot();
    if (!root) return;
    var index = 0;
    Array.prototype.forEach.call(root.querySelectorAll("tbody tr"), function (row) {
      Array.prototype.forEach.call(row.querySelectorAll("[name]"), function (el) {
        var name = el.getAttribute("name") || "";
        var match = INDEXED_NAME_RE.exec(name);
        if (!match) return;
        el.setAttribute("name", match[1] + "-" + index);
      });
      index += 1;
    });
  }

  function reindexShelfNames() {
    shelfSections().forEach(function (shelf, index) {
      Array.prototype.forEach.call(shelf.querySelectorAll("[name]"), function (el) {
        var name = el.getAttribute("name") || "";
        var match = SHELF_NAME_RE.exec(name);
        if (!match) return;
        el.setAttribute("name", match[1] + "-" + index);
      });
    });
  }

  function closeTypeaheadPopups() {
    document.dispatchEvent(new CustomEvent("planogram-close-popups"));
  }

  function bindShelfDnD(shelf) {
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) return;
    var handle = shelf.querySelector(".planogram-drag-handle");
    if (!handle || handle.dataset.dndBound === "1") return;
    handle.dataset.dndBound = "1";
    handle.draggable = true;

    handle.addEventListener("dragstart", function (event) {
      dragShelf = shelf;
      shelf.classList.add("planogram-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "shelf");
      closeTypeaheadPopups();
    });
    handle.addEventListener("dragend", function () {
      shelf.classList.remove("planogram-dragging");
      shelfSections().forEach(function (s) {
        s.classList.remove("planogram-drop-target");
      });
      dragShelf = null;
    });

    shelf.addEventListener("dragover", function (event) {
      if (!dragShelf || dragShelf === shelf) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      shelf.classList.add("planogram-drop-target");
    });
    shelf.addEventListener("dragleave", function () {
      shelf.classList.remove("planogram-drop-target");
    });
    shelf.addEventListener("drop", function (event) {
      event.preventDefault();
      shelf.classList.remove("planogram-drop-target");
      var root = shelvesRoot();
      if (!root || !dragShelf || dragShelf === shelf) return;
      var shelves = shelfSections();
      var from = shelves.indexOf(dragShelf);
      var to = shelves.indexOf(shelf);
      if (from < 0 || to < 0) return;
      if (from < to) {
        root.insertBefore(dragShelf, shelf.nextSibling);
      } else {
        root.insertBefore(dragShelf, shelf);
      }
      reindexShelfNames();
      reindexRowNames();
    });
  }

  function toggleShelfCollapse(shelf) {
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) return;
    var collapsed = shelf.classList.toggle("is-collapsed");
    var btn = shelf.querySelector(".planogram-shelf-collapse");
    if (btn) btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }

  function clearEmptyShelf(shelf) {
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) return;
    var tbody = shelfTbody(shelf);
    if (productRows(tbody).length > 0) return;
    shelf.parentNode && shelf.parentNode.removeChild(shelf);
    reindexShelfNames();
    reindexRowNames();
  }

  function syncMoveButtonVisibility(row) {
    if (!row) return;
    var moveBtn = row.querySelector(".planogram-product-move");
    if (!moveBtn) return;
    moveBtn.hidden = !rowHasProduct(row);
  }

  function onSelectionChanged(row) {
    var shelf = shelfOf(row);
    syncMoveButtonVisibility(row);
    if (!shelf || shelf.classList.contains("planogram-ungrouped")) {
      return;
    }
    if (rowHasProduct(row)) {
      insertRowBySortKey(shelf, row);
    } else {
      ensureShelfEnrollRow(shelf);
    }
    updateShelfClearButton(shelf);
    reindexRowNames();
  }

  function bindShelfChrome(shelf) {
    if (!shelf || shelf.dataset.chromeBound === "1") return;
    shelf.dataset.chromeBound = "1";
    bindShelfDnD(shelf);

    var collapseBtn = shelf.querySelector(".planogram-shelf-collapse");
    if (collapseBtn) {
      collapseBtn.addEventListener("click", function () {
        toggleShelfCollapse(shelf);
      });
    }
    var clearBtn = shelf.querySelector(".planogram-shelf-clear");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        clearEmptyShelf(shelf);
      });
    }
    updateShelfClearButton(shelf);
  }

  function openMoveShelfPicker(select) {
    if (!select) return;
    select.focus();
    if (typeof select.showPicker === "function") {
      try {
        select.showPicker();
        return;
      } catch (_err) {
        /* fall through to click */
      }
    }
    select.click();
  }

  function bindShelfMove(row) {
    var select = row.querySelector("select.planogram-move-shelf");
    if (!select || select.dataset.shelfMoveBound === "1") return;
    select.dataset.shelfMoveBound = "1";
    select.addEventListener("change", function () {
      var value = String(select.value || "").trim();
      if (!value) return;
      var target = findShelfByKitGroupId(value);
      if (!target) {
        target = createShelfSection(value);
      }
      if (!target) {
        select.value = "";
        return;
      }
      moveRowToShelf(row, value);
      removeEmptyUngrouped();
      reindexShelfNames();
      reindexRowNames();
    });
    var moveBtn = row.querySelector(".planogram-product-move");
    if (moveBtn && moveBtn.dataset.moveBound !== "1") {
      moveBtn.dataset.moveBound = "1";
      moveBtn.addEventListener("click", function () {
        openMoveShelfPicker(select);
      });
    }
  }

  function syncPendingExitButtons(root) {
    if (!root) return;
    Array.prototype.forEach.call(root.querySelectorAll("tbody tr"), function (row) {
      if (row.getAttribute("data-persisted") !== "1") return;
      if (rowPendingExit(row)) setClearButtonMode(row, "restore");
    });
  }

  function bindAll() {
    shelfSections().forEach(function (shelf) {
      bindShelfChrome(shelf);
      ensureShelfEnrollRow(shelf);
      var tbody = shelfTbody(shelf);
      if (!tbody) return;
      Array.prototype.forEach.call(tbody.rows, bindShelfMove);
    });
    var ungrouped = shelvesRoot()
      ? shelvesRoot().querySelector(".planogram-ungrouped")
      : null;
    if (ungrouped) {
      var utbody = shelfTbody(ungrouped);
      if (utbody) {
        Array.prototype.forEach.call(utbody.rows, bindShelfMove);
      }
    }
    syncPendingExitButtons(shelvesRoot());
  }

  function markPendingExit(row) {
    softRemovePersistedRow(row);
  }

  function clearPendingExit(row) {
    restorePersistedRow(row);
  }

  function install() {
    if (installed) return;
    if (typeof document === "undefined") return;
    if (!shelvesRoot()) return;
    installed = true;

    document.addEventListener("planogram-product-selection-changed", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) return;
      var row = target.closest("tr");
      var rootEl = shelvesRoot();
      if (!row || !rootEl || !rootEl.contains(row)) return;
      onSelectionChanged(row);
      bindShelfMove(row);
    });

    document.addEventListener("planogram-product-soft-remove", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) return;
      var row = target.closest("tr");
      var rootEl = shelvesRoot();
      if (!row || !rootEl || !rootEl.contains(row)) return;
      softRemovePersistedRow(row);
    });

    document.addEventListener("planogram-product-restore", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) return;
      var row = target.closest("tr");
      var rootEl = shelvesRoot();
      if (!row || !rootEl || !rootEl.contains(row)) return;
      restorePersistedRow(row);
    });

    var form = document.getElementById(FORM_ID);
    if (form) {
      form.addEventListener("submit", function () {
        ensureAllShelfEnrollRows();
        shelfSections().slice().forEach(clearEmptyShelf);
        reindexShelfNames();
        reindexRowNames();
      });
    }

    bindAll();
    shelfSections().forEach(function (shelf) {
      var tbody = shelfTbody(shelf);
      if (!tbody) return;
      Array.prototype.forEach.call(tbody.rows, syncMoveButtonVisibility);
    });
    reindexShelfNames();
    reindexRowNames();
  }

  var api = {
    reindexRowNames: reindexRowNames,
    reindexShelfNames: reindexShelfNames,
    markPendingExit: markPendingExit,
    clearPendingExit: clearPendingExit,
    install: install,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.MicromarketPlanogramTable = api;
  }
  if (typeof document !== "undefined") {
    install();
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
