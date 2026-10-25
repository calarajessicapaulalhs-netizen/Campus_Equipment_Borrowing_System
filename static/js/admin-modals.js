(() => {
  const dialog = document.querySelector("#action-modal");
  const content = document.querySelector("#action-modal-content");
  const title = document.querySelector("#action-modal-title");

  if (!dialog || !content || !title) return;

  const showPage = (html, fallbackUrl) => {
    try {
      const page = new DOMParser().parseFromString(html, "text/html");

      // If redirected to login page or unauthenticated session
      if (page.querySelector(".auth-split-wrapper") || page.querySelector('form[action*="login"]')) {
        window.location.href = "/accounts/login/";
        return;
      }

      const main = page.querySelector("main.wrap") ||
                   page.querySelector("main") ||
                   page.querySelector(".admin-content") ||
                   page.querySelector(".wrap") ||
                   page.querySelector(".form-panel") ||
                   page.querySelector("form") ||
                   page.body;

      const heading = page.querySelector("h1") || main?.querySelector("h1");

      const inner = main ? main.innerHTML.trim() : "";
      if (!inner || inner === "<p>Could not load this page.</p>") {
        if (fallbackUrl) {
          window.location.href = fallbackUrl;
          return;
        }
      }

      content.innerHTML = inner || "<p>Could not load this page.</p>";
      title.textContent = heading ? heading.textContent.trim() : "Details";
    } catch (err) {
      if (fallbackUrl) {
        window.location.href = fallbackUrl;
      } else {
        content.innerHTML = `<p class="alert alert-error">${err.message}</p>`;
      }
    }
  };

  document.addEventListener("click", async (event) => {
    const trigger = event.target.closest("a.modal-trigger");
    if (!trigger || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    content.innerHTML = "<p>Loading…</p>";
    title.textContent = "Loading";
    dialog.showModal();

    try {
      const response = await fetch(trigger.href, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });

      if (response.redirected || (response.url && response.url.includes("/login"))) {
        window.location.href = response.url || "/accounts/login/";
        return;
      }

      if (!response.ok) {
        window.location.href = trigger.href;
        return;
      }

      const text = await response.text();
      showPage(text, trigger.href);
    } catch (error) {
      window.location.href = trigger.href;
    }
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target.closest(".modal-close")) {
      if (event.target.closest?.(".modal-close")) event.preventDefault();
      dialog.close();
    }
  });

  dialog.addEventListener("input", (event) => {
    const field = event.target;
    if (field.matches?.('[name="reason"]') && field.value.trim()) {
      field.setCustomValidity("");
    }
  });

  dialog.addEventListener("submit", async (event) => {
    if (event.defaultPrevented) return;
    const form = event.target.closest("form");
    if (!form || form.method.toLowerCase() !== "post") return;
    if (form.dataset.standardSubmit === "true") return;

    // Run form onsubmit handler if present
    if (typeof form.onsubmit === "function") {
      const result = form.onsubmit(event);
      if (result === false || event.defaultPrevented) {
        event.preventDefault();
        return;
      }
    }

    event.preventDefault();
    const submitter = event.submitter;
    if (submitter?.name === "decision") {
      const reason = form.querySelector('[name="reason"]');
      if (reason && !reason.value.trim()) {
        const action = submitter.value === "reject" ? "rejecting" : "approving";
        reason.setCustomValidity(`Enter a reason before ${action} this request.`);
        reason.reportValidity();
        reason.focus();
        return;
      }
    }
    form.querySelector('[name="reason"]')?.setCustomValidity("");
    const formData = new FormData(form);
    if (submitter?.name && submitter.value) {
      formData.set(submitter.name, submitter.value);
    }
    const buttonText = submitter?.textContent.trim();
    if (submitter) {
      submitter.disabled = true;
      submitter.textContent = "Saving…";
    }

    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });

      if (response.redirected) {
        window.location.reload();
        return;
      }

      const text = await response.text();
      showPage(text, window.location.href);
      const notice = content.querySelector(".alert");
      if (!response.ok && notice) notice.focus();
    } catch (error) {
      content.insertAdjacentHTML(
        "afterbegin",
        `<p class="alert alert-error" role="alert">${error.message}</p>`,
      );
    } finally {
      if (submitter?.isConnected) {
        submitter.disabled = false;
        submitter.textContent = buttonText || "Save";
      }
    }
  });
})();

(() => {
  const dialog = document.querySelector("[data-notification-dialog]");
  if (!dialog) return;
  dialog.querySelector("[data-notification-close]")?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  if (typeof dialog.showModal === "function") dialog.showModal();
})();
