// Tagwerk's night sky: movement on intent only (base.html loads it on every page).
// - Depth: the star layers shift a little with the pointer and the scroll position, the near
//   stars more than the far ones, so the sky feels deep.
// - Warp: when you change page, the stars stretch into streaks for a moment (hx-boost swaps).
// - Spotlight: tiles that lift on hover get a soft light under the pointer (--mx/--my).
// Nothing runs with "reduce motion" or lighter effects; the page works the same without it.
(function () {
  const sky = document.querySelector(".tw-sky");
  const still = () =>
    matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.documentElement.dataset.effects === "light" ||
    document.documentElement.dataset.motion === "still";
  if (!sky) return;

  const layers = [...sky.querySelectorAll(".tw-depth")]; // far, mid, near
  const strength = [5, 11, 20]; // pixels at the window edge
  const scrollFactor = [0.015, 0.035, 0.07];
  let px = 0, py = 0, queued = false;

  function apply() {
    queued = false;
    if (still()) {
      layers.forEach((l) => (l.style.transform = ""));
      return;
    }
    const y = window.scrollY || 0;
    layers.forEach((l, i) => {
      l.style.transform = `translate3d(${(-px * strength[i]).toFixed(1)}px, ${(-py * strength[i] - y * scrollFactor[i]).toFixed(1)}px, 0)`;
    });
  }
  function queue() {
    if (!queued) { queued = true; requestAnimationFrame(apply); }
  }
  if (matchMedia("(hover: hover)").matches) {
    window.addEventListener("pointermove", (e) => {
      px = e.clientX / innerWidth - 0.5;
      py = e.clientY / innerHeight - 0.5;
      queue();
    }, { passive: true });
  }
  window.addEventListener("scroll", queue, { passive: true });

  // Warp on page change: htmx fires beforeRequest for boosted links.
  window.twWarp = function () {
    if (still()) return;
    sky.classList.add("warp");
    setTimeout(() => sky.classList.remove("warp"), 260);
  };
  document.addEventListener("htmx:beforeRequest", (e) => { if (e.detail && e.detail.boosted) window.twWarp(); });

  // Spotlight under the pointer on lifting tiles
  document.addEventListener("pointermove", (e) => {
    const tile = e.target.closest && e.target.closest(".lift");
    if (!tile || still()) return;
    const r = tile.getBoundingClientRect();
    tile.style.setProperty("--mx", `${e.clientX - r.left}px`);
    tile.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, { passive: true });
})();
