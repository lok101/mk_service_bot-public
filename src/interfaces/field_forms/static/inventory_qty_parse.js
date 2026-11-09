/**
 * Port of parse_inventory_form_qty (Python): strip letters, comma→dot, Decimal-like.
 * Dual-export: browser global + Node module.exports for golden tests.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.parseInventoryFormQty = api.parseInventoryFormQty;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function parseInventoryFormQty(raw) {
    const stripped = String(raw == null ? "" : raw).trim();
    let cleaned = "";
    for (const ch of stripped) {
      if (!/\p{L}/u.test(ch)) {
        cleaned += ch;
      }
    }
    cleaned = cleaned.replace(/,/g, ".").replace(/ /g, "");
    if (!cleaned) {
      throw new Error("quantity text has no digits");
    }
    if (!/^-?\d+(\.\d+)?$/.test(cleaned)) {
      throw new Error("quantity text is not a number");
    }
    return cleaned;
  }

  return { parseInventoryFormQty };
});
