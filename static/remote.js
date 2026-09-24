const guide = document.querySelector("#guide");
const feedback = document.querySelector("#feedback");
const clock = document.querySelector("#clock");

const REFRESH_MS = 60_000;
const PIXELS_PER_MINUTE = 3;
const PAST_MINUTES = 30;

let timelineStart = null;
let timelineEnd = null;
let lastTunedChannelId = null;
let loading = false;

function parseTime(value) {
  return new Date(value).getTime();
}

function formatTime(value) {
  return new Intl.DateTimeFormat("es-MX", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function setFeedback(message, state = "") {
  feedback.textContent = message;
  feedback.className = `feedback${state ? ` is-${state}` : ""}`;
}

function updateClock() {
  clock.textContent = formatTime(Date.now());
}

function makeProgram(item, now) {
  const start = parseTime(item.start_time);
  const end = parseTime(item.end_time);
  const block = document.createElement("div");
  block.className = `program${start <= now && now < end ? " is-current" : ""}`;
  block.dataset.start = start;
  block.dataset.end = end;
  block.style.left = `${((start - timelineStart) / 60_000) * PIXELS_PER_MINUTE}px`;
  block.style.width = `${Math.max(2, ((end - start) / 60_000) * PIXELS_PER_MINUTE - 3)}px`;

  const title = document.createElement("strong");
  title.textContent = item.item_name;
  const time = document.createElement("span");
  time.className = "program-time";
  time.textContent = `${formatTime(start)}–${formatTime(end)}`;
  block.append(title, time);
  return block;
}

function makeChannelLabel(channel) {
  const label = document.createElement("div");
  label.className = "channel-label";

  const channelName = document.createElement("div");
  channelName.className = "channel-name";
  channelName.textContent = channel.name;

  const media = document.createElement("div");
  media.className = "current-thumb-wrap";
  const badge = document.createElement("span");
  badge.className = "now-badge";
  badge.textContent = "AL AIRE";

  if (channel.current?.thumb_url) {
    const image = document.createElement("img");
    image.className = "current-thumb";
    image.src = channel.current.thumb_url;
    image.alt = `Miniatura de ${channel.current.item_name}`;
    image.loading = "lazy";
    image.addEventListener("error", () => {
      image.remove();
      const placeholder = document.createElement("span");
      placeholder.className = "current-thumb-placeholder";
      placeholder.textContent = "Sin miniatura";
      media.prepend(placeholder);
    }, { once: true });
    media.append(image);
  } else {
    const placeholder = document.createElement("span");
    placeholder.className = "current-thumb-placeholder";
    placeholder.textContent = "Sin miniatura";
    media.append(placeholder);
  }
  media.append(badge);

  const title = document.createElement("div");
  title.className = "current-title";
  title.textContent = channel.current?.item_name || "Canal sin emisión actual";

  const plot = document.createElement("p");
  plot.className = "current-plot";
  plot.textContent = channel.current?.plot || "Sin descripción disponible.";

  label.append(channelName, media, title, plot);
  return label;
}

function renderGuide(channels) {
  const allItems = channels.flatMap(({ schedule }) => schedule);
  if (!allItems.length) {
    guide.innerHTML = '<p class="fatal">No hay programación disponible.</p>';
    guide.setAttribute("aria-busy", "false");
    return;
  }

  const now = Date.now();
  const firstStart = Math.min(...allItems.map(item => parseTime(item.start_time)));
  timelineStart = Math.max(firstStart, now - PAST_MINUTES * 60_000);
  timelineStart = Math.floor(timelineStart / 1_800_000) * 1_800_000;
  timelineEnd = Math.max(...allItems.map(item => parseTime(item.end_time)));

  const durationMinutes = Math.max(30, (timelineEnd - timelineStart) / 60_000);
  const trackWidth = durationMinutes * PIXELS_PER_MINUTE;
  const inner = document.createElement("div");
  inner.className = "guide-inner";
  inner.style.width = `calc(${trackWidth}px + var(--label-width))`;

  const ruler = document.createElement("div");
  ruler.className = "time-ruler";
  ruler.append(document.createElement("div"));
  const rulerTrack = document.createElement("div");
  rulerTrack.className = "ruler-track";
  rulerTrack.style.width = `${trackWidth}px`;
  for (let tick = timelineStart; tick <= timelineEnd; tick += 1_800_000) {
    const label = document.createElement("span");
    label.className = "time-tick";
    label.style.left = `${((tick - timelineStart) / 60_000) * PIXELS_PER_MINUTE}px`;
    label.textContent = formatTime(tick);
    rulerTrack.append(label);
  }
  ruler.append(rulerTrack);
  inner.append(ruler);

  for (const channel of channels) {
    const row = document.createElement("div");
    row.className = `channel-row${channel.id === lastTunedChannelId ? " is-tuned" : ""}`;
    row.dataset.channelId = channel.id;
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-label", `Sintonizar ${channel.name} en TV11`);

    const label = makeChannelLabel(channel);
    const track = document.createElement("div");
    track.className = "program-track";
    track.style.width = `${trackWidth}px`;

    if (channel.schedule.length) {
      for (const item of channel.schedule) track.append(makeProgram(item, now));
    } else {
      const empty = document.createElement("div");
      empty.className = "empty-track";
      empty.textContent = "Sin programación";
      track.append(empty);
    }

    row.append(label, track);
    row.addEventListener("click", () => tuneChannel(channel));
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        tuneChannel(channel);
      }
    });
    inner.append(row);
  }

  const nowLine = document.createElement("div");
  nowLine.id = "now-line";
  nowLine.className = "now-line";
  inner.append(nowLine);
  guide.replaceChildren(inner);
  guide.setAttribute("aria-busy", "false");
  updateNowLine();
}

