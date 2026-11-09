"use strict";

(function (root) {
  function parseBound(el, name, fallback) {
    var raw = el.getAttribute(name);
    if (raw == null || raw === "") return fallback;
    var n = Number(raw);
    return Number.isFinite(n) ? n : fallback;
  }

  function clamp(value, min, max) {
    if (!Number.isFinite(value)) return min;
    return Math.min(max, Math.max(min, value));
  }

  function nudge(value, dir, min, max) {
    var current = Number.isFinite(Number(value)) ? Number(value) : min;
    return clamp(current + (Number(dir) || 0), min, max);
  }

  function disabledState(value, min, max) {
    var n = Number.isFinite(Number(value)) ? Number(value) : min;
    return { minus: n <= min, plus: n >= max };
  }

  function normalizeInput(raw, min, max, integerMode) {
    var text = raw == null ? "" : String(raw).trim();
    if (text === "") return min;
    var n = Number(text.replace(",", "."));
    if (!Number.isFinite(n)) return min;
    if (integerMode) n = Math.round(n);
    return clamp(n, min, max);
  }

  function syncButtons(stepper, value) {
    var min = parseBound(stepper, "data-min", 0);
    var max = parseBound(stepper, "data-max", 50);
    var state = disabledState(value, min, max);
    var minus = stepper.querySelector('.admin-qty-btn[data-dir="-1"]');
    var plus = stepper.querySelector('.admin-qty-btn[data-dir="1"]');
    if (minus) minus.disabled = state.minus;
    if (plus) plus.disabled = state.plus;
  }

  function isIntegerMode(stepper, input) {
    if (stepper.getAttribute("data-integer") === "1") return true;
    if (input.getAttribute("data-integer") === "1") return true;
    var step = input.getAttribute("step");
    return step === "1";
  }

  function readValue(input, stepper) {
    var min = parseBound(stepper, "data-min", 0);
    var max = parseBound(stepper, "data-max", 50);
    var value = normalizeInput(input.value, min, max, isIntegerMode(stepper, input));
    input.value = String(value);
    syncButtons(stepper, value);
    return value;
  }

  function syncStepper(stepper) {
    var input = stepper.querySelector(".admin-qty-input");
    if (!input) return;
    readValue(input, stepper);
  }

  function initAll(rootEl) {
    var scope = rootEl || (typeof document !== "undefined" ? document : null);
    if (!scope || !scope.querySelectorAll) return;
    Array.prototype.forEach.call(scope.querySelectorAll(".admin-qty-stepper"), syncStepper);
  }

  function onClick(event) {
    var btn = event.target && event.target.closest
      ? event.target.closest(".admin-qty-btn")
      : null;
    if (!btn || btn.disabled) return;
    var stepper = btn.closest(".admin-qty-stepper");
    if (!stepper) return;
    var input = stepper.querySelector(".admin-qty-input");
    if (!input) return;
    var min = parseBound(stepper, "data-min", 0);
    var max = parseBound(stepper, "data-max", 50);
    var dir = Number(btn.getAttribute("data-dir")) || 0;
    var next = nudge(input.value || 0, dir, min, max);
    input.value = String(next);
    readValue(input, stepper);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function onCommit(event) {
    var input = event.target;
    if (!input || !input.classList || !input.classList.contains("admin-qty-input")) return;
    var stepper = input.closest(".admin-qty-stepper");
    if (!stepper) return;
    readValue(input, stepper);
  }

  function install(doc) {
    var documentRef = doc || (typeof document !== "undefined" ? document : null);
    if (!documentRef || documentRef.documentElement.dataset.adminQtyStepper === "1") return;
    documentRef.documentElement.dataset.adminQtyStepper = "1";
    documentRef.addEventListener("click", onClick);
    documentRef.addEventListener("change", onCommit);
    documentRef.addEventListener("blur", onCommit, true);
    if (documentRef.readyState === "loading") {
      documentRef.addEventListener("DOMContentLoaded", function () {
        initAll(documentRef);
      });
    } else {
      initAll(documentRef);
    }
  }

  var api = {
    clamp: clamp,
    nudge: nudge,
    disabledState: disabledState,
    normalizeInput: normalizeInput,
    initAll: initAll,
    install: install,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.AdminQuantityStepper = api;
  }
  if (typeof document !== "undefined") {
    install(document);
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
