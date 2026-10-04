/* model-tweaks web flasher.
 *
 * The firmware is built by the repository's own tweak.py and mtlib, run unchanged
 * in Pyodide (flasher/web.py is the glue). The page loads them from the repository
 * (flasher/files.json lists them), reads the user's .syx locally, and offers the
 * result as a download or sends it over Web MIDI. Nothing is uploaded anywhere.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const st = { py: null, web: null, input: null, out: null, outName: null, sending: false, stop: false };

// ----------------------------------------------------------------------------
// Engine: Pyodide + the repository's Python
// ----------------------------------------------------------------------------
async function loadEngine() {
  const py = await loadPyodide();
  const files = await (await fetch("files.json", { cache: "no-cache" })).json();
  py.FS.mkdirTree("/app");
  await Promise.all(files.map(async (rel) => {
    const r = await fetch("../" + rel, { cache: "no-cache" });
    if (!r.ok) throw new Error(`could not load ${rel} (${r.status}). The page needs the whole repository: ` +
      "serve its root folder (e.g. python3 -m http.server in model-tweaks/) and open /flasher/");
    const dst = "/app/" + (rel === "flasher/web.py" ? "web.py" : rel);
    py.FS.mkdirTree(dst.slice(0, dst.lastIndexOf("/")));
    py.FS.writeFile(dst, new Uint8Array(await r.arrayBuffer()));
  }));
  py.runPython("import sys; sys.path.insert(0, '/app')");
  st.py = py;
  st.web = py.pyimport("web");
}

const engineReady = loadEngine().then(
  () => setStatus("engine", "Ready.", "ok"),
  (e) => setStatus("engine", "Could not load the engine: " + e.message, "bad"),
);

function setStatus(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}

const paint = () => new Promise((r) => setTimeout(r, 30));   // let the page redraw before a long call

// ----------------------------------------------------------------------------
// Step 1: the user's firmware
// ----------------------------------------------------------------------------
async function takeFile(file) {
  if (!file) return;
  $("step-pick").hidden = true;
  $("step-get").hidden = true;
  $("fwinfo").hidden = true;
  setStatus("engine", "Reading " + file.name + "…");
  await engineReady;
  if (!st.web) return;
  await paint();
  const data = new Uint8Array(await file.arrayBuffer());
  let info;
  try {
    info = JSON.parse(st.web.inspect(data, file.name));
  } catch (e) {
    setStatus("engine", "Could not read the file: " + e.message, "bad");
    return;
  }
  if (!info.ok) {
    setStatus("engine", (info.device ? info.device + ": " : "") + info.error, "bad");
    return;
  }
  st.input = file.name;
  setStatus("engine", "");
  const fi = $("fwinfo");
  fi.innerHTML = "";
  const dl = document.createElement("dl");
  addRow(dl, "File", file.name);
  addRow(dl, "Firmware", info.device + " OS " + info.os);
  addRow(dl, "SHA-256", info.sha256);
  addRow(dl, "", info.exact ? "matches the known original"
    : "the MAIN OS matches the original, the file itself does not; normal if it was repacked");
  fi.appendChild(dl);
  fi.hidden = false;
  showTweaks(info.tweaks);
}

function addRow(dl, k, v) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = k;
  dd.textContent = v;
  dl.append(dt, dd);
}

// ----------------------------------------------------------------------------
// Step 2: pick tweaks, build
// ----------------------------------------------------------------------------
function showTweaks(tweaks) {
  const box = $("tweaks");
  box.innerHTML = "";
  for (const t of tweaks) {
    // The whole card is the label, so clicking anywhere toggles it.
    const card = document.createElement("label");
    card.className = "tweak";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.value = t.id;
    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "tweak-name";
    title.textContent = t.name;
    const ul = document.createElement("ul");
    for (const line of t.description) {
      const li = document.createElement("li");
      // "  A16  text": an indented line is a term + explanation (e.g. the USB modes)
      const m = /^\s+(\S+)\s{2,}(.*)$/.exec(line);
      if (m) {
        li.className = "term";
        const b = document.createElement("b");
        b.textContent = m[1];
        const span = document.createElement("span");
        span.textContent = m[2];
        li.append(b, span);
      } else {
        li.textContent = line;
      }
      ul.appendChild(li);
    }
    body.append(title, ul);
    if (t.links && t.links.length) {
      const links = document.createElement("div");
      links.className = "tweak-links";
      for (const l of t.links) {
        const a = document.createElement("a");
        a.href = l.url;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = l.label;
        a.addEventListener("click", (e) => e.stopPropagation());   // follow the link, keep the checkbox
        links.appendChild(a);
      }
      body.appendChild(links);
    }
    card.append(cb, body);
    box.appendChild(card);
  }
  setStatus("build-status", "");
  $("step-pick").hidden = false;
}

async function build() {
  const ids = [...document.querySelectorAll("#tweaks input:checked")].map((c) => c.value);
  if (!ids.length) {
    setStatus("build-status", "Nothing selected.", "bad");
    return;
  }
  $("build").disabled = true;
  $("step-get").hidden = true;
  setStatus("build-status", "Building and verifying… (a few seconds)");
  await paint();
  let res;
  try {
    res = JSON.parse(st.web.build(JSON.stringify(ids)));
  } catch (e) {
    res = { ok: false, error: e.message };
  }
  $("build").disabled = false;
  if (!res.ok) {
    setStatus("build-status", res.error, "bad");
    return;
  }
  st.out = st.py.FS.readFile("/tmp/out.syx");
  st.outName = res.name;
  setStatus("build-status", "Built: " + ids.length + " tweak(s), " + res.changed + " MAIN OS bytes changed.", "ok");
  const r = $("result");
  r.innerHTML = "";
  const dl = document.createElement("dl");
  addRow(dl, "File", res.name + " (" + res.size + " bytes)");
  addRow(dl, "SHA-256", res.sha256);
  addRow(dl, "Checks", "all passed");
  r.appendChild(dl);
  const pre = document.createElement("pre");
  pre.className = "checks";
  pre.textContent = res.checks.join("\n");
  r.appendChild(pre);
  $("step-get").hidden = false;
  $("step-get").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ----------------------------------------------------------------------------
// Step 3: download, or send over Web MIDI
// ----------------------------------------------------------------------------
function download() {
  const url = URL.createObjectURL(new Blob([st.out], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = st.outName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/* Split a .syx into its F0..F7 messages. */
