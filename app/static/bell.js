// The bell (ADR 0035, 0043): opens the notification menu (#bell-panel in base.html) with the
// unread notifications. A summary is a link to the notification on the Notifications page; ✓
// marks it as read in place. Escape and a click outside close the menu.
// Opening the menu marks nothing as read.
(function () {
  const WIDE = "(min-width: 1100px)"; // the side menu shows (app.css)
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
    expanded(false);
    if (opener && opener.offsetParent) opener.focus();
  }

  document.addEventListener("click", (e) => {
    const bell = e.target.closest("[data-bell], [data-open-bell]");
    if (bell) {
      e.preventDefault();
      panel().hidden ? open(bell.matches("[data-bell]") ? bell : visibleBell()) : close();
      return;
    }
    const p = panel();
    if (p && !p.hidden && !p.contains(e.target) && document.contains(e.target)) close();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel() && !panel().hidden) close();
  });

  // ✓ removed the row that had the focus: the menu takes it, so the keyboard stays in it.
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "bell-list" && document.activeElement === document.body) panel().focus();
  });

  // The tab's title starts with the bell's number, like other web apps: "(3) Inbox · Tagwerk".
  function title() {
    const count = document.getElementById("bell-count-side");
    const n = count ? Number(count.dataset.count || 0) : 0;
    const plain = document.title.replace(/^\(\d+\) /, "");
    document.title = n ? `(${n}) ${plain}` : plain;
  }
  title();
  document.addEventListener("htmx:afterSettle", title);

  addEventListener("resize", () => {
    const p = panel();
    if (p && !p.hidden) place(p);
  });
})();
