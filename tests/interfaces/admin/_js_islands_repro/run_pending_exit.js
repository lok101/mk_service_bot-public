/* Node+jsdom: markPendingExit / clearPendingExit toggle class + hidden input. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const root = path.resolve("src/interfaces/admin/static");
fs.readFileSync(path.join(root, "micromarket_planogram_table.js"), "utf8");

const html = `
<!doctype html>
<html><body>
<div id="micromarket-planogram-shelves">
  <section class="planogram-shelf" data-kit-group-id="10">
    <input name="shelf_kit_group_id-0" value="10" />
    <table class="planogram-shelf-table"><tbody>
      <tr data-persisted="1">
        <td>
          <div class="planogram-product-picker">
            <input class="planogram-domain-product-id" name="domain_product_id-0" value="a" />
            <a class="planogram-product-link">Alpha</a>
            <button type="button" class="planogram-product-clear" aria-label="Убрать товар">✕</button>
          </div>
          <input name="pending_exit-0" value="" />
          <input name="kit_group_id-0" value="10" />
        </td>
      </tr>
    </tbody></table>
  </section>
</div>
</body></html>
`;

const dom = new JSDOM(html, { runScripts: "outside-only" });
global.window = dom.window;
global.document = dom.window.document;
global.Element = dom.window.Element;
global.HTMLElement = dom.window.HTMLElement;
global.window.MicromarketPlanogramSortKey = {
  comparePlanogramLines: function () {
    return 0;
  },
};

const api = require(path.join(root, "micromarket_planogram_table.js"));
const row = document.querySelector("tr[data-persisted]");
api.markPendingExit(row);
const afterMark = {
  class: row.classList.contains("planogram-pending-exit"),
  value: row.querySelector('input[name^="pending_exit-"]').value,
};
api.clearPendingExit(row);
const afterClear = {
  class: row.classList.contains("planogram-pending-exit"),
  value: row.querySelector('input[name^="pending_exit-"]').value,
};

process.stdout.write(JSON.stringify({ afterMark, afterClear }));
