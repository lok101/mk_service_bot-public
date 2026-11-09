(() => {
  const form = document.getElementById("field-form-coffee");
  if (!form || form.dataset.inputUi !== "radio") return;

  const submit = form.querySelector("[data-submit]");

  function refreshSubmit() {
    if (!submit) return;
    const lines = form.querySelectorAll("[data-line-code]");
    let incomplete = false;
    for (const line of lines) {
      const checked = line.querySelector("[data-radio-input]:checked");
      if (!checked) {
        incomplete = true;
        break;
      }
    }
    submit.disabled = incomplete;
  }

  form.addEventListener("change", (event) => {
    const radio = event.target.closest("[data-radio-input]");
    if (!radio || !form.contains(radio)) return;
    refreshSubmit();
  });

  refreshSubmit();
})();
