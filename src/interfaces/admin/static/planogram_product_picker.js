(function () {
  function readOptions() {
    var node = document.getElementById("planogram-domain-product-options");
    if (!node) return [];
    try {
      var parsed = JSON.parse(node.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function pickRoot(target) {
    return target.closest(".planogram-product-picker");
  }

  function filterOptions(query) {
    var q = (query || "").trim().toLowerCase();
    var all = readOptions();
    if (!q) return all.slice();
    return all.filter(function (product) {
      var name = String(product.name || "").toLowerCase();
      var number = String(product.number || "").toLowerCase();
      return name.indexOf(q) !== -1 || number.indexOf(q) !== -1;
    });
  }

  function hideOptions(root) {
    var list = root.querySelector(".planogram-product-options");
    if (!list) return;
    list.hidden = true;
    list.innerHTML = "";
  }

  function setSelectedVisible(root, selected) {
    var search = root.querySelector(".planogram-product-search");
    var selectedEl = root.querySelector(".planogram-product-selected");
    var clearBtn = root.querySelector(".planogram-product-clear");
    if (search) search.hidden = selected;
    if (selectedEl) selectedEl.hidden = !selected;
    if (clearBtn) clearBtn.hidden = !selected;
  }

  function applyProduct(root, product) {
    var idInput = root.querySelector(".planogram-domain-product-id");
    var codeInput = root.querySelector(".planogram-legacy-product-code");
    var link = root.querySelector(".planogram-product-link");
    var search = root.querySelector(".planogram-product-search");
    if (!idInput || !codeInput) return;

    idInput.value = product.domain_product_id || "";
    codeInput.value = "";

    if (!link) {
      var selectedEl = root.querySelector(".planogram-product-selected");
      if (selectedEl) {
        selectedEl.textContent = "";
        link = document.createElement("a");
        link.className = "planogram-product-link";
        selectedEl.appendChild(link);
      }
    }
    if (link) {
      link.textContent = product.name || "";
      link.href = "/admin/domain-products/" + encodeURIComponent(product.domain_product_id);
      link.target = "_blank";
      link.rel = "noopener";
    }
    if (search) search.value = "";

    var unlinked = product.linked === false;
    if (unlinked) {
      root.setAttribute("data-unlinked", "true");
    } else {
      root.removeAttribute("data-unlinked");
    }
    var row = root.closest("tr");
    if (row) {
      row.classList.toggle("planogram-product-unlinked", unlinked);
    }
    var cell = root.closest(".planogram-cell");
    if (cell) {
      cell.classList.toggle("planogram-product-unlinked", unlinked);
    }

    setSelectedVisible(root, true);
    hideOptions(root);
    root.dispatchEvent(
      new CustomEvent("planogram-product-selection-changed", {
        bubbles: true,
        detail: { action: "apply" },
      }),
    );
  }

  function clearSelection(root) {
    var idInput = root.querySelector(".planogram-domain-product-id");
    var codeInput = root.querySelector(".planogram-legacy-product-code");
    var link = root.querySelector(".planogram-product-link");
    var search = root.querySelector(".planogram-product-search");
    if (idInput) idInput.value = "";
    if (codeInput) codeInput.value = "";
    if (link) {
      link.textContent = "";
      link.removeAttribute("href");
    }
    root.removeAttribute("data-unlinked");
    var row = root.closest("tr");
    if (row) row.classList.remove("planogram-product-unlinked");
    var cell = root.closest(".planogram-cell");
    if (cell) cell.classList.remove("planogram-product-unlinked");
    setSelectedVisible(root, false);
    hideOptions(root);
    if (search) {
      search.value = "";
      search.focus();
    }
    root.dispatchEvent(
      new CustomEvent("planogram-product-selection-changed", {
        bubbles: true,
        detail: { action: "clear" },
      }),
    );
  }

  function showOptions(root, query) {
    var list = root.querySelector(".planogram-product-options");
    if (!list) return;
    list.innerHTML = "";
    var matches = filterOptions(query);
    if (!matches.length) {
      var empty = document.createElement("li");
      empty.className = "planogram-product-options-empty";
      empty.textContent = "Ничего не найдено";
      list.appendChild(empty);
    } else {
      matches.forEach(function (product, index) {
        var item = document.createElement("li");
        var button = document.createElement("button");
        button.type = "button";
        button.className = "planogram-product-option";
        button.textContent = product.name + " (" + product.number + ")";
        if (index === 0) button.setAttribute("aria-selected", "true");
        button.addEventListener("mousedown", function (event) {
          event.preventDefault();
          applyProduct(root, product);
        });
        item.appendChild(button);
        list.appendChild(item);
      });
    }
    list.hidden = false;
  }

  document.addEventListener("input", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (!target.classList.contains("planogram-product-search")) return;
    var root = pickRoot(target);
    if (!root) return;
    showOptions(root, target.value);
  });

  document.addEventListener("focusin", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (!target.classList.contains("planogram-product-search")) return;
    var root = pickRoot(target);
    if (!root) return;
    showOptions(root, target.value);
  });

  function micromarketShelvesRoot() {
    return document.getElementById("micromarket-planogram-shelves");
  }

  function isMicromarketPersistedRow(row) {
    if (!row) return false;
    var shelves = micromarketShelvesRoot();
    if (!shelves || !shelves.contains(row)) return false;
    return row.getAttribute("data-persisted") === "1";
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;

    var restoreBtn = target.closest(".planogram-product-restore");
    if (restoreBtn) {
      event.preventDefault();
      var restoreRoot = pickRoot(restoreBtn);
      if (!restoreRoot) return;
      restoreRoot.dispatchEvent(
        new CustomEvent("planogram-product-restore", {
          bubbles: true,
          detail: { action: "restore" },
        }),
      );
      return;
    }

    var clearBtn = target.closest(".planogram-product-clear");
    if (clearBtn) {
      event.preventDefault();
      var clearRoot = pickRoot(clearBtn);
      if (!clearRoot) return;
      var row = clearRoot.closest("tr");
      // Micromarket persisted row: soft-remove (queue), not instant clear.
      // Snack / non-persisted keep clearSelection.
      if (isMicromarketPersistedRow(row)) {
        clearRoot.dispatchEvent(
          new CustomEvent("planogram-product-soft-remove", {
            bubbles: true,
            detail: { action: "soft-remove" },
          }),
        );
        return;
      }
      clearSelection(clearRoot);
      return;
    }

    if (target.closest(".planogram-product-picker")) return;
    document.querySelectorAll(".planogram-product-picker").forEach(hideOptions);
  });

  function optionButtons(root) {
    return Array.prototype.slice.call(
      root.querySelectorAll(".planogram-product-options button.planogram-product-option"),
    );
  }

  function selectedOptionIndex(buttons) {
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].getAttribute("aria-selected") === "true") return i;
    }
    return -1;
  }

  function setSelectedOption(buttons, index) {
    buttons.forEach(function (button, i) {
      if (i === index) button.setAttribute("aria-selected", "true");
      else button.removeAttribute("aria-selected");
    });
    if (index >= 0 && buttons[index] && buttons[index].scrollIntoView) {
      buttons[index].scrollIntoView({ block: "nearest" });
    }
  }

  document.addEventListener("keydown", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;
    if (!target.classList.contains("planogram-product-search")) return;
    var root = pickRoot(target);
    if (!root) return;

    var list = root.querySelector(".planogram-product-options");
    var listOpen = list && !list.hidden;

    if (event.key === "Escape") {
      if (!listOpen) return;
      event.preventDefault();
      hideOptions(root);
      return;
    }

    if (!listOpen) return;

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      var buttons = optionButtons(root);
      if (!buttons.length) return;
      var current = selectedOptionIndex(buttons);
      var next;
      if (event.key === "ArrowDown") {
        next = current < 0 ? 0 : Math.min(current + 1, buttons.length - 1);
      } else {
        next = current < 0 ? buttons.length - 1 : Math.max(current - 1, 0);
      }
      setSelectedOption(buttons, next);
      return;
    }

    if (event.key === "Enter") {
      event.preventDefault();
      var selected = root.querySelector(
        '.planogram-product-options button[aria-selected="true"]',
      );
      if (selected) selected.dispatchEvent(new Event("mousedown"));
    }
  });

  document.addEventListener("planogram-close-popups", function () {
    document.querySelectorAll(".planogram-product-picker").forEach(hideOptions);
  });

  function readLastBuyMap() {
    var node = document.getElementById("planogram-last-buy-prices");
    if (!node) return {};
    try {
      var parsed = JSON.parse(node.textContent || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  function updateRowLastBuy(row, domainProductId) {
    if (!row) return;
    var cell = row.querySelector(".planogram-buy-price");
    if (!cell) return;
    var map = readLastBuyMap();
    var key = domainProductId || "";
    var value = key && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : "—";
    cell.textContent = value || "—";
  }

  document.addEventListener("planogram-product-selection-changed", function (event) {
    var root = event.target;
    if (!(root instanceof Element) || !root.classList.contains("planogram-product-picker")) {
      return;
    }
    var row = root.closest("tr");
    var detail = event.detail || {};
    if (detail.action === "clear") {
      updateRowLastBuy(row, "");
      return;
    }
    var idInput = root.querySelector(".planogram-domain-product-id");
    updateRowLastBuy(row, idInput ? idInput.value : "");
  });
})();
