"use strict";

function cellSnapshotHasData(cell) {
  if (!cell) return false;
  var product = String(cell.product || "").trim();
  var line = String(cell.line || "").trim();
  return Boolean(product || line || cell.merge);
}

function mergeCrossesCut(cell, newShelves, newSlots) {
  if (!cell || !cell.merge) return false;
  var shelf = Number(cell.shelf);
  var slot = Number(cell.slot);
  if (Number.isNaN(shelf) || Number.isNaN(slot)) return false;
  if (shelf >= newShelves) return false;
  if (slot >= newSlots) return false;
  // Horizontal span 2 crosses the right cut line.
  return slot + 2 > newSlots;
}

function sliceHasData(cells, oldShelves, oldSlots, newShelves, newSlots) {
  if (newShelves >= oldShelves && newSlots >= oldSlots) return false;
  var list = cells || [];
  for (var i = 0; i < list.length; i += 1) {
    var cell = list[i];
    var shelf = Number(cell.shelf);
    var slot = Number(cell.slot);
    if (Number.isNaN(shelf) || Number.isNaN(slot)) continue;
    var inCutRegion = shelf >= newShelves || slot >= newSlots;
    if (inCutRegion && cellSnapshotHasData(cell)) return true;
    if (mergeCrossesCut(cell, newShelves, newSlots)) return true;
  }
  return false;
}

function applyResize(cells, oldShelves, oldSlots, newShelves, newSlots, confirmed) {
  var list = cells || [];
  var shrinking = newShelves < oldShelves || newSlots < oldSlots;
  if (shrinking && sliceHasData(list, oldShelves, oldSlots, newShelves, newSlots) && !confirmed) {
    return {
      cells: list,
      shelves: oldShelves,
      slots: oldSlots,
      needsConfirm: true,
    };
  }

  var next = [];
  for (var i = 0; i < list.length; i += 1) {
    var cell = list[i];
    var shelf = Number(cell.shelf);
    var slot = Number(cell.slot);
    if (Number.isNaN(shelf) || Number.isNaN(slot)) continue;
    if (shelf >= newShelves || slot >= newSlots) continue;
    var copy = {
      shelf: shelf,
      slot: slot,
      product: cell.product,
      line: cell.line,
      merge: Boolean(cell.merge),
    };
    if (copy.merge && slot + 2 > newSlots) {
      copy.merge = false;
    }
    next.push(copy);
  }

  return {
    cells: next,
    shelves: newShelves,
    slots: newSlots,
    needsConfirm: false,
  };
}

var api = {
  cellSnapshotHasData: cellSnapshotHasData,
  sliceHasData: sliceHasData,
  applyResize: applyResize,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof window !== "undefined") {
  window.PlanogramResize = api;
}
