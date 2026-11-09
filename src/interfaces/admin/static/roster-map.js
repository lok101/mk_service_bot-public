(function () {
  "use strict";

  var PALETTE = [
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#a65628",
    "#f781bf",
    "#66c2a5",
    "#e6ab02",
    "#666666",
    "#1b9e77",
    "#d95f02",
  ];
  var map = null;
  var markers = {};

  function colorForTechnician(id) {
    if (!id) return "#888888";
    var h = 0;
    for (var i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  function parseCoord(raw) {
    var n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function technicianLabel(id) {
    if (!id) return "Без техника";
    var filter = document.getElementById("roster-technician-filter");
    if (filter) {
      for (var i = 0; i < filter.options.length; i++) {
        if (filter.options[i].value === id) {
          return (filter.options[i].textContent || "").trim() || id;
        }
      }
    }
    var selects = document.querySelectorAll('#roster-table tbody select[name^="technician-"]');
    for (var s = 0; s < selects.length; s++) {
      var opts = selects[s].options;
      for (var j = 0; j < opts.length; j++) {
        if (opts[j].value === id) {
          return (opts[j].textContent || "").trim() || id;
        }
      }
    }
    return id;
  }

  function rebuildLegend(visibleByTech) {
    var legend = document.getElementById("roster-map-legend");
    if (!legend) return;
    legend.innerHTML = "";
    Object.keys(visibleByTech)
      .sort()
      .forEach(function (techId) {
        var item = document.createElement("span");
        item.className = "admin-map-legend-item";
        var swatch = document.createElement("span");
        swatch.className = "admin-map-swatch";
        swatch.style.backgroundColor = colorForTechnician(techId);
        item.appendChild(swatch);
        item.appendChild(document.createTextNode(technicianLabel(techId)));
        legend.appendChild(item);
      });
  }

  function sync() {
    if (!map) return;
    var bounds = [];
    var visibleByTech = {};
    var visibleCount = 0;

    Object.keys(markers).forEach(function (code) {
      var entry = markers[code];
      var row = entry.row;
      var marker = entry.marker;
      var visible = !row.hasAttribute("hidden");
      if (visible) {
        marker.addTo(map);
        var tech = row.getAttribute("data-technician-id") || "";
        var color = colorForTechnician(tech);
        marker.setStyle({ color: color, fillColor: color });
        visibleByTech[tech] = true;
        bounds.push(marker.getLatLng());
        visibleCount += 1;
      } else {
        map.removeLayer(marker);
      }
    });

    var countEl = document.getElementById("roster-map-count");
    if (countEl) countEl.textContent = String(visibleCount);
    rebuildLegend(visibleByTech);

    if (bounds.length >= 1) {
      map.fitBounds(L.latLngBounds(bounds), { padding: [24, 24], maxZoom: 14 });
    }
  }

  function bindExpandToggle() {
    var btn = document.getElementById("roster-map-expand");
    var el = document.getElementById("roster-map");
    if (!btn || !el) return;
    btn.addEventListener("click", function () {
      var expanded = el.classList.toggle("is-expanded");
      document.body.classList.toggle("roster-map-expanded", expanded);
      btn.setAttribute("aria-pressed", expanded ? "true" : "false");
      btn.textContent = expanded ? "Свернуть карту" : "Развернуть карту";
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          if (!map) return;
          map.invalidateSize({ animate: false });
          sync();
        });
      });
    });
  }

  function initMap() {
    var el = document.getElementById("roster-map");
    if (!el || typeof L === "undefined") return;
    map = L.map(el);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    document.querySelectorAll("#roster-table tbody tr[data-lat][data-lng]").forEach(function (row) {
      var lat = parseCoord(row.getAttribute("data-lat"));
      var lng = parseCoord(row.getAttribute("data-lng"));
      if (lat === null || lng === null) return;
      var tech = row.getAttribute("data-technician-id") || "";
      var color = colorForTechnician(tech);
      var marker = L.circleMarker([lat, lng], {
        radius: 8,
        color: color,
        fillColor: color,
        fillOpacity: 0.85,
        weight: 1,
      }).addTo(map);
      var name = row.getAttribute("data-location-name") || "";
      var code = row.getAttribute("data-machine-id") || "";
      var tip = document.createElement("span");
      tip.textContent = name || code;
      marker.bindTooltip(tip);
      markers[code] = { marker: marker, row: row };
    });
    window.addEventListener("roster:rows-updated", sync);
    sync();
    if (Object.keys(markers).length === 0) {
      map.setView([55.75, 37.62], 10);
    }
  }

  function init() {
    bindExpandToggle();
    initMap();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
