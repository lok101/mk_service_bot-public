(function () {
  // Окно кандидатов: колонки Имя | Код | Статус
  function qs(id) {
    return document.getElementById(id);
  }

  function statusText(card) {
    var parts = [];
    if (card.archived) parts.push("архив");
    if (card.taken) parts.push("занята");
    return parts.join(", ");
  }

  function ensureLines(summaryEl) {
    var nameEl = document.getElementById("catalog-card-name");
    var codeLine = document.getElementById("catalog-card-code");
    if (nameEl && codeLine) return { nameEl: nameEl, codeLine: codeLine };
    summaryEl.textContent = "";
    nameEl = document.createElement("p");
    nameEl.id = "catalog-card-name";
    codeLine = document.createElement("p");
    codeLine.id = "catalog-card-code";
    summaryEl.appendChild(nameEl);
    summaryEl.appendChild(codeLine);
    return { nameEl: nameEl, codeLine: codeLine };
  }

  function applySelection(card, codeEl, summaryEl) {
    var lines = ensureLines(summaryEl);
    codeEl.value = card.code;
    lines.nameEl.textContent = card.archived ? card.name + " архив" : card.name;
    lines.codeLine.textContent = card.code;
  }

  function render(payload, query, windowEl, hintEl, exactEl, codeEl, summaryEl) {
    var body = windowEl.querySelector("tbody");
    body.innerHTML = "";
    var cards = payload.cards || [];
    if (!query.trim()) {
      windowEl.hidden = true;
      hintEl.textContent = "";
      exactEl.textContent = "";
      return;
    }
    cards.forEach(function (card) {
      var row = document.createElement("tr");
      var nameCell = document.createElement("td");
      var codeCell = document.createElement("td");
      var statusCell = document.createElement("td");
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = card.name;
      button.addEventListener("click", function () {
        applySelection(card, codeEl, summaryEl);
      });
      nameCell.appendChild(button);
      codeCell.textContent = card.code;
      statusCell.textContent = statusText(card);
      row.appendChild(nameCell);
      row.appendChild(codeCell);
      row.appendChild(statusCell);
      body.appendChild(row);
    });
    windowEl.hidden = cards.length === 0;
    if (cards.length === 0) hintEl.textContent = "В каталоге нет такой карточки";
    else if (payload.truncated) hintEl.textContent = "Уточните запрос";
    else hintEl.textContent = "";
    var needle = query.trim().toLowerCase();
    var first = cards[0];
    if (first && first.code.trim().toLowerCase() === needle) {
      exactEl.textContent = first.code + " — " + first.name;
    } else {
      exactEl.textContent = "";
    }
  }

  function bindHideButton() {
    var hideBtn = qs("domain-product-hide");
    if (!hideBtn) return;
    hideBtn.addEventListener("click", function () {
      var form = hideBtn.closest("form");
      if (!form) return;
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "action";
      input.value = "hide";
      form.appendChild(input);
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    });
  }

  function init() {
    bindHideButton();
    var queryEl = qs("catalog-card-query");
    var windowEl = qs("catalog-card-window");
    var hintEl = qs("catalog-card-hint");
    var exactEl = qs("catalog-card-exact");
    var summaryEl = qs("catalog-card-summary");
    var codeEl = document.querySelector('input[name="catalog_code"]');
    if (!queryEl || !windowEl || !hintEl || !exactEl || !summaryEl || !codeEl) return;

    queryEl.addEventListener("input", function () {
      var query = queryEl.value || "";
      fetch("/admin/domain-products/catalog-cards?q=" + encodeURIComponent(query), {
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json();
        })
        .then(function (payload) {
          if ((queryEl.value || "") !== query) return;
          render(payload, query, windowEl, hintEl, exactEl, codeEl, summaryEl);
        });
    });

    queryEl.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      var first = windowEl.querySelector("button");
      if (!first) return;
      event.preventDefault();
      first.click();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
