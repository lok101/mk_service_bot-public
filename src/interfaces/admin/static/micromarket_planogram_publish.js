/* Micromarket planogram Publish button: JSON POST without full page reload. */
(function (root) {
  function install(doc) {
    var documentRef = doc || (typeof document !== "undefined" ? document : null);
    if (!documentRef) return;
    var form = documentRef.getElementById("micromarket-planogram-publish-form");
    if (!form || !form.hasAttribute("data-publish-fetch")) return;
    var button = documentRef.getElementById("micromarket-planogram-publish-button");
    var errorEl = documentRef.getElementById("micromarket-planogram-publish-error");
    function showError(message) {
      if (!errorEl) return;
      errorEl.textContent = message || "Не удалось опубликовать";
      errorEl.removeAttribute("hidden");
    }
    function clearError() {
      if (!errorEl) return;
      errorEl.textContent = "";
      errorEl.setAttribute("hidden", "");
    }
    function markPublishing() {
      if (button) {
        button.disabled = true;
        button.textContent = "Задача выполняется";
      }
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!button || button.disabled) return;
      clearError();
      fetch(form.getAttribute("action") || form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then(function (response) {
          return response
            .json()
            .then(function (payload) {
              return { okHttp: response.ok, status: response.status, payload: payload };
            })
            .catch(function () {
              throw new Error("non_json");
            });
        })
        .then(function (result) {
          var payload = result.payload || {};
          if (payload.ok === true) {
            markPublishing();
            if (payload.notice) {
              var notice = documentRef.createElement("p");
              notice.className = "admin-hint";
              notice.textContent = payload.notice;
              form.insertAdjacentElement("afterend", notice);
            }
            return;
          }
          showError(payload.error || "Не удалось опубликовать");
        })
        .catch(function () {
          showError("Не удалось опубликовать");
        });
    });
  }

  var api = { install: install };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.MicromarketPlanogramPublish = api;
  }
  if (typeof document !== "undefined") {
    install(document);
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
