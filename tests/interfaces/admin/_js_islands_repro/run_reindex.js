/* Node+jsdom: reindexRowNames renumbers indexed field names continuously. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const root = path.resolve("src/interfaces/admin/static");
const tableJs = fs.readFileSync(path.join(root, "micromarket_planogram_table.js"), "utf8");

const html = `
<!doctype html>
<html><body>
<div id="micromarket-planogram-shelves">
  <section class="planogram-shelf" data-kit-group-id="10">
    <input name="shelf_kit_group_id-5" value="10" />
    <table class="planogram-shelf-table"><tbody>
      <tr data-persisted="1">
        <td><input class="planogram-domain-product-id" name="domain_product_id-7" value="a" />
            <input name="pending_exit-7" value="" />
            <input name="target_qty-7" value="1" /></td>
      </tr>
      <tr data-persisted="1">
        <td><input class="planogram-domain-product-id" name="domain_product_id-2" value="b" />
            <input name="pending_exit-2" value="" />
            <input name="target_qty-2" value="2" /></td>
      </tr>
    </tbody></table>
  </section>
  <section class="planogram-shelf" data-kit-group-id="20">
    <input name="shelf_kit_group_id-9" value="20" />
    <table class="planogram-shelf-table"><tbody>
      <tr data-persisted="1">
        <td><input class="planogram-domain-product-id" name="domain_product_id-3" value="c" />
            <input name="pending_exit-3" value="" />
            <input name="target_qty-3" value="3" /></td>
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

const api = require(path.join(root, "micromarket_planogram_table.js"));
api.reindexRowNames();
api.reindexShelfNames();

const rowNames = Array.from(document.querySelectorAll("tbody tr")).map((row) =>
  Array.from(row.querySelectorAll("[name]")).map((el) => el.getAttribute("name")),
);
const shelfNames = Array.from(
  document.querySelectorAll('input[name^="shelf_kit_group_id-"]'),
).map((el) => el.getAttribute("name"));

process.stdout.write(JSON.stringify({ rowNames, shelfNames }));
