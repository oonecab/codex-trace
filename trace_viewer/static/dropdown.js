"use strict";
// Styled replacement for the browser's native <select> popup, which cannot be themed.
// The real <select> stays in the DOM (hidden), so existing code keeps reading `.value` and listening for "change".
(() => {
  const valueDescriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  let openMenu = null;

  function make(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function enhance(select) {
    if (select.multiple || select.dataset.native !== undefined) return;
    const wrap = make("div", "dd");
    const trigger = make("button", "dd-trigger");
    const label = make("span", "dd-label");
    const menu = make("div", "dd-menu");
    let items = [];
    let active = -1;

    trigger.type = "button";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (select.getAttribute("aria-label")) trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    trigger.append(label);
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    select.before(wrap);
    wrap.append(trigger, menu, select);
    select.classList.add("dd-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    // Programmatic `select.value = x` must refresh the visible label.
    Object.defineProperty(select, "value", {
      configurable: true,
      get() {
        return valueDescriptor.get.call(this);
      },
      set(v) {
        valueDescriptor.set.call(this, v);
        sync();
      },
    });

    function sync() {
      wrap.hidden = select.hidden;
      trigger.disabled = select.disabled;
      const chosen = select.options[select.selectedIndex];
      label.textContent = chosen ? chosen.textContent : "";
      trigger.title = chosen && chosen.title ? chosen.title : "";
      if (!menu.hidden) build();
    }

    function build() {
      items = [...select.options].map((option, index) => {
        const row = make("div", "dd-option");
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", String(index === select.selectedIndex));
        row.append(
          make("span", "dd-text", option.textContent),
          make("span", "dd-check", index === select.selectedIndex ? "✓" : ""),
        );
        if (option.title) row.title = option.title;
        row.addEventListener("mousedown", (e) => e.preventDefault());
        row.addEventListener("click", () => choose(index));
        row.addEventListener("mousemove", () => highlight(index, false));
        return row;
      });
      menu.replaceChildren(...items);
    }

    function highlight(index, scroll = true) {
      active = Math.max(0, Math.min(items.length - 1, index));
      items.forEach((row, i) => row.classList.toggle("active", i === active));
      if (scroll && items[active]) items[active].scrollIntoView({ block: "nearest" });
    }

    function open() {
      if (openMenu && openMenu !== close) openMenu();
      build();
      menu.hidden = false;
      wrap.classList.add("open");
      trigger.setAttribute("aria-expanded", "true");
      const room = window.innerHeight - trigger.getBoundingClientRect().bottom;
      wrap.classList.toggle(
        "up",
        room < Math.min(menu.scrollHeight, 320) + 16 && trigger.getBoundingClientRect().top > room,
      );
      highlight(Math.max(0, select.selectedIndex));
      openMenu = close;
    }

    function close() {
      menu.hidden = true;
      wrap.classList.remove("open", "up");
      trigger.setAttribute("aria-expanded", "false");
      if (openMenu === close) openMenu = null;
    }

    function choose(index) {
      const changed = index !== select.selectedIndex;
      select.selectedIndex = index;
      sync();
      close();
      trigger.focus();
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    trigger.addEventListener("click", () => (menu.hidden ? open() : close()));
    trigger.addEventListener("keydown", (e) => {
      const closed = menu.hidden;
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        if (closed) return open();
        if (e.key === "ArrowDown") highlight(active + 1);
        else if (e.key === "ArrowUp") highlight(active - 1);
        else choose(active);
      } else if (!closed && e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation(); // do not also close the detail panel
        close();
      } else if (!closed && (e.key === "Home" || e.key === "End")) {
        e.preventDefault();
        highlight(e.key === "Home" ? 0 : items.length - 1);
      } else if (!closed && e.key === "Tab") {
        close();
      }
    });
    trigger.addEventListener("blur", () => setTimeout(() => !wrap.contains(document.activeElement) && close(), 0));

    new MutationObserver(sync).observe(select, {
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "disabled"],
    });
    select.addEventListener("change", sync);
    sync();
  }

  document.addEventListener("click", (e) => {
    if (openMenu && !e.target.closest(".dd")) openMenu();
  });
  document.querySelectorAll("select").forEach(enhance);
})();
