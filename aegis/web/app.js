// Aegis control-panel front-end. Vanilla JS, no build step.

const $ = (id) => document.getElementById(id);

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

async function loadLabels() {
  try {
    const { labels } = await (await fetch("/api/labels")).json();
    const dl = $("labels");
    dl.innerHTML = "";
    (labels || []).forEach((l) => {
      const opt = document.createElement("option");
      opt.value = l;
      dl.appendChild(opt);
    });
  } catch (e) {
    /* labels are a convenience; ignore failures */
  }
}

function setBanner(armed) {
  const b = $("banner");
  b.textContent = armed ? "ENGAGED" : "STANDBY";
  b.className = "banner " + (armed ? "engaged" : "standby");
}

function renderJoints(joints) {
  const el = $("joints");
  const keys = Object.keys(joints || {});
  if (!keys.length) {
    el.textContent = "—";
    return;
  }
  el.innerHTML = keys
    .map((k) => `<span class="chip">${k}: ${joints[k]}</span>`)
    .join("");
}

function renderDetections(dets, target) {
  const el = $("detections");
  if (!dets || !dets.length) {
    el.textContent = "nothing detected";
    return;
  }
  const t = (target || "").toLowerCase();
  el.innerHTML = dets
    .map((d) => {
      const isTarget = t && (d.label.includes(t) || t.includes(d.label));
      return `<span class="chip ${isTarget ? "target" : ""}">${d.label} ${d.confidence}</span>`;
    })
    .join("");
}

async function poll() {
  try {
    const s = await (await fetch("/api/status")).json();
    setBanner(!!s.armed);
    $("message").textContent = s.message || "";
    $("st-state").textContent = s.running
      ? s.armed
        ? "engaged"
        : "standby"
      : "starting";
    $("st-target").textContent = s.target || "—";
    $("st-visible").textContent = s.target_visible ? "yes" : "no";
    $("st-conf").textContent =
      s.target_confidence != null ? s.target_confidence : "—";
    $("st-error").textContent =
      s.error_x != null ? `${s.error_x} / ${s.error_y}` : "—";
    $("st-fps").textContent = s.fps != null ? s.fps : "—";
    renderJoints(s.joints);
    renderDetections(s.detections, s.target);
  } catch (e) {
    $("message").textContent = "connection lost…";
  }
}

$("set-target").addEventListener("click", async () => {
  const target = $("target").value.trim();
  if (!target) return;
  await postJSON("/api/target", { target });
  $("message").textContent = `target set: ${target}`;
});

$("target").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("set-target").click();
});

$("engage").addEventListener("click", async () => {
  const target = $("target").value.trim();
  if (target) await postJSON("/api/target", { target });
  await postJSON("/api/engage");
});

$("stop").addEventListener("click", async () => {
  await postJSON("/api/stop");
});

loadLabels();
setInterval(poll, 500);
poll();
