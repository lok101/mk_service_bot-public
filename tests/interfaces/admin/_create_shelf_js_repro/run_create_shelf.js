/* Node+jsdom smoke: move to a category without a section creates it. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "../../../../src/interfaces/admin/static");
const sortJs = fs.readFileSync(path.join(root, "micromarket_planogram_sort_key.js"), "utf8");
const tableJs = fs.readFileSync(path.join(root, "micromarket_planogram_table.js"), "utf8");

const html = `<!DOCTYPE html><html><body>
<form id="micromarket-planogram-form">
<template id="planogram-shelf-template">
  <section class="planogram-shelf" data-kit-group-id="">
    <input type="hidden" name="shelf_kit_group_id-0" value="">
    <header class="planogram-shelf-header">
      <button type="button" class="planogram-drag-handle">H</button>
      <span class="planogram-shelf-label"></span>
      <button type="button" class="planogram-shelf-collapse">v</button>
      <button type="button" class="planogram-shelf-clear">C</button>
    </header>
    <div class="planogram-shelf-body">
      <table class="planogram-shelf-table"><tbody></tbody></table>
    </div>
  </section>
</template>
<div id="micromarket-planogram-shelves">
  <section class="planogram-shelf" data-kit-group-id="10">
    <input type="hidden" name="shelf_kit_group_id-0" value="10">
    <header class="planogram-shelf-header">
      <button type="button" class="planogram-drag-handle">H</button>
      <span class="planogram-shelf-label">Salads</span>
      <button type="button" class="planogram-shelf-collapse">v</button>
      <button type="button" class="planogram-shelf-clear">C</button>
    </header>
    <div class="planogram-shelf-body">
      <table class="planogram-shelf-table"><tbody>
        <tr data-persisted="1">
          <td>
            <input class="planogram-domain-product-id" name="domain_product_id-0" value="p1">
            <a class="planogram-product-link">Product</a>
            <input class="planogram-kit-group-id" type="hidden" name="kit_group_id-0" value="10">
            <select class="planogram-move-shelf">
              <option value="">Move</option>
              <option value="10" hidden>Salads</option>
              <option value="20">Drinks</option>
            </select>
          </td>
        </tr>
      </tbody></table>
    </div>
  </section>
</div>
</form>
<script>${sortJs}</script>
<script>${tableJs}</script>
</body></html>`;

const dom = new JSDOM(html, { runScripts: "dangerously" });
const { document } = dom.window;
const row = document.querySelector("tr[data-persisted]");
const select = row.querySelector("select.planogram-move-shelf");
select.value = "20";
select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
const shelves = Array.prototype.map.call(
  document.querySelectorAll("#micromarket-planogram-shelves > .planogram-shelf"),
  (s) => s.getAttribute("data-kit-group-id"),
);
process.stdout.write(
  JSON.stringify({
    shelves,
    rowShelf: row.closest(".planogram-shelf").getAttribute("data-kit-group-id"),
    kitGroup: row.querySelector(".planogram-kit-group-id").value,
  }),
);
