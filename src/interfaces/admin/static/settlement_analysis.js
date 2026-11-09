(() => {
  const clusterForm = document.getElementById("settlement-analysis-cluster-form");
  const sessionsInput = document.getElementById("settlement-sessions-query");
  const techHidden = document.getElementById("settlement-sessions-hidden");
  if (!clusterForm || !sessionsInput) {
    return;
  }

  const syncSessions = () => {
    const checked = Array.from(
      clusterForm.querySelectorAll('input[data-cluster-checkbox="1"]:checked'),
    ).map((el) => el.value);
    const csv = checked.join(",");
    sessionsInput.value = csv;
    if (techHidden) {
      techHidden.value = csv;
    }
  };

  clusterForm.querySelectorAll('input[data-cluster-checkbox="1"]').forEach((box) => {
    box.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    box.addEventListener("change", () => {
      syncSessions();
      clusterForm.requestSubmit();
    });
  });
  clusterForm.querySelectorAll("[data-cluster-check-label]").forEach((label) => {
    label.addEventListener("click", (event) => {
      event.stopPropagation();
    });
  });

  const techSelect = document.getElementById("settlement-technician");
  if (techSelect) {
    techSelect.addEventListener("change", () => {
      const techForm = document.getElementById("settlement-analysis-tech-form");
      if (techHidden) {
        techHidden.value = "";
      }
      if (techForm) {
        techForm.requestSubmit();
      }
    });
  }
})();
