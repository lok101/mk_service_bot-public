(function (root) {
  function parseCarouselGroups(text) {
    try {
      const parsed = JSON.parse(text || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_err) {
      return [];
    }
  }

  function viewFrameUrl(batchId, frameIndex) {
    return `/admin/visit-photo-review/frames/${batchId}/${frameIndex}/view`;
  }

  function disposeActionUrl(batchId, queryString) {
    const qs = queryString ? String(queryString).replace(/^\?/, "") : "";
    const base = `/admin/visit-photo-review/blocks/${batchId}/unrecognized/dispose`;
    return qs ? `${base}?${qs}` : base;
  }

  function install() {
    if (typeof document === "undefined") return;
    const dataEl = document.getElementById("visit-photo-carousel-data");
    if (!dataEl) return;

    /** @type {Array<object>} */
    let groups = parseCarouselGroups(dataEl.textContent || "[]");

    const byId = Object.fromEntries(groups.map((g) => [g.group_id, g]));
    const els = {
      carousel: document.getElementById("visit-photo-carousel"),
      photo: document.getElementById("carousel-photo"),
      counter: document.getElementById("carousel-counter"),
      hint: document.getElementById("carousel-viewed-hint"),
      title: document.getElementById("carousel-title"),
      machine: document.getElementById("carousel-machine"),
      technician: document.getElementById("carousel-technician"),
      date: document.getElementById("carousel-date"),
      error: document.getElementById("carousel-error"),
      techSection: document.getElementById("tech-section"),
      modelSection: document.getElementById("model-section"),
      techActions: document.getElementById("tech-actions"),
      modelActions: document.getElementById("model-actions"),
      disposeSection: document.getElementById("dispose-section"),
      disposeForm: document.getElementById("dispose-form"),
      disposeIndex: document.getElementById("dispose-index"),
      disposeContentActions: document.getElementById("dispose-content-actions"),
      prev: document.getElementById("carousel-prev"),
      next: document.getElementById("carousel-next"),
      close: document.getElementById("carousel-close"),
      toast: document.getElementById("visit-photo-toast"),
    };

    let activeGroup = null;
    let index = 0;
    let toastTimer = null;

    function showToast(text) {
      if (!els.toast) return;
      els.toast.textContent = text;
      els.toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        els.toast.hidden = true;
      }, 2200);
    }

    function showError(text) {
      if (!els.error) return;
      if (!text) {
        els.error.hidden = true;
        els.error.textContent = "";
        return;
      }
      els.error.hidden = false;
      els.error.textContent = text;
    }

    function formatDate(iso) {
      try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString("ru-RU", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch (_err) {
        return iso;
      }
    }

    function currentFrame() {
      if (!activeGroup || !activeGroup.frames.length) return null;
      return activeGroup.frames[index];
    }

    async function recordView(frame) {
      if (!frame) return;
      try {
        await fetch(viewFrameUrl(frame.batch_id, frame.index), {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: "",
          credentials: "same-origin",
        });
      } catch (_err) {
        /* keep carousel open even if view POST fails */
      }
    }

    function buildDefectButtons() {
      els.techActions.innerHTML = "";
      els.modelActions.innerHTML = "";
      const defects = activeGroup.defects || [];
      if (!defects.length) {
        const p = document.createElement("p");
        p.className = "admin-muted";
        p.textContent = "Нет кнопок в каталоге";
        els.techActions.appendChild(p);
      } else {
        for (const item of defects) {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "admin-btn";
          b.textContent = item.label;
          b.dataset.code = item.code;
          b.addEventListener("click", () => markDefect(item.code, item.label));
          els.techActions.appendChild(b);
        }
      }
      const modelBtn = document.createElement("button");
      modelBtn.type = "button";
      modelBtn.className = "admin-btn admin-btn-secondary";
      modelBtn.textContent = "Кадр не в этой группе";
      modelBtn.dataset.systemError = "1";
      modelBtn.addEventListener("click", () => markSystemError());
      els.modelActions.appendChild(modelBtn);
    }

    function buildDisposeControls(frame) {
      const qs = new URLSearchParams(window.location.search);
      // name="action" on submit buttons shadows form.action → RadioNodeList
      els.disposeForm.setAttribute(
        "action",
        disposeActionUrl(frame.batch_id, qs.toString()),
      );
      els.disposeIndex.value = String(frame.index);
      els.disposeContentActions.innerHTML = "";
      for (const group of activeGroup.content_groups || []) {
        const btn = document.createElement("button");
        btn.type = "submit";
        btn.name = "action";
        btn.value = "content";
        btn.className = "admin-btn visit-photo-dispose-group";
        btn.dataset.targetGroupId = group.group_id;
        btn.textContent = group.title;
        els.disposeContentActions.appendChild(btn);
      }
    }

    function removeDisposedFrame() {
      if (!activeGroup) return;
      activeGroup.frames.splice(index, 1);
      if (!activeGroup.frames.length) {
        closeCarousel();
        window.location.reload();
        return;
      }
      if (index >= activeGroup.frames.length) index = 0;
      paintCarousel();
      showToast("Кадр разобран");
    }

    async function submitDispose(event) {
      event.preventDefault();
      const frame = currentFrame();
      if (!frame || !els.disposeForm) return;
      const submitter = event.submitter;
      if (!submitter || submitter.name !== "action") return;
      const action = submitter.value;
      const targetGroupId =
        action === "content" ? submitter.dataset.targetGroupId || "" : "";
      if (action === "content" && !targetGroupId) return;
      const body = new URLSearchParams();
      body.set("index", els.disposeIndex.value);
      body.set("target_group_id", targetGroupId);
      body.set("action", action);
      let response;
      try {
        response = await fetch(els.disposeForm.getAttribute("action"), {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            Accept: "application/json",
          },
          body: body.toString(),
          credentials: "same-origin",
        });
      } catch (_err) {
        showError("Не удалось разобрать кадр");
        return;
      }
      let payload = {};
      try {
        payload = await response.json();
      } catch (_err) {
        payload = {};
      }
      if (!response.ok) {
        showError(payload.error || payload.detail || "Не удалось разобрать кадр");
        return;
      }
      removeDisposedFrame();
    }

    function paintButtons(frame) {
      const codes = new Set(frame.selected_codes || []);
      for (const btn of els.techActions.querySelectorAll("button[data-code]")) {
        btn.classList.toggle("demo-mark-active", codes.has(btn.dataset.code));
      }
      for (const btn of els.modelActions.querySelectorAll("button[data-system-error]")) {
        btn.classList.toggle("demo-mark-active", Boolean(frame.system_error));
      }
    }

    async function paintCarousel() {
      const frame = currentFrame();
      if (!frame || !activeGroup) return;
      showError("");
      els.photo.src = frame.photo_href;
      els.photo.alt = `${activeGroup.title}, кадр ${frame.index}`;
      els.counter.textContent = `Фото ${index + 1} из ${activeGroup.frames.length}`;
      els.machine.textContent = frame.machine_name || frame.machine_id;
      els.technician.textContent = frame.technician_name || frame.technician_id;
      els.date.textContent = formatDate(frame.occurred_at);
      els.hint.textContent = "Просмотрено при открытии";
      if (activeGroup.is_unrecognized) {
        els.techSection.hidden = true;
        els.modelSection.hidden = true;
        els.disposeSection.hidden = false;
        buildDisposeControls(frame);
      } else {
        els.techSection.hidden = false;
        els.modelSection.hidden = false;
        els.disposeSection.hidden = true;
        paintButtons(frame);
      }
      await recordView(frame);
    }

    function applyMarkToCurrentFrame(frame, payload) {
      frame.selected_codes = payload.defect_codes || [];
      frame.system_error = Boolean(payload.system_error);
    }

    async function markDefect(code, label) {
      const frame = currentFrame();
      if (!frame || !activeGroup) return;
      const body = new URLSearchParams();
      body.set("defect_code", code);
      body.set("index", String(frame.index));
      const response = await fetch(
        `/admin/visit-photo-review/blocks/${frame.batch_id}/${activeGroup.group_id}/mark`,
        {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
          credentials: "same-origin",
        }
      );
      let payload = {};
      try {
        payload = await response.json();
      } catch (_err) {
        payload = {};
      }
      if (!response.ok) {
        showError(payload.error || "Не удалось записать отметку");
        return;
      }
      applyMarkToCurrentFrame(frame, payload);
      paintButtons(frame);
      showToast(payload.cleared ? "Отметка снята" : `Записано сразу: «${label}»`);
    }

    async function markSystemError() {
      const frame = currentFrame();
      if (!frame || !activeGroup) return;
      const body = new URLSearchParams();
      body.set("system_error", "1");
      body.set("index", String(frame.index));
      const response = await fetch(
        `/admin/visit-photo-review/blocks/${frame.batch_id}/${activeGroup.group_id}/mark`,
        {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
          credentials: "same-origin",
        }
      );
      let payload = {};
      try {
        payload = await response.json();
      } catch (_err) {
        payload = {};
      }
      if (!response.ok) {
        showError(payload.error || "Не удалось записать отметку");
        return;
      }
      applyMarkToCurrentFrame(frame, payload);
      paintButtons(frame);
      showToast(payload.cleared ? "Отметка снята" : "Записано сразу: «Кадр не в этой группе»");
    }

    function openCarousel(groupId) {
      const group = byId[groupId];
      if (!group || group.is_missing || !group.frames || !group.frames.length) {
        showToast("В группе нет кадров по фильтру");
        return;
      }
      activeGroup = group;
      index = 0;
      els.title.textContent = group.title;
      if (!group.is_unrecognized) {
        buildDefectButtons();
      }
      els.carousel.hidden = false;
      paintCarousel();
    }

    function closeCarousel() {
      els.carousel.hidden = true;
      activeGroup = null;
      showError("");
    }

    function step(delta) {
      if (!activeGroup || !activeGroup.frames.length) return;
      index = (index + delta + activeGroup.frames.length) % activeGroup.frames.length;
      paintCarousel();
    }

    document.querySelectorAll("[data-open-carousel]").forEach((btn) => {
      btn.addEventListener("click", () => openCarousel(btn.getAttribute("data-group-id")));
    });
    els.prev.addEventListener("click", () => step(-1));
    els.next.addEventListener("click", () => step(1));
    els.close.addEventListener("click", closeCarousel);
    els.carousel.addEventListener("click", (event) => {
      if (event.target === els.carousel) closeCarousel();
    });
    if (els.disposeForm) {
      els.disposeForm.addEventListener("submit", submitDispose);
    }
    document.addEventListener("keydown", (event) => {
      if (els.carousel.hidden) return;
      if (event.key === "Escape") closeCarousel();
      if (event.key === "ArrowLeft") step(-1);
      if (event.key === "ArrowRight") step(1);
    });
  }

  const api = {
    parseCarouselGroups: parseCarouselGroups,
    viewFrameUrl: viewFrameUrl,
    disposeActionUrl: disposeActionUrl,
    install: install,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined") {
    root.VisitPhotoReviewQueue = api;
  }
  if (typeof document !== "undefined") {
    install();
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