function updateNowLine() {
  const line = document.querySelector("#now-line");
  if (!line || timelineStart === null) return;
  const position = ((Date.now() - timelineStart) / 60_000) * PIXELS_PER_MINUTE;
  line.style.left = `calc(var(--label-width) + ${position}px)`;
  line.hidden = Date.now() < timelineStart || Date.now() > timelineEnd;

  const now = Date.now();
  document.querySelectorAll(".program").forEach(block => {
    block.classList.toggle(
      "is-current",
      Number(block.dataset.start) <= now && now < Number(block.dataset.end),
    );
  });
}

async function tuneChannel(channel) {
  if (loading) return;
  loading = true;
  setFeedback(`Sintonizando ${channel.name} en TV11…`, "busy");
  try {
    const response = await fetch(`/api/remote/tune/${channel.id}`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No fue posible sintonizar TV11");
    lastTunedChannelId = channel.id;
    document.querySelectorAll(".channel-row").forEach(row => {
      row.classList.toggle("is-tuned", Number(row.dataset.channelId) === channel.id);
    });
    setFeedback(
      `${channel.name}: ${payload.item_name} desde ${Math.round(payload.offset_seconds)} s.`,
      "success",
    );
  } catch (error) {
    setFeedback(error.message, "error");
  } finally {
    loading = false;
  }
}

async function loadGuide() {
  try {
    const channelsResponse = await fetch("/api/channels");
    if (!channelsResponse.ok) throw new Error("No se pudieron cargar los canales");
    const channels = await channelsResponse.json();
    const enriched = await Promise.all(channels.map(async channel => {
      const [scheduleResponse, currentResponse] = await Promise.all([
        fetch(`/api/channels/${channel.id}/schedule`),
        fetch(`/api/remote/channels/${channel.id}/current`),
      ]);
      if (!scheduleResponse.ok) throw new Error(`No se pudo cargar ${channel.name}`);
      const current = currentResponse.ok ? await currentResponse.json() : null;
      return { ...channel, schedule: await scheduleResponse.json(), current };
    }));
    renderGuide(enriched);
  } catch (error) {
    const message = document.createElement("p");
    message.className = "fatal";
    message.textContent = error.message;
    guide.replaceChildren(message);
    guide.setAttribute("aria-busy", "false");
  }
}

guide.innerHTML = '<p class="loading">Cargando programación…</p>';
updateClock();
loadGuide();
setInterval(updateClock, 1_000);
setInterval(updateNowLine, 1_000);
setInterval(loadGuide, REFRESH_MS);
