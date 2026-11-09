(function () {
  const form = document.getElementById("field-form-coffee");
  if (!form || form.getAttribute("data-require-all-lines") !== "1") {
    return;
  }
  const submit = form.querySelector("[data-submit]");
  const inputs = Array.from(form.querySelectorAll("[data-qty-input]"));

  function allAnswered() {
    return inputs.every(function (input) {
      return String(input.value || "").trim() !== "";
    });
  }

  function sync() {
    if (submit) {
      submit.disabled = !allAnswered();
    }
  }

  inputs.forEach(function (input) {
    input.addEventListener("input", sync);
    input.addEventListener("change", sync);
  });
  sync();
})();
