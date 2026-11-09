(function () {
  var rowsRoot = document.getElementById("defect-rows");
  var addButton = document.getElementById("add-defect");
  if (!rowsRoot || !addButton) {
    return;
  }

  function nextIndex() {
    return rowsRoot.querySelectorAll(".demo-defect-row").length;
  }

  function clearEmptyHint() {
    var hint = rowsRoot.querySelector(".admin-muted");
    if (hint) {
      hint.remove();
    }
  }

  function bindRemove(button) {
    button.addEventListener("click", function () {
      var row = button.closest(".demo-defect-row");
      if (row) {
        row.remove();
      }
      if (!rowsRoot.querySelector(".demo-defect-row")) {
        var p = document.createElement("p");
        p.className = "admin-muted";
        p.textContent =
          "Проблем пока нет — на разборе блок «Ошибки техника» будет пустым.";
        rowsRoot.appendChild(p);
      }
    });
  }

  rowsRoot.querySelectorAll("[data-remove-defect]").forEach(bindRemove);

  addButton.addEventListener("click", function () {
    clearEmptyHint();
    var index = nextIndex();
    var row = document.createElement("div");
    row.className = "demo-defect-row";
    row.innerHTML =
      '<label>Подпись<input type="text" name="defect_label_' +
      index +
      '" value="" autocomplete="off"></label>' +
      '<button type="button" class="admin-btn" data-remove-defect>Удалить</button>';
    rowsRoot.appendChild(row);
    bindRemove(row.querySelector("[data-remove-defect]"));
  });
})();
