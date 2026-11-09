(function () {
  "use strict";

  var COLLAPSED_KEY = "admin_sidebar_collapsed";
  var FOLDERS_KEY = "admin_sidebar_open_folders";
  var sidebar = document.getElementById("admin-app-sidebar");
  if (!sidebar) {
    return;
  }

  function readOpenFolders() {
    try {
      var raw = localStorage.getItem(FOLDERS_KEY);
      if (!raw) {
        return [];
      }
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch (_err) {
      return [];
    }
  }

  function writeOpenFolders(ids) {
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(ids));
  }

  var collapsed = localStorage.getItem(COLLAPSED_KEY) === "true";
  sidebar.setAttribute("data-collapsed", collapsed ? "true" : "false");

  var toggle = sidebar.querySelector(".admin-sidebar-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = sidebar.getAttribute("data-collapsed") !== "true";
      sidebar.setAttribute("data-collapsed", next ? "true" : "false");
      localStorage.setItem(COLLAPSED_KEY, next ? "true" : "false");
    });
  }

  var openIds = new Set(readOpenFolders());
  var folders = sidebar.querySelectorAll(".admin-sidebar-folder");
  folders.forEach(function (folder) {
    var folderId = folder.getAttribute("data-folder-id");
    if (!folderId) {
      return;
    }
    if (openIds.has(folderId)) {
      folder.open = true;
    }
    folder.addEventListener("toggle", function () {
      if (folder.open) {
        openIds.add(folderId);
      } else {
        openIds.delete(folderId);
      }
      writeOpenFolders(Array.from(openIds));
    });
  });
})();
