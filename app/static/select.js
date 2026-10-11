// Shift-click to tick a range of tracks, like in a file manager: tick one checkbox, hold Shift
// and click another, and every checkbox in between is set the same way (ticked, or unticked
// if the Shift-click unticked a box). The range starts at the box clicked last.
//
// A list opts in with data-range-select (on the <tbody>, so the "select all" box in the header
// isn't part of it). Each box that changes fires its own "change" event, so the page counts it
// as if it had been clicked by hand. Rows that are hidden (filtered out) are skipped.
(() => {
  const BOX = "[data-range-select] input[type=checkbox]";
  let last = null; // the box clicked last: the start of the next range

  // Shift + mouse button would also select the page's text between the two clicks.
  // Stopping the mousedown prevents that; the click still ticks the box.
  document.addEventListener("mousedown", (e) => {
    if (e.shiftKey && e.target instanceof Element && e.target.matches(BOX)) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const box = e.target;
    if (!(box instanceof HTMLInputElement) || !box.matches(BOX)) return;
    const list = box.closest("[data-range-select]");
    // After a page change the old box is gone: list.contains() is false, so no range.
    if (e.shiftKey && last && last !== box && list.contains(last)) {
      const boxes = [...list.querySelectorAll("input[type=checkbox]")].filter(
        (b) => !b.disabled && !b.closest("[hidden]"),
      );
      const from = boxes.indexOf(last), to = boxes.indexOf(box);
      if (from >= 0 && to >= 0) {
        boxes.slice(Math.min(from, to), Math.max(from, to) + 1).forEach((b) => {
          if (b.checked === box.checked) return;
          b.checked = box.checked;
          b.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }
    }
    last = box;
  });
})();