function splitMessages(raw) {
  const msgs = [];
  let start = -1;
  for (let i = 0; i < raw.length; i++) {
    if (raw[i] === 0xf0) start = i;
    else if (raw[i] === 0xf7 && start >= 0) {
      msgs.push(raw.subarray(start, i + 1));
      start = -1;
    }
  }
  return msgs;
}

const DIN_BYTES_PER_SEC = 31250 / 10;   // a MIDI cable, 8N1

let midiAccess = null;
async function connectMidi() {
  if (!navigator.requestMIDIAccess) {
    setStatus("send-status", "This browser has no Web MIDI. Use Chrome or Edge, or download the file.", "bad");
    return;
  }
  try {
    midiAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch (e) {
    setStatus("send-status", "MIDI access was refused: " + e.message, "bad");
    return;
  }
  const sel = $("midi-port");
  sel.innerHTML = "";
  for (const out of midiAccess.outputs.values()) {
    const o = document.createElement("option");
    o.value = out.id;
    o.textContent = out.name;
    if (/model/i.test(out.name)) o.selected = true;
    sel.appendChild(o);
  }
  sel.hidden = !sel.options.length;
  $("send").disabled = !sel.options.length;
  setStatus("send-status", sel.options.length ? "" : "No MIDI outputs found. Is the device connected over USB?",
            sel.options.length ? "" : "bad");
}

async function send() {
  const out = midiAccess && midiAccess.outputs.get($("midi-port").value);
  if (!out || !st.out) return;
  const pace = Math.max(1, parseFloat($("pace").value) || 1.4);
  const msgs = splitMessages(st.out);
  st.sending = true;
  st.stop = false;
  $("send").disabled = true;
  $("stop").hidden = false;
  $("progress").hidden = false;
  $("progress").max = msgs.length;
  const minutes = Math.ceil(st.out.length / DIN_BYTES_PER_SEC * pace / 60);
  setStatus("send-status", "Sending " + msgs.length + " messages, about " + minutes + " min…");
  let n = 0;
  for (; n < msgs.length && !st.stop; n++) {
    out.send(msgs[n]);
    await new Promise((r) => setTimeout(r, pace * msgs[n].length / DIN_BYTES_PER_SEC * 1000));
    if (n % 20 === 0) $("progress").value = n;
  }
  $("progress").value = n;
  st.sending = false;
  $("send").disabled = false;
  $("stop").hidden = true;
  if (n < msgs.length) setStatus("send-status", "Stopped after " + n + " of " + msgs.length + " messages.", "bad");
  else setStatus("send-status", "Sent. Follow the device's screen until it restarts.", "ok");
}

// ----------------------------------------------------------------------------
$("file").addEventListener("change", (e) => takeFile(e.target.files[0]));
const drop = $("drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  takeFile(e.dataTransfer.files[0]);
});
$("build").addEventListener("click", build);
$("download").addEventListener("click", download);
$("midi-connect").addEventListener("click", connectMidi);
$("send").addEventListener("click", send);
$("stop").addEventListener("click", () => { st.stop = true; });
window.addEventListener("beforeunload", (e) => { if (st.sending) e.preventDefault(); });
