// Tagwerk's night sky: movement on intent only (base.html loads it on every page).
// - Depth: the star layers shift a little with the pointer and the scroll position, the near
//   stars more than the far ones, so the sky feels deep.
// - Changing page: the new page's cards come in one after another, quickly.
// - Big moments: Convert to AIFF jumps through hyperspace, Apply sends out a golden burst.
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

  // --- Changing page ------------------------------------------------------------------------
  // The new page's cards and sections come in quickly, one after another (top to bottom).
  // Only for links to another page: sorting, paging and filtering a list don't animate.
  const GROUPS = ".kpis, .with-rail, .stack, .settings-layout, .settings-body, .rail";
  let changingPage = false;
  document.addEventListener("htmx:beforeRequest", (e) => {
    const d = e.detail;
    const config = d && d.boosted && d.requestConfig;
    changingPage = !!config && config.verb === "get" &&
      new URL(config.path, location.href).pathname !== location.pathname;
  });
  function enter() {
    const main = document.querySelector("#page main");
    if (!main || still()) return;
    const cards = [];
    (function collect(el) {
      for (const child of el.children) {
        if (child.matches(GROUPS)) collect(child); // a grid: its cards come in one by one
        else if (child.tagName !== "SCRIPT") cards.push(child);
      }
    })(main);
    cards.slice(0, 16).forEach((card, i) => {
      card.style.animationDelay = `${Math.min(i, 6) * 28}ms`;
      card.classList.add("tw-in");
      card.addEventListener("animationend", function done(e) {
        if (e.target !== card) return; // a child's own animation
        card.classList.remove("tw-in");
        card.style.animationDelay = "";
        card.removeEventListener("animationend", done);
      });
    });
  }
  document.addEventListener("htmx:afterSwap", (e) => {
    if (changingPage && e.detail && e.detail.boosted) enter();
    changingPage = false;
  });
  document.addEventListener("htmx:historyRestore", enter);

  // --- Big moments ----------------------------------------------------------------------------
  // Buttons with data-fx play a short effect when their form is really sent (after any "are you
  // sure?" question): data-fx="warp" (Convert to AIFF) jumps through hyperspace, data-fx="burst"
  // (Apply changes) sends a golden shock wave with sparks out of the button.
  // If the form names what burns (form.twBurnTargets(), the Changes page: the ticked changes),
  // the order is: 1. the sparks fly; 2. the form is sent right away, so the files are written
  // while 3. the list burns away; 4. when both are done the page shows the result once (done=1:
  // the notification, or the progress if the writing takes longer). The server leaves changes
  // that are being written out of the page, so the burnt list never comes back.
  document.addEventListener("submit", (e) => {
    const button = e.submitter, form = e.target;
    const fx = button && button.dataset.fx;
    if (!fx || still()) return;
    const r = button.getBoundingClientRect();
    if (fx === "warp") window.twWarp();
    if (fx !== "burst") return;
    window.twBurst(r.left + r.width / 2, r.top + r.height / 2);
    const burning = typeof form.twBurnTargets === "function" ? form.twBurnTargets() : [];
    if (!burning.length || !window.htmx) return;
    e.preventDefault(); // sent here instead, so the page stays while the list burns
    e.stopImmediatePropagation();
    let answer = null, burnt = false;
    const show = () => {
      if (!answer || !burnt) return;
      const url = new URL(answer, location.href);
      if (!url.searchParams.has("error")) url.searchParams.set("done", "1");
      // To the top: the progress and what is still pending are there (a long list was scrolled).
      window.htmx.ajax("GET", url.pathname + url.search, { target: "#page", select: "#page", swap: "outerHTML show:window:top" });
    };
    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then((response) => { answer = response.url || form.action; show(); })
      .catch(() => location.reload()); // offline or the server is gone: show what is true
    setTimeout(() => window.twDissolve(burning, () => { burnt = true; show(); }), 220); // the sparks reach the list first
  }, true);

  // A canvas, made on first use and hidden in between. ``front``: above the page (the burst),
  // else inside the sky, behind the page (the warp).
  function canvasFor(front) {
    const c = document.createElement("canvas");
    c.className = front ? "tw-fx-canvas" : "tw-warp-canvas";
    c.hidden = true;
    (front ? document.body : sky).appendChild(c);
    return c;
  }
  function begin(c) {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5); // sharper is not worth the work
    c.width = Math.round(innerWidth * dpr);
    c.height = Math.round(innerHeight * dpr);
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.hidden = false;
    return ctx;
  }
  const smooth = (from, to, t) => {
    const k = Math.min(1, Math.max(0, (t - from) / (to - from)));
    return k * k * (3 - 2 * k);
  };

  // Warp: stars are points in 3D (x and y across the window, z the distance: 1 far, 0 at your
  // eye). Each frame they come closer and are drawn as a line from where they were to where they
  // are, so they stretch into streaks. The normal star layers zoom in and fade meanwhile.
  const WARP = { up: 110, hold: 150, down: 380 }; // ms: to full speed, at full speed, to a stop
  const STAR_COLOURS = ["224, 231, 255", "165, 180, 252", "253, 230, 138"]; // white-blue, indigo, gold
  let warpCanvas = null, warpFrame = 0;
  window.twWarp = function () {
    if (still()) return;
    warpCanvas = warpCanvas || canvasFor(false);
    const ctx = begin(warpCanvas);
    const main = document.querySelector("#page main");
    const m = main && main.getBoundingClientRect();
    const centre = { x: m && m.width ? m.left + m.width / 2 : innerWidth / 2, y: innerHeight * 0.42 };
    const spread = Math.max(innerWidth, innerHeight) * 0.5;
    sky.style.setProperty("--wx", `${centre.x}px`);
    sky.style.setProperty("--wy", `${centre.y}px`);
    const star = (z) => {
      const r = Math.random();
      return { x: Math.random() * 2 - 1, y: Math.random() * 2 - 1, z, c: STAR_COLOURS[r < 0.1 ? 2 : r < 0.38 ? 1 : 0] };
    };
    const count = Math.round(Math.min(420, Math.max(160, (innerWidth * innerHeight) / 3600)));
    const stars = Array.from({ length: count }, () => star(0.12 + Math.random() * 0.88));
    const project = (s, z) => {
      const f = 0.42 / Math.max(z, 0.02);
      return [centre.x + s.x * spread * f, centre.y + s.y * spread * f];
    };
    const start = performance.now(), total = WARP.up + WARP.hold + WARP.down;
    let last = start;
    sky.classList.remove("warp");
    void sky.offsetWidth; // restart the zoom
    sky.classList.add("warp");
    setTimeout(() => sky.classList.remove("warp"), WARP.up + WARP.hold);
    cancelAnimationFrame(warpFrame);
    function draw(now) {
      const t = now - start;
      if (t > total) {
        ctx.clearRect(0, 0, innerWidth, innerHeight);
        warpCanvas.hidden = true;
        return;
      }
      const dt = Math.min(48, now - last);
      last = now;
      const speed = smooth(0, WARP.up, t) * (1 - smooth(WARP.up + WARP.hold, total, t));
      const fade = smooth(0, 60, t) * (1 - smooth(total - WARP.down * 0.5, total, t));
      const step = speed * 0.0042 * dt; // how much closer each star comes this frame
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      ctx.globalCompositeOperation = "lighter";
      const glow = 0.32 * speed * fade; // the light at the end of the tunnel
      if (glow > 0.01) {
        const g = ctx.createRadialGradient(centre.x, centre.y, 0, centre.x, centre.y, spread * 0.95);
        g.addColorStop(0, `rgba(224, 231, 255, ${glow.toFixed(3)})`);
        g.addColorStop(0.18, `rgba(129, 140, 248, ${(glow * 0.55).toFixed(3)})`);
        g.addColorStop(1, "rgba(67, 56, 202, 0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, innerWidth, innerHeight);
      }
      ctx.lineCap = "round";
      for (const s of stars) {
        s.z -= step;
        if (s.z < 0.03) Object.assign(s, star(1)); // flew past you: a new one far away
        const [x1, y1] = project(s, Math.max(0.03, s.z + step * 8)); // where it was
        const [x2, y2] = project(s, s.z);
        const near = 1 - Math.min(1, s.z);
        ctx.strokeStyle = `rgba(${s.c}, ${(fade * Math.min(1, 0.25 + near * 1.2)).toFixed(3)})`;
        ctx.lineWidth = 0.6 + near * 2.4;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
      warpFrame = requestAnimationFrame(draw);
    }
    warpFrame = requestAnimationFrame(draw);
  };

  // Burst: a golden shock wave and a second, indigo one rush out of the button, with a flash
  // and sparks that fly out, slow down and fade. Drawn above the page; 700 ms in all.
  const BURST_MS = 700;
  const SPARK_COLOURS = ["245, 197, 66", "253, 230, 138", "255, 255, 255", "165, 180, 252"];
  let burstCanvas = null, burstFrame = 0;
  window.twBurst = function (x, y) {
    if (still()) return;
    burstCanvas = burstCanvas || canvasFor(true);
    const ctx = begin(burstCanvas);
    const reach = Math.max(innerWidth, innerHeight) * 0.6;
    const sparks = Array.from({ length: 90 }, () => {
      const a = Math.random() * Math.PI * 2, v = 0.35 + Math.random() * 1.25; // px per ms
      return { x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, w: 1 + Math.random() * 2,
               c: SPARK_COLOURS[Math.floor(Math.random() * SPARK_COLOURS.length)] };
    });
    const start = performance.now();
    let last = start;
    cancelAnimationFrame(burstFrame);
    function ring(t, colour, width, alpha) {
      if (t <= 0 || t >= 1) return;
      const eased = 1 - Math.pow(1 - t, 3);
      ctx.strokeStyle = `rgba(${colour}, ${(alpha * Math.pow(1 - t, 1.4)).toFixed(3)})`;
      ctx.lineWidth = width * (1 - t) + 0.8;
      ctx.beginPath();
      ctx.arc(x, y, 6 + eased * reach, 0, Math.PI * 2);
      ctx.stroke();
    }
    function draw(now) {
      const t = (now - start) / BURST_MS;
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      if (t >= 1) {
        burstCanvas.hidden = true;
        return;
      }
      const dt = Math.min(48, now - last);
      last = now;
      ctx.globalCompositeOperation = "lighter";
      const flash = 0.55 * Math.pow(1 - t, 3);
      const g = ctx.createRadialGradient(x, y, 0, x, y, 160);
      g.addColorStop(0, `rgba(253, 230, 138, ${flash.toFixed(3)})`);
      g.addColorStop(1, "rgba(245, 197, 66, 0)");
      ctx.fillStyle = g;
      ctx.fillRect(x - 160, y - 160, 320, 320);
      ring(t, "245, 197, 66", 7, 0.95);
      ring(t * 1.25 - 0.12, "129, 140, 248", 4, 0.7);
      ctx.lineCap = "round";
      const drag = Math.pow(0.9935, dt); // they slow down
      const alpha = Math.pow(1 - t, 1.2);
      for (const p of sparks) {
        const px = p.x, py = p.y;
        p.vx *= drag;
        p.vy = p.vy * drag + 0.0009 * dt; // and fall a little
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        ctx.strokeStyle = `rgba(${p.c}, ${alpha.toFixed(3)})`;
        ctx.lineWidth = p.w;
        ctx.beginPath();
        ctx.moveTo(px - p.vx * 10, py - p.vy * 10);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
      }
      burstFrame = requestAnimationFrame(draw);
    }
    burstFrame = requestAnimationFrame(draw);
  };

  // Dissolve: the elements burn away from the bottom up. A wavy, flickering edge climbs them,
  // slowly at first and a little faster as it goes up; just above it they glow hot, below it they
  // are gone (a clip-path that follows the wave), and stardust and a few embers rise from it,
  // swaying and twinkling. Calls done() when the edge reached the top; the dust drifts on over
  // the next page a moment longer. Only what is on screen burns (a long list doesn't burn off the
  // screen or take longer): the rest simply goes when the edge reaches the top.
  let dustCanvas = null, dustFrame = 0;
  const DUST = ["253, 230, 138", "255, 255, 255", "165, 180, 252"];
  // The edge's wave at x: two slow sines, moving, so it flickers like a flame front.
  const wave = (x, now) => Math.sin(x * 0.045 + now * 0.006) * 3 + Math.sin(x * 0.12 - now * 0.011) * 1.6;
  window.twDissolve = function (elements, done) {
    // Table rows aren't clipped in every browser: their cells are.
    const parts = elements.flatMap((el) => (el.tagName === "TR" ? [...el.cells] : [el]))
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter((b) => b.r.height > 0 && b.r.bottom > 0 && b.r.top < innerHeight);
    if (still() || !parts.length) return done();
    dustCanvas = dustCanvas || canvasFor(true);
    const ctx = begin(dustCanvas);
    const top = Math.max(0, Math.min(...parts.map((b) => b.r.top))) - 8;
    const bottom = Math.min(innerHeight, Math.max(...parts.map((b) => b.r.bottom))) + 8;
    // About 0.9 ms per pixel on screen: a full window takes ~1.7 s, never more than 2.2 s; a short
    // strip (the last card above the button) burns quickly instead of crawling.
    const ms = Math.max(800, Math.min(2200, 900 + (bottom - top) * 0.9));
    const dust = [];
    const start = performance.now();
    let last = start, sent = false;
    cancelAnimationFrame(dustFrame);

    function clip(b, edge, now) {
      // Keep what is above the wavy edge: a polygon along the element's top and the wave.
      const { left, top: y0, width, height } = b.r;
      if (edge - 6 > y0 + height) { b.el.style.clipPath = ""; return; } // not reached yet
      if (edge + 6 < y0) { b.el.style.clipPath = "inset(0 0 100% 0)"; return; } // burnt
      const points = ["0 0", `${width}px 0`];
      for (let k = 12; k >= 0; k--) {
        const x = (width * k) / 12;
        const y = Math.max(0, Math.min(height, edge + wave(left + x, now) - y0));
        points.push(`${x.toFixed(1)}px ${y.toFixed(1)}px`);
      }
      b.el.style.clipPath = `polygon(${points.join(", ")})`;
    }

    function draw(now) {
      const t = Math.min(1, (now - start) / ms);
      const dt = Math.min(48, now - last);
      last = now;
      // Semi-slow at the start, a little faster going up (speed from 0.5 to 1.5).
      const edge = bottom - (bottom - top) * (0.5 * t + 0.5 * t * t);
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      ctx.globalCompositeOperation = "lighter";
      const flicker = 0.85 + 0.15 * Math.sin(now * 0.05);
      for (const b of parts) {
        clip(b, edge, now);
        if (t >= 1 || edge < b.r.top - 6 || edge > b.r.bottom + 6) continue;
        const { left, width } = b.r;
        // Heat just above the edge: the cards glow before they go.
        const heat = ctx.createLinearGradient(0, edge - 34, 0, edge);
        heat.addColorStop(0, "rgba(245, 158, 11, 0)");
        heat.addColorStop(1, `rgba(251, 146, 60, ${(0.3 * flicker).toFixed(3)})`);
        ctx.fillStyle = heat;
        ctx.fillRect(left, Math.max(b.r.top, edge - 34), width, Math.min(34, edge - b.r.top + 4));
        // The edge itself: a wide warm glow and a thin bright line, both following the wave.
        for (const [lineWidth, colour] of [[6, `rgba(245, 158, 11, ${(0.35 * flicker).toFixed(3)})`],
                                           [1.6, `rgba(255, 240, 190, ${(0.95 * flicker).toFixed(3)})`]]) {
          ctx.lineWidth = lineWidth;
          ctx.strokeStyle = colour;
          ctx.beginPath();
          for (let x = 0; x <= width; x += 6) {
            const y = edge + wave(left + x, now);
            if (x === 0) ctx.moveTo(left + x, y);
            else ctx.lineTo(left + x, y);
          }
          ctx.stroke();
        }
        // New dust along the edge; now and then an ember. (Capped: a wide screen full of
        // changes mustn't drown the browser in particles.)
        for (let i = 0, n = dust.length < 1400 ? (width / 170) * dt : 0; i < n; i++) {
          const x = left + Math.random() * width;
          const ember = Math.random() < 0.12;
          dust.push({
            x, y: edge + wave(x, now), ember,
            vy: -(ember ? 0.08 + Math.random() * 0.14 : 0.03 + Math.random() * 0.1),
            life: 0, span: (ember ? 700 : 900) + Math.random() * 1100,
            size: ember ? 1.8 + Math.random() * 1.4 : 0.6 + Math.random() * 1.2,
            c: ember ? "251, 176, 80" : DUST[Math.random() < 0.6 ? 0 : Math.random() < 0.6 ? 1 : 2],
            phase: Math.random() * 6.3, sway: 0.01 + Math.random() * 0.025,
          });
        }
      }
      for (let i = dust.length - 1; i >= 0; i--) {
        const p = dust[i];
        p.life += dt;
        if (p.life > p.span) { dust.splice(i, 1); continue; }
        p.x += Math.sin(p.phase + p.life / 260) * p.sway * dt; // swaying
        p.y += p.vy * dt;
        p.vy *= Math.pow(0.9985, dt); // rising slower and slower
        const fade = 1 - p.life / p.span;
        const twinkle = 0.55 + 0.45 * Math.sin(p.phase + p.life / (p.ember ? 45 : 70));
        const alpha = fade * twinkle;
        if (p.ember) { // a soft halo around the glowing core
          ctx.fillStyle = `rgba(${p.c}, ${(alpha * 0.22).toFixed(3)})`;
          ctx.fillRect(p.x - p.size, p.y - p.size, p.size * 3, p.size * 3);
        }
        ctx.fillStyle = `rgba(${p.c}, ${alpha.toFixed(3)})`;
        ctx.fillRect(p.x, p.y, p.size, p.size);
      }
      if (t >= 1 && !sent) {
        sent = true;
        elements.forEach((el) => (el.style.visibility = "hidden")); // also those off screen
        done();
      }
      if (t >= 1 && !dust.length) {
        dustCanvas.hidden = true;
        return;
      }
      dustFrame = requestAnimationFrame(draw);
    }
    dustFrame = requestAnimationFrame(draw);
  };

  // Spotlight under the pointer on lifting tiles
  document.addEventListener("pointermove", (e) => {
    const tile = e.target.closest && e.target.closest(".lift");
    if (!tile || still()) return;
    const r = tile.getBoundingClientRect();
    tile.style.setProperty("--mx", `${e.clientX - r.left}px`);
    tile.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, { passive: true });
})();
