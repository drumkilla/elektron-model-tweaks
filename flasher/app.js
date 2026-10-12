/* model-tweaks web flasher.
 *
 * The firmware is built by elekloader's linker (its copy in elekloader/, GPL-2.0)
 * from the .elemod mods in mods/<device>/, run unchanged in Pyodide (flasher/web.py
 * is the glue). The page loads them from the repository
 * (flasher/files.json lists them), reads the user's .syx locally, and offers the
 * result as a download or sends it over Web MIDI. Nothing is uploaded anywhere.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const st = { py: null, web: null, input: null, out: null, outName: null, sending: false, stop: false };

// ----------------------------------------------------------------------------
// Engine: Pyodide + the repository's Python
// ----------------------------------------------------------------------------
// The repository's files, each fetched once (the mod list and the engine share them).
const fileList = fetch("files.json", { cache: "no-cache" }).then((r) => r.json());
const fetched = {};
function repoFile(rel) {
  return fetched[rel] = fetched[rel] || fetch("../" + rel, { cache: "no-cache" }).then((r) => {
    if (!r.ok) throw new Error(`could not load ${rel} (${r.status}). The page needs the whole repository: ` +
      "serve its root folder (e.g. python3 -m http.server in model-tweaks/) and open /flasher/");
    return r.arrayBuffer();
  });
}

async function loadEngine() {
  const files = await fileList;
  files.forEach(repoFile);                               // start the downloads while Pyodide loads
  const py = await loadPyodide();
  py.FS.mkdirTree("/app");
  await Promise.all(files.map(async (rel) => {
    const dst = "/app/" + (rel === "flasher/web.py" ? "web.py" : rel);
    py.FS.mkdirTree(dst.slice(0, dst.lastIndexOf("/")));
    py.FS.writeFile(dst, new Uint8Array(await repoFile(rel)));
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
  showBrowse();
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
  $("step-pick").classList.remove("browsing");
  $("browse").hidden = true;
  $("build").hidden = false;
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
// Step 2 before a firmware is loaded: every device's mods, to read about (no
// checkboxes, no build). The list is what web.py would offer: the .elemod files in
// files.json, without the hidden requirements, by title.
// ----------------------------------------------------------------------------
const HIDDEN = new Set(["core", "modkit"]);
const catalog = fileList.then((files) => Promise.all(
  files.filter((rel) => /^mods\/[^/]+\/[^/]+\.elemod$/.test(rel)).map(async (rel) => {
    const d = JSON.parse(new TextDecoder().decode(await repoFile(rel)));
    return { dev: rel.split("/")[1], id: d.id, name: d.title || d.id, version: d.version || "",
             description: [d.description || ""], links: [] };
  }))).then((mods) => {
  const byDev = {};
  for (const m of mods) if (!HIDDEN.has(m.id)) (byDev[m.dev] = byDev[m.dev] || []).push(m);
  for (const list of Object.values(byDev)) list.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  return byDev;
});
let browseDev = "model-samples";

async function showBrowse(dev) {
  if (dev) browseDev = dev;
  const step = $("step-pick");
  step.classList.add("browsing");
  $("browse").hidden = false;
  $("build").hidden = true;
  for (const b of document.querySelectorAll("#devices button")) b.setAttribute("aria-selected", b.dataset.dev === browseDev);
  let byDev;
  try {
    byDev = await catalog;
  } catch (e) {
    $("tweaks").textContent = "Could not load the list of mods: " + e.message;
    return;
  }
  if (!step.classList.contains("browsing")) return;      // a firmware was loaded meanwhile
  showTweaks(byDev[browseDev] || []);
}

// ----------------------------------------------------------------------------
// Step 2: pick mods, build
// ----------------------------------------------------------------------------
function showTweaks(tweaks) {
  const box = $("tweaks");
  box.innerHTML = "";
  for (const t of tweaks) {
    // The checkbox toggles the mod; a click anywhere else on the card shows its details.
    const card = document.createElement("div");
    card.className = "tweak";
    card.tabIndex = 0;
    card.dataset.id = t.id;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.value = t.id;
    cb.setAttribute("aria-label", "Include " + t.name);
    cb.addEventListener("click", (e) => e.stopPropagation());
    card.addEventListener("click", () => showDetails(t, card));
    card.addEventListener("keydown", (e) => {
      if (e.target === card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); showDetails(t, card); }
    });
    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "tweak-name";
    title.textContent = t.name;
    if (t.version) {                     // the mod's version: smaller, not the accent
      const ver = document.createElement("span");
      ver.className = "tweak-version";
      ver.textContent = t.version;
      title.append(" ", ver);
    }
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
  resetDetails();
  setStatus("build-status", "");
  $("step-pick").hidden = false;
}

// ----------------------------------------------------------------------------
// A mod's details: docs/mods/<id>.md (written for the page, with screenshots and
// animations of the device in docs/mods/media/), in the panel beside the list, or under
// the card on a narrow screen. Markdown: # / ## / ### headings, paragraphs, "- " lists,
// ![caption](media/x.png) images (a line of their own), **bold**, `code`, [links](...).
// ----------------------------------------------------------------------------
const DOCS = "../docs/mods/";
const docCache = {};

function resetDetails() {
  const d = $("details");
  d.innerHTML = '<p class="hint">Click a mod to see what it does, with pictures of the screen.</p>';
  $("details-col").appendChild(d);
  for (const c of document.querySelectorAll(".tweak.selected")) c.classList.remove("selected");
}

function renderDoc(md) {
  const out = [];
  let list = null, para = null;
  const flush = () => {
    if (para) out.push("<p>" + inline(para.join(" ")) + "</p>");
    if (list) out.push("<ul>" + list.map((li) => "<li>" + inline(li) + "</li>").join("") + "</ul>");
    para = list = null;
  };
  for (const raw of md.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) {
      flush();
      const n = Math.min(m[1].length + 2, 5);           // # -> h3, ## -> h4, ### -> h5
      out.push("<h" + n + ">" + inline(m[2]) + "</h" + n + ">");
    } else if ((m = line.match(/^!\[(.*?)\]\(([^)\s]+)\)$/))) {
      flush();
      const src = /^https?:/.test(m[2]) ? m[2] : DOCS + m[2];
      out.push('<figure><img src="' + src.replace(/"/g, "&quot;") + '" alt="" loading="lazy">' +
               (m[1] ? "<figcaption>" + inline(m[1]) + "</figcaption>" : "") + "</figure>");
    } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
      if (para) flush();
      (list = list || []).push(m[1]);
    } else if (list && /^\s{2,}\S/.test(raw)) {
      list[list.length - 1] += " " + line.trim();      // a list item's continuation
    } else {
      if (list) flush();
      (para = para || []).push(line.trim());
    }
  }
  flush();
  return out.join("");
}

async function showDetails(t, card) {
  for (const c of document.querySelectorAll(".tweak.selected")) c.classList.remove("selected");
  card.classList.add("selected");
  const d = $("details");
  if (window.matchMedia("(max-width: 900px)").matches) card.after(d);   // under the card
  else $("details-col").appendChild(d);
  d.dataset.id = t.id;
  let html = docCache[t.id];
  if (html === undefined) {
    d.innerHTML = '<p class="hint">Loading…</p>';
    try {
      const r = await fetch(DOCS + t.id + ".md", { cache: "no-cache" });
      html = r.ok ? renderDoc(await r.text()) : null;
    } catch (e) {
      html = null;
    }
    docCache[t.id] = html;
  }
  if (d.dataset.id !== t.id) return;                     // another one was picked meanwhile
  d.innerHTML = html || ("<h3>" + inline(t.name) + "</h3><p>" + inline(t.description.join(" ")) + "</p>");
  if (!window.matchMedia("(max-width: 900px)").matches) d.scrollTop = 0;
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
  setStatus("build-status", "Built: " + ids.length + " mod(s); linked with what they need: " + res.mods.join(", ") + ".", "ok");
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
// The version and the changelog: CHANGELOG.md, in the format it keeps
// ("## <version> — <date>", "- " items continued by indented lines, paragraphs,
// **bold** and `code`). The newest entry is open, the older ones folded.
// ----------------------------------------------------------------------------
function inline(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>")
            .replace(/\[(.+?)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function parseChangelog(md) {
  const entries = [];
  let cur = null, item = null, para = null;
  const flush = () => {
    if (item) cur.blocks.push({ li: item.join(" ") });
    if (para) cur.blocks.push({ p: para.join(" ") });
    item = para = null;
  };
  for (const line of md.split("\n")) {
    const h = line.match(/^## (\S+)\s*[—-]\s*(.+)$/);
    if (h) { if (cur) flush(); cur = { version: h[1], date: h[2].trim(), blocks: [] }; entries.push(cur); continue; }
    if (!cur) continue;                                   // the intro above the first entry
    if (/^- /.test(line)) { flush(); item = [line.slice(2).trim()]; continue; }
    if (/^\s+\S/.test(line) && item) { item.push(line.trim()); continue; }
    if (!line.trim()) { flush(); continue; }
    if (item) flush();
    (para = para || []).push(line.trim());
  }
  if (cur) flush();
  return entries;
}

async function loadChangelog() {
  try {
    const r = await fetch("../CHANGELOG.md", { cache: "no-cache" });
    if (!r.ok) return;
    const entries = parseChangelog(await r.text());
    if (!entries.length) return;
    $("version").textContent = " · v" + entries[0].version;
    $("changelog-body").innerHTML = entries.map((e, i) => {
      let html = "", list = false;
      for (const b of e.blocks) {
        if (b.li !== undefined && !list) { html += "<ul>"; list = true; }
        if (b.li === undefined && list) { html += "</ul>"; list = false; }
        html += b.li !== undefined ? "<li>" + inline(b.li) + "</li>" : "<p>" + inline(b.p) + "</p>";
      }
      if (list) html += "</ul>";
      return `<details${i === 0 ? " open" : ""}><summary><b>${inline(e.version)}</b> <span>${inline(e.date)}</span>` +
             `</summary>${html}</details>`;
    }).join("");
    $("changelog").hidden = false;
  } catch (e) { /* the page works without it */ }
}
loadChangelog();

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
for (const b of document.querySelectorAll("#devices button")) b.addEventListener("click", () => showBrowse(b.dataset.dev));
showBrowse();
$("download").addEventListener("click", download);
$("midi-connect").addEventListener("click", connectMidi);
$("send").addEventListener("click", send);
$("stop").addEventListener("click", () => { st.stop = true; });
window.addEventListener("beforeunload", (e) => { if (st.sending) e.preventDefault(); });
