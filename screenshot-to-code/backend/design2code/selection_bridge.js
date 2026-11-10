/* Preview-only bridge; exported projects do not contain this file. */
(() => {
  let selectionToken = null;
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || !event.data || event.data.type !== "d2c-select-mode") return;
    selectionToken = event.data.enabled && typeof event.data.token === "string" ? event.data.token : null;
    document.documentElement.style.cursor = selectionToken ? "crosshair" : "";
  });
  for (const type of ["pointerdown", "pointerup", "mousedown", "mouseup", "touchstart", "touchend", "submit"]) {
    document.addEventListener(type, (event) => {
      if (!selectionToken) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, { capture: true, passive: false });
  }
  document.addEventListener("keydown", (event) => {
    if (!selectionToken || event.key !== "Escape") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.parent.postMessage({ type: "d2c-selection-cancelled", token: selectionToken }, "*");
    selectionToken = null;
    document.documentElement.style.cursor = "";
  }, true);
  document.addEventListener("click", (event) => {
    if (!selectionToken || !(event.target instanceof Element)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const element = event.target;
    const parts = [];
    let current = element;
    while (current && current.tagName.toLowerCase() !== "html" && parts.length < 6) {
      const classes = (current.getAttribute("class") || "").split(/\s+/).filter(Boolean).slice(0, 3);
      parts.unshift(current.tagName.toLowerCase() + classes.map((name) => `.${name}`).join(""));
      current = current.parentElement;
    }
    const identical = Array.from(document.getElementsByTagName(element.tagName)).filter((other) => other.outerHTML === element.outerHTML);
    const context = `Element location: ${parts.join(" > ")}` + (identical.length > 1 ? `; matching element ${identical.indexOf(element) + 1} of ${identical.length} in document order.` : "");
    window.parent.postMessage({ type: "d2c-element-selected", token: selectionToken, html: element.outerHTML.slice(0, 2000), context: context.slice(0, 800), label: (element.textContent || element.tagName).trim().slice(0, 80) }, "*");
    selectionToken = null;
    document.documentElement.style.cursor = "";
  }, true);
})();
