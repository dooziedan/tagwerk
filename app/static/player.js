// The play bar at the bottom of the window: one track at a time, play/pause, a progress bar
// and stop (which also hides the bar). No queue.
//
// A play button carries the track in data attributes:
//   data-play="/tracks/1/audio"  data-type="audio/flac"  data-mp3="/tracks/1/audio.mp3"
//   data-title="…"  data-duration="248.5"
// If the browser can't play the file's format (AIFF, mostly ALAC), it plays data-mp3 instead:
// Tagwerk converts on the fly, and jumping restarts the conversion at that point (?start=).
(() => {
  const bar = document.getElementById("player");
  if (!bar) return;
  const audio = new Audio();
  const toggle = document.getElementById("player-toggle");
  const seek = document.getElementById("player-seek");
  const time = document.getElementById("player-time");
  const title = document.getElementById("player-title");
  let track = null; // the dataset of the button that started it
  let converted = false; // playing the on-the-fly MP3
  let offset = 0; // with the MP3: where the current stream started, in seconds
  let dragging = false;
  const mute = document.getElementById("player-mute");
  const volume = document.getElementById("player-volume");

  const duration = () =>
    converted || !isFinite(audio.duration) ? Number(track.duration) || 0 : audio.duration;
  const position = () => offset + audio.currentTime;
  const clock = (s) => {
    s = Math.max(0, Math.floor(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  function show(playing) {
    toggle.classList.toggle("playing", playing);
    toggle.setAttribute("aria-label", playing ? "Pause" : "Play");
    document.querySelectorAll("[data-play]").forEach((b) => {
      const current = track && b.dataset.play === track.play;
      b.classList.toggle("playing", current && playing);
      b.setAttribute("aria-pressed", current && playing ? "true" : "false");
    });
  }

  // Volume and mute: the button mutes (and unmutes), the slider sets the level. The level is
  // remembered in this browser.
  //
  // The sound goes through a Web Audio gain node, which glides to each new level in about
  // 30 ms; setting audio.volume directly jumps, and fast slider moves can be heard as steps.
  // The slider is squared (50 % → 25 % gain) so it feels even to the ear. Without Web Audio,
  // it falls back to audio.volume.
  //
  // Touch screens (no hover: phones, tablets) have no volume control at all (hidden in CSS):
  // the hardware buttons set the volume, and the plain audio element plays at full level.
  // Web Audio is skipped there too, since iPhones silence it with the mute switch.
  const touch = matchMedia("(hover: none)").matches;
  let level = 1; // the slider, 0…1
  let muted = false;
  let context = null;
  let gain = null;

  function applyVolume() {
    if (touch) return;
    const target = muted ? 0 : level * level;
    if (gain) gain.gain.setTargetAtTime(target, context.currentTime, 0.01);
    else audio.volume = target;
  }

  function startWebAudio() {
    // Only after a click (browsers block sound before), and only once.
    if (touch) return;
    if (context) return context.state === "suspended" && context.resume();
    try {
      context = new AudioContext();
      gain = context.createGain();
      gain.gain.value = muted ? 0 : level * level;
      context.createMediaElementSource(audio).connect(gain).connect(context.destination);
      audio.volume = 1;
    } catch (e) {
      context = gain = null;
    }
  }

  function showVolume() {
    const silent = muted || level === 0;
    mute.classList.toggle("muted", silent);
    mute.setAttribute("aria-label", silent ? "Unmute" : "Mute");
    mute.title = silent ? "Unmute" : "Mute";
    volume.value = String(muted ? 0 : Math.round(level * 100));
  }
  try {
    const saved = parseFloat(localStorage.getItem("tagwerk-volume"));
    if (saved > 0 && saved <= 1) level = saved;
  } catch (e) {}
  applyVolume();
  showVolume();

  function load(start) {
    if (converted) {
      offset = start;
      audio.src = `${track.mp3}?start=${start.toFixed(2)}`;
    } else {
      offset = 0;
      audio.src = track.play;
      if (start) audio.currentTime = start;
    }
    audio.play().catch(() => show(false));
  }

  function play(data) {
    startWebAudio();
    if (track && track.play === data.play) {
      audio.paused ? audio.play() : audio.pause();
      return;
    }
    track = { ...data };
    converted = !audio.canPlayType(track.type);
    title.textContent = track.title;
    bar.hidden = false;
    document.body.classList.add("with-player");
    load(0);
  }

  function stop() {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    track = null;
    bar.hidden = true;
    document.body.classList.remove("with-player");
    show(false);
  }

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-play]");
    if (!button) return;
    e.preventDefault();
    play(button.dataset);
  });
  mute.addEventListener("click", () => {
    if (level === 0) level = 0.5; // muted by the slider: unmute to a level
    else muted = !muted;
    applyVolume();
    showVolume();
  });
  volume.addEventListener("input", () => {
    muted = false;
    level = volume.value / 100;
    applyVolume();
    showVolume();
    try {
      // 0 counts as muted and isn't remembered: the next visit shouldn't start silent.
      if (level > 0) localStorage.setItem("tagwerk-volume", String(level));
    } catch (e) {}
  });
  toggle.addEventListener("click", () => {
    startWebAudio();
    audio.paused ? audio.play() : audio.pause();
  });
  document.getElementById("player-stop").addEventListener("click", stop);
  // Space pauses and resumes while a track is loaded (keyboards: desktop). Left alone while
  // typing, and on buttons, links and other controls, where space already does something
  // (on the focused ▶ or ⏸ button it presses that button, which also toggles).
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || !track || e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
    const target = e.target;
    const control = "input, textarea, select, button, a, summary, [role=button]";
    const ownSlider = target === seek || target === volume;
    if (!ownSlider && (target.isContentEditable || target.closest(control))) return;
    e.preventDefault(); // no page scroll
    audio.paused ? audio.play() : audio.pause();
  });
  // A new page was swapped in: mark the playing track's ▶ button on it again.
  document.addEventListener("htmx:afterSettle", () => show(!audio.paused && !!track));
  audio.addEventListener("play", () => show(true));
  audio.addEventListener("pause", () => show(false));
  audio.addEventListener("ended", () => show(false));
  audio.addEventListener("timeupdate", () => {
    if (!track) return; // stopped
    const total = duration();
    if (!dragging && total) seek.value = String((position() / total) * 1000);
    time.textContent = `${clock(position())} / ${clock(total)}`;
  });
  seek.addEventListener("input", () => {
    dragging = true;
    time.textContent = `${clock((seek.value / 1000) * duration())} / ${clock(duration())}`;
  });
  seek.addEventListener("change", () => {
    dragging = false;
    const target = (seek.value / 1000) * duration();
    if (converted) load(target);
    else audio.currentTime = target;
  });
})();
