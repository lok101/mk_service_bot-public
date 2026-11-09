(() => {
  const form =
    document.getElementById("field-form-inventory") ||
    document.getElementById("field-form-coffee");
  if (!form) return;

  const submit = form.querySelector("[data-submit]");
  const parseQty =
    typeof globalThis.parseInventoryFormQty === "function"
      ? globalThis.parseInventoryFormQty
      : null;

  function lineRoot(node) {
    return node.closest("[data-line-code]");
  }

  function fieldErrorEl(line) {
    return line.querySelector("[data-field-error]");
  }

  function clearFieldError(line) {
    const input = line.querySelector("[data-qty-input]");
    const err = fieldErrorEl(line);
    if (input) {
      input.classList.remove("field-form__qty--invalid");
      input.removeAttribute("aria-invalid");
    }
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
  }

  function showFieldError(line, message) {
    const input = line.querySelector("[data-qty-input]");
    const err = fieldErrorEl(line);
    if (input) {
      input.classList.add("field-form__qty--invalid");
      input.setAttribute("aria-invalid", "true");
    }
    if (err) {
      err.hidden = false;
      err.textContent = message;
    }
  }

  function validateQtyInput(input) {
    const line = lineRoot(input);
    if (!line) return true;
    const raw = String(input.value || "").trim();
    const required = input.getAttribute("data-required") === "1";
    const minAttr = input.getAttribute("data-min");
    const maxAttr = input.getAttribute("data-max");
    const integer = input.getAttribute("data-integer") === "1";

    if (minAttr == null && maxAttr == null && !required && !integer) {
      clearFieldError(line);
      return true;
    }

    if (raw === "") {
      if (required) {
        showFieldError(line, "Нужен ответ");
        return false;
      }
      clearFieldError(line);
      return true;
    }

    if (!parseQty) {
      clearFieldError(line);
      return true;
    }

    let qtyText;
    try {
      qtyText = parseQty(raw);
    } catch (_error) {
      showFieldError(line, "Некорректное количество");
      return false;
    }

    const qty = Number(qtyText);
    if (!Number.isFinite(qty)) {
      showFieldError(line, "Некорректное количество");
      return false;
    }
    if (qty < 0) {
      showFieldError(line, "Количество не может быть отрицательным");
      return false;
    }
    if (integer && !Number.isInteger(qty)) {
      showFieldError(line, "Количество должно быть целым");
      return false;
    }
    if (minAttr != null && qty < Number(minAttr)) {
      showFieldError(line, `Количество не должно быть меньше ${minAttr}`);
      return false;
    }
    if (maxAttr != null && qty > Number(maxAttr)) {
      showFieldError(line, `Количество не должно превышать ${maxAttr}`);
      return false;
    }
    clearFieldError(line);
    return true;
  }

  function setEmpty(line, empty) {
    const input = line.querySelector("[data-qty-input]");
    const toggle = line.querySelector("[data-empty-toggle]");
    if (!input || !toggle) return;
    if (empty) {
      input.value = "0";
      input.hidden = true;
      input.setAttribute("aria-hidden", "true");
      toggle.setAttribute("aria-pressed", "true");
      toggle.textContent = "Сброс";
      line.dataset.answer = "empty";
    } else {
      input.value = "";
      input.hidden = false;
      input.removeAttribute("aria-hidden");
      toggle.setAttribute("aria-pressed", "false");
      toggle.textContent = "Пусто";
      line.dataset.answer = "unanswered";
    }
    clearFieldError(line);
    refreshSubmit();
  }

  function refreshSubmit() {
    if (!submit) return;
    const lines = form.querySelectorAll("[data-line-code]");
    let incomplete = false;
    for (const line of lines) {
      const input = line.querySelector("[data-qty-input]");
      if (!input) continue;
      if (input.value.trim() === "") {
        incomplete = true;
        break;
      }
    }
    submit.disabled = incomplete;
  }

  form.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-empty-toggle]");
    if (!toggle || !form.contains(toggle)) return;
    event.preventDefault();
    const line = lineRoot(toggle);
    if (!line) return;
    const pressed = toggle.getAttribute("aria-pressed") === "true";
    setEmpty(line, !pressed);
  });

  form.addEventListener("input", (event) => {
    const input = event.target.closest("[data-qty-input]");
    if (!input || !form.contains(input)) return;
    const line = lineRoot(input);
    if (!line) return;
    const toggle = line.querySelector("[data-empty-toggle]");
    if (toggle) {
      toggle.setAttribute("aria-pressed", "false");
      toggle.textContent = "Пусто";
    }
    input.hidden = false;
    line.dataset.answer = input.value.trim() === "" ? "unanswered" : "qty";
    if (input.classList.contains("field-form__qty--invalid")) {
      validateQtyInput(input);
    }
    refreshSubmit();
  });

  form.addEventListener(
    "blur",
    (event) => {
      const input = event.target.closest("[data-qty-input]");
      if (!input || !form.contains(input)) return;
      validateQtyInput(input);
    },
    true,
  );

  for (const line of form.querySelectorAll("[data-line-code]")) {
    const input = line.querySelector("[data-qty-input]");
    if (input && input.value.trim() === "0") {
      const toggle = line.querySelector("[data-empty-toggle]");
      if (toggle) {
        setEmpty(line, true);
      } else {
        line.dataset.answer = "qty";
      }
    } else {
      line.dataset.answer = input && input.value.trim() !== "" ? "qty" : "unanswered";
    }
  }
  refreshSubmit();
})();
