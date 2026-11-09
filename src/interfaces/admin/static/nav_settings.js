(() => {
  const form = document.getElementById("nav-settings-form");
  const editor = document.getElementById("nav-settings-editor");
  const rootList = document.getElementById("nav-settings-root");
  const hidden = document.getElementById("structure_json");
  const addFolderBtn = document.getElementById("nav-settings-add-folder");
  if (!form || !editor || !rootList || !hidden) {
    return;
  }

  const PANEL_LABELS = {
    roster: "Roster",
    master_data: "Парк",
    visit_board: "Визиты",
    settlement_analysis: "Сверка",
    matrix_pricing: "Правила цены",
    matrix_sku_catalog: "SKU матрицы",
    technicians: "Техники",
    users: "Доступ",
    nav_settings: "Настройки меню",
  };

  /** @type {Array<object>} */
  let nodes = [];
  try {
    nodes = JSON.parse(editor.dataset.navStructure || "[]");
  } catch {
    nodes = [];
  }
  if (!Array.isArray(nodes)) {
    nodes = [];
  }

  let dragPayload = null;

  function panelLabel(panel) {
    return PANEL_LABELS[panel] || panel;
  }

  function serialize() {
    hidden.value = JSON.stringify(nodes);
  }

  function findPanelOwner(panel) {
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      if (node.type === "panel" && node.panel === panel) {
        return { kind: "root", index: i };
      }
      if (node.type === "folder" && Array.isArray(node.children)) {
        const childIndex = node.children.indexOf(panel);
        if (childIndex >= 0) {
          return { kind: "folder", folderIndex: i, childIndex };
        }
      }
    }
    return null;
  }

  function removePanel(panel) {
    const owner = findPanelOwner(panel);
    if (!owner) {
      return;
    }
    if (owner.kind === "root") {
      nodes.splice(owner.index, 1);
      return;
    }
    const folder = nodes[owner.folderIndex];
    folder.children.splice(owner.childIndex, 1);
  }

  function removeFolder(folderId) {
    const index = nodes.findIndex(
      (node) => node.type === "folder" && node.id === folderId,
    );
    if (index < 0) {
      return;
    }
    const folder = nodes[index];
    const children = Array.isArray(folder.children) ? [...folder.children] : [];
    nodes.splice(index, 1);
    children.reverse().forEach((panel) => {
      nodes.splice(index, 0, { type: "panel", panel });
    });
  }

  function insertAtRoot(index, node) {
    const clamped = Math.max(0, Math.min(index, nodes.length));
    nodes.splice(clamped, 0, node);
  }

  function insertPanelIntoFolder(folderIndex, childIndex, panel) {
    const folder = nodes[folderIndex];
    if (!folder || folder.type !== "folder") {
      return;
    }
    if (!Array.isArray(folder.children)) {
      folder.children = [];
    }
    const clamped = Math.max(0, Math.min(childIndex, folder.children.length));
    folder.children.splice(clamped, 0, panel);
  }

  function onDragStart(event, payload) {
    dragPayload = payload;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", JSON.stringify(payload));
  }

  function clearDrag() {
    dragPayload = null;
  }

  function handleDropOnRoot(event, insertIndex) {
    event.preventDefault();
    const payload = dragPayload;
    clearDrag();
    if (!payload) {
      return;
    }
    if (payload.kind === "root-panel") {
      const from = nodes.findIndex(
        (node) => node.type === "panel" && node.panel === payload.panel,
      );
      removePanel(payload.panel);
      let target = insertIndex;
      if (from >= 0 && from < insertIndex) {
        target -= 1;
      }
      insertAtRoot(target, { type: "panel", panel: payload.panel });
      render();
      return;
    }
    if (payload.kind === "folder-child") {
      removePanel(payload.panel);
      insertAtRoot(insertIndex, { type: "panel", panel: payload.panel });
      render();
      return;
    }
    if (payload.kind === "folder") {
      const from = nodes.findIndex(
        (node) => node.type === "folder" && node.id === payload.folderId,
      );
      if (from < 0) {
        return;
      }
      const [folder] = nodes.splice(from, 1);
      let target = insertIndex;
      if (from < insertIndex) {
        target -= 1;
      }
      insertAtRoot(target, folder);
      render();
    }
  }

  function handleDropOnFolder(event, folderId, childIndex) {
    event.preventDefault();
    const payload = dragPayload;
    clearDrag();
    if (!payload) {
      return;
    }
    if (payload.kind === "folder") {
      return;
    }
    if (payload.kind !== "root-panel" && payload.kind !== "folder-child") {
      return;
    }
    removePanel(payload.panel);
    const targetFolderIndex = nodes.findIndex(
      (node) => node.type === "folder" && node.id === folderId,
    );
    if (targetFolderIndex < 0) {
      insertAtRoot(nodes.length, { type: "panel", panel: payload.panel });
      render();
      return;
    }
    insertPanelIntoFolder(targetFolderIndex, childIndex, payload.panel);
    render();
  }

  function makeDropGap(onDrop) {
    const gap = document.createElement("li");
    gap.className = "nav-settings-drop-gap";
    gap.addEventListener("dragover", (event) => {
      event.preventDefault();
      gap.classList.add("is-over");
    });
    gap.addEventListener("dragleave", () => {
      gap.classList.remove("is-over");
    });
    gap.addEventListener("drop", (event) => {
      gap.classList.remove("is-over");
      onDrop(event);
    });
    return gap;
  }

  function makeHandle(payload) {
    const handle = document.createElement("span");
    handle.className = "nav-settings-handle";
    handle.draggable = true;
    handle.title = "Перетащить";
    handle.textContent = "⋮⋮";
    handle.addEventListener("dragstart", (event) => onDragStart(event, payload));
    handle.addEventListener("dragend", clearDrag);
    return handle;
  }

  function render() {
    rootList.replaceChildren();
    rootList.appendChild(
      makeDropGap((event) => handleDropOnRoot(event, 0)),
    );
    nodes.forEach((node, index) => {
      const li = document.createElement("li");
      li.className = "nav-settings-item";
      if (node.type === "panel") {
        li.classList.add("nav-settings-item-panel");
        const row = document.createElement("div");
        row.className = "nav-settings-row";
        row.appendChild(
          makeHandle({ kind: "root-panel", panel: node.panel }),
        );
        const label = document.createElement("span");
        label.className = "nav-settings-label";
        label.textContent = panelLabel(node.panel);
        row.appendChild(label);
        li.appendChild(row);
      } else if (node.type === "folder") {
        li.classList.add("nav-settings-item-folder");
        const row = document.createElement("div");
        row.className = "nav-settings-row";
        row.appendChild(
          makeHandle({ kind: "folder", folderId: node.id }),
        );
        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.className = "nav-settings-folder-title";
        titleInput.value = node.title || "";
        titleInput.placeholder = "Название папки";
        titleInput.addEventListener("input", () => {
          node.title = titleInput.value;
          serialize();
        });
        row.appendChild(titleInput);
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "admin-btn admin-btn-secondary nav-settings-remove";
        removeBtn.textContent = "Удалить папку";
        removeBtn.addEventListener("click", () => {
          removeFolder(node.id);
          render();
        });
        row.appendChild(removeBtn);
        li.appendChild(row);

        const childList = document.createElement("ul");
        childList.className = "nav-settings-list nav-settings-children";
        childList.dataset.dropZone = "folder";
        const children = Array.isArray(node.children) ? node.children : [];
        const folderId = node.id;
        childList.appendChild(
          makeDropGap((event) => handleDropOnFolder(event, folderId, 0)),
        );
        children.forEach((panel, childIndex) => {
          const childLi = document.createElement("li");
          childLi.className = "nav-settings-item nav-settings-item-panel";
          const childRow = document.createElement("div");
          childRow.className = "nav-settings-row";
          childRow.appendChild(
            makeHandle({
              kind: "folder-child",
              panel,
              fromFolderId: folderId,
            }),
          );
          const childLabel = document.createElement("span");
          childLabel.className = "nav-settings-label";
          childLabel.textContent = panelLabel(panel);
          childRow.appendChild(childLabel);
          childLi.appendChild(childRow);
          childList.appendChild(childLi);
          childList.appendChild(
            makeDropGap((event) =>
              handleDropOnFolder(event, folderId, childIndex + 1),
            ),
          );
        });
        // drop zone into folder body
        childList.addEventListener("dragover", (event) => {
          event.preventDefault();
        });
        childList.addEventListener("drop", (event) => {
          if (event.target !== childList) {
            return;
          }
          handleDropOnFolder(event, folderId, children.length);
        });
        li.appendChild(childList);
      }
      rootList.appendChild(li);
      rootList.appendChild(
        makeDropGap((event) => handleDropOnRoot(event, index + 1)),
      );
    });
    serialize();
  }

  if (addFolderBtn) {
    addFolderBtn.addEventListener("click", () => {
      const id = `folder-${Date.now().toString(36)}`;
      nodes.push({
        type: "folder",
        id,
        title: "Новая папка",
        children: [],
      });
      render();
    });
  }

  form.addEventListener("submit", () => {
    serialize();
  });

  render();
})();
