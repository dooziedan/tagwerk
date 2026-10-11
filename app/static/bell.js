// The bell (ADR 0035): opens the notification menu (#bell-panel in base.html). A summary opens
// its card: beside the menu on wide screens, in the menu's place on phones and narrow windows
// (with ← Back). Escape and a click outside close everything.
// Opening the menu or a card marks nothing as read: only the ✓ Read buttons do.
(function () {
  const WIDE = "(min-width: 1100px)"; // the side menu shows (app.css), so the card fits beside
  let opener = null; // the button that opened the menu: it gets the focus back

  const panel = () => document.getElementById("bell-panel");
  const visibleBell = () => [...document.querySelectorAll("[data-bell]")].find((b) => b.offsetParent);

  // Beside the side menu, level with the bell; or just below the floating top bar.
  function place(p) {
    const bell = visibleBell();
    if (matchMedia(WIDE).matches) {
      const side = document.querySelector(".side");
      p.style.left = side.getBoundingClientRect().right + 12 + "px";
      p.style.top = Math.max(12, bell ? bell.getBoundingClientRect().top : 12) + "px";
    } else {
      const bar = document.querySelector(".topbar");
      p.style.left = "";
      p.style.top = (bar ? bar.getBoundingClientRect().bottom : 0) + 8 + "px";
    }
  }

  function expanded(open) {
    document.querySelectorAll("[data-bell]").forEach((b) => b.setAttribute("aria-expanded", open));
  }

  function open(from) {
    const p = panel();
    if (!p) return;
    opener = from;
    document.querySelectorAll("details.dropdown[open]").forEach((d) => (d.open = false));
    closeCard();
    place(p);
    p.hidden = false;
    expanded(true);
    p.focus();
    window.htmx.ajax("GET", "/partials/notifications/menu", { target: "#bell-list", swap: "innerHTML" });
  }

  function close() {
    const p = panel();
    if (!p || p.hidden) return;
    p.hidden = true;
    closeCard();
    expanded(false);
    if (opener && opener.offsetParent) opener.focus();
  }

  function closeCard() {
    const p = panel();
    if (!p) return;
    const shown = p.querySelector("[data-bell-item][aria-current]");
    document.getElementById("bell-card").innerHTML = "";
    p.classList.remove("with-card");
    if (shown) {
      shown.removeAttribute("aria-current");
      if (p.contains(document.activeElement) || document.activeElement === document.body) shown.focus();
    }
  }

  document.addEventListener("click", (e) => {
    const bell = e.target.closest("[data-bell], [data-open-bell]");
    if (bell) {
      e.preventDefault();
      panel().hidden ? open(bell.matches("[data-bell]") ? bell : visibleBell()) : close();
      return;
    }
    if (e.target.closest("[data-bell-back]")) return closeCard();
    const item = e.target.closest("[data-bell-item]");
    if (item) {
      panel().querySelectorAll("[data-bell-item][aria-current]").forEach((b) => b.removeAttribute("aria-current"));
      item.setAttribute("aria-current", "true");
      return;
    }
    const p = panel();
    if (p && !p.hidden && !p.contains(e.target) && document.contains(e.target)) close();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel() && !panel().hidden) close();
  });

  document.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail.target;
    if (target.id === "bell-card") {
      panel().classList.add("with-card");
      const card = target.querySelector(".note-card");
      if (card) card.focus();
    } else if (target.id === "bell-list" && panel().classList.contains("with-card")) {
      closeCard(); // ✓ Read: back to the list, without it
      panel().focus();
    }
  });

  addEventListener("resize", () => {
    const p = panel();
    if (p && !p.hidden) place(p);
  });
})();
