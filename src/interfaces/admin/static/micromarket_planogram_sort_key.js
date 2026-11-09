/* Pure planogram line sort key — parity with planogram_line_sort_key (Python).
 * Key: lower + yo→e; tie domain_product_id then product_code.
 * comparePlanogramLines: pending_exit false before true, then alpha key.
 */
(function (root) {
  var YO = "\u0451";
  var YO_UPPER = "\u0401";
  var YE = "\u0435";

  function field(line, camel, snake) {
    if (!line || typeof line !== "object") return "";
    var value = line[camel];
    if (value === undefined || value === null) value = line[snake];
    return String(value == null ? "" : value);
  }

  function pendingExitOf(line) {
    if (!line || typeof line !== "object") return false;
    var value = line.pendingExit;
    if (value === undefined || value === null) value = line.pending_exit;
    return Boolean(value);
  }

  function sortKey(line) {
    var name = field(line, "name", "name");
    var domainProductId = field(line, "domainProductId", "domain_product_id").trim();
    var productCode = field(line, "productCode", "product_code").trim();
    var normalized = name
      .toLowerCase()
      .split(YO)
      .join(YE)
      .split(YO_UPPER)
      .join(YE);
    return [normalized, domainProductId, productCode];
  }

  function comparePlanogramLines(a, b) {
    var pa = pendingExitOf(a) ? 1 : 0;
    var pb = pendingExitOf(b) ? 1 : 0;
    if (pa !== pb) return pa - pb;
    var ka = sortKey(a);
    var kb = sortKey(b);
    for (var i = 0; i < 3; i++) {
      if (ka[i] < kb[i]) return -1;
      if (ka[i] > kb[i]) return 1;
    }
    return 0;
  }

  var api = {
    sortKey: sortKey,
    comparePlanogramLines: comparePlanogramLines,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.MicromarketPlanogramSortKey = api;
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
