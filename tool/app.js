"use strict";
/* Ring annotator (static page; reads and writes a batch folder the user picks).
   Classes, buttons, keys and the reference gallery all come from batch.json. */
const TOOL_VERSION = "v1.0";
const FORMAT = 1;
const AUTOSAVE_NOTE_MS = 500;
const FIXED = [   // answers that are the same in every batch
  { id: "not_ring", label: "Not a ring", key: "0" },
  { id: "ring_unknown", label: "Ring, can't tell which", key: "r" },
  { id: "unsure", label: "Can't tell if it is a ring", key: "x" },
];
const $ = id => document.getElementById(id);

let root = null, batch = null, ANS = [];       // folder handle, batch.json, answer list: [{id,label,key,description}]
let items = [], answers = {}, pos = 0, annotator = "", annFile = "";
let undoStack = [], drafts = {};               // drafts: notes typed on items not yet answered
let saveErr = null, lastSaved = null, saveChain = Promise.resolve(), noteTimer = null, dirty = false;
let urls = [];

// ---- helpers -----------------------------------------------------------------------------------
const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sanitize = n => String(n).trim().replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._]+/, "").slice(0, 40);
async function fileAt(path) {
  const parts = String(path || "").split("/").filter(p => p && p !== ".");
  if (!parts.length || parts.includes("..")) return null;
  try {
    let d = root; for (const p of parts.slice(0, -1)) d = await d.getDirectoryHandle(p);
    return await (await d.getFileHandle(parts[parts.length - 1])).getFile();
  } catch (e) { return null; }
}
async function jget(path) { const f = await fileAt(path); if (!f) return null; try { return JSON.parse(await f.text()); } catch (e) { return null; } }
async function listDir(h) { const out = []; for await (const [name, ent] of h.entries()) out.push([name, ent.kind]); return out; }

// Answer list from batch.json: classes in batch order get 1..9, then letters (skipping those used by fixed answers and the page).
function buildAnswers(classes) {
  const spare = "abcdefhijklmnopqstuvwyz".split("");     // not g (gallery), r, x (fixed)
  const out = classes.map((c, i) => ({ id: c.id, label: c.label || c.id, description: c.description || "", reference: c.reference || [],
    key: i < 9 ? String(i + 1) : (spare[i - 9] || "") }));
  return out.concat(FIXED.map(f => ({ ...f, description: "", reference: [] })));
}

// ---- loading and report ------------------------------------------------------------------------
async function scanFolder(h) {
  root = h; const R = { name: h.name, top: await listDir(h) };
  if (!R.top.some(t => t[0] === "batch.json")) { R.notBatch = true; return R; }
  const b = await jget("batch.json");
  if (!b || !Array.isArray(b.items) || !Array.isArray(b.classes)) { R.badJson = true; return R; }
  R.b = b; R.problems = [];
  if (b.format !== FORMAT) R.problems.push(`batch.json has format ${esc(b.format)}; this page reads format ${FORMAT}`);
  const ids = new Set(), res = new Set(FIXED.map(f => f.id));
  for (const c of b.classes) {
    if (!c || typeof c.id !== "string" || !c.id) R.problems.push("a class has no id");
    else if (res.has(c.id)) R.problems.push(`class id "${esc(c.id)}" is used twice or reserved`);
    else res.add(c.id);
  }
  for (const it of b.items) {
    if (!it || typeof it.item_id !== "string" || !it.item_id) R.problems.push("an item has no item_id");
    else if (ids.has(it.item_id)) R.problems.push(`item_id "${esc(it.item_id)}" is used twice`);
    else ids.add(it.item_id);
  }
  R.missing = { patch: [], context: [], reference: [] };
  for (const it of b.items) {
    if (!await fileAt(it.patch)) R.missing.patch.push(it.patch || it.item_id);
    if (!await fileAt(it.context)) R.missing.context.push(it.context || it.item_id);
  }
  for (const c of b.classes) for (const r of (c.reference || [])) if (!await fileAt(r)) R.missing.reference.push(r);
  R.ann = [];
  try {
    for (const [name, kind] of await listDir(await h.getDirectoryHandle("annotations"))) {
      if (kind !== "file" || !name.endsWith(".json")) continue;       // .json.bak is ignored
      const a = await jget("annotations/" + name); if (!a) { R.ann.push({ file: name, bad: true }); continue; }
      const n = Object.keys(a.answers || {}).filter(k => ids.has(k)).length;
      R.ann.push({ file: name, annotator: a.annotator, n, batch_id: a.batch_id });
    }
  } catch (e) { /* no annotations folder yet */ }
  return R;
}
function missList(l) { return l.length ? `<span class="bad">${l.length} missing: ${esc(l.slice(0, 12).join(", "))}${l.length > 12 ? " ... (" + l.length + " in all)" : ""}</span>` : "none"; }
function renderReport(R) {
  const rep = $("ld-report"); rep.style.display = ""; $("ld-pick").style.display = "none";
  const again = '<button id="ld-again">Choose a different folder</button>';
  if (R.notBatch || R.badJson) {
    const list = R.top.length ? R.top.map(t => esc(t[0]) + (t[1] === "directory" ? "/" : "")).join(", ") : "(nothing)";
    rep.innerHTML = `<div class="ldmsg bad">${R.notBatch ? "This is not a batch folder (there is no batch.json in it)." : "batch.json in this folder could not be read."}</div>
      <p>Folder "${esc(R.name)}" contains: ${list}</p><div class="btns">${again}</div>`;
    $("ld-again").onclick = chooseFolder; return;
  }
  const b = R.b, N = b.items.length;
  const annRows = R.ann.length ? R.ann.map(a => a.bad ? `${esc(a.file)}: unreadable` : `${esc(a.file)}: ${a.n} of ${N} answered${a.batch_id !== b.batch_id ? ' <span class="bad">(different batch_id: ' + esc(a.batch_id) + ")</span>" : ""}`).join("<br>") : "none";
  rep.innerHTML = `<table>
    <tr><td>Batch</td><td>${esc(b.title || b.batch_id)} <small>(${esc(b.batch_id)})</small></td></tr>
    <tr><td>Instruction</td><td>${esc(b.instruction || "")}</td></tr>
    <tr><td>Items</td><td>${N}</td></tr>
    <tr><td>Classes</td><td>${b.classes.length}: ${esc(b.classes.map(c => c.label || c.id).join(", "))}</td></tr>
    <tr><td>Missing patch files</td><td>${missList(R.missing.patch)}</td></tr>
    <tr><td>Missing context files</td><td>${missList(R.missing.context)}</td></tr>
    <tr><td>Missing reference files</td><td>${missList(R.missing.reference)}</td></tr>
    <tr><td>Annotation files found</td><td id="ld-ann">${annRows}</td></tr></table>
    ${R.problems.length ? '<div class="ldmsg bad" id="ld-problems">Cannot start: ' + R.problems.join("; ") + "</div>" : ""}
    <div class="btns"><label>Your name: <input type="text" id="ld-name" size="22"></label>
      <button id="ld-start" disabled>Start</button>${again}</div>
    <div id="ld-nameinfo" class="ldmsg"></div>`;
  $("ld-again").onclick = chooseFolder;
  const upd = () => {
    const s = sanitize($("ld-name").value), ex = s && R.ann.find(a => a.file === s + ".json");
    $("ld-nameinfo").innerHTML = !s ? "Type your name to start." : `File: annotations/${esc(s)}.json` + (ex ? (ex.n !== undefined ? ` (exists: ${ex.n} answered, you will resume)` : " (exists but unreadable)") : " (new)");
    $("ld-start").disabled = !s || R.problems.length > 0 || !!(ex && ex.bad) || !!(ex && ex.batch_id !== b.batch_id);
  };
  $("ld-name").oninput = upd; upd();
  $("ld-start").onclick = () => startBatch(R, $("ld-name").value.trim());
}
async function chooseFolder() {
  let h; try { h = await window.showDirectoryPicker({ mode: "readwrite" }); } catch (e) { return; }   // cancelled
  try { renderReport(await scanFolder(h)); } catch (e) { $("ld-report").style.display = ""; $("ld-report").innerHTML = '<div class="ldmsg bad">Could not read the folder: ' + esc(e) + '</div><div class="btns"><button id="ld-again">Choose a different folder</button></div>'; $("ld-again").onclick = chooseFolder; }
}
function init() {
  if (!window.showDirectoryPicker) {
    $("ld-pick").style.display = "none"; const u = $("ld-unsupported"); u.style.display = "";
    u.textContent = "This page needs a browser that can read and write a folder: use Chrome or Edge on a computer. Firefox and Safari do not support this.";
    return;
  }
  $("ld-choose").onclick = chooseFolder;
}

async function startBatch(R, name) {
  batch = R.b; items = batch.items; ANS = buildAnswers(batch.classes);
  annotator = name; annFile = "annotations/" + sanitize(name) + ".json";
  answers = {}; drafts = {}; undoStack = [];
  const saved = await jget(annFile);
  if (saved && saved.answers && saved.batch_id === batch.batch_id) answers = saved.answers;
  const valid = new Set(ANS.map(a => a.id));
  for (const k of Object.keys(answers)) if (!answers[k] || !valid.has(answers[k].answer)) delete answers[k];
  pos = firstUnanswered(); if (pos < 0) pos = 0;
  $("loader").style.display = "none";
  $("h-batch").textContent = "batch: " + (batch.title || batch.batch_id); $("h-who").textContent = "annotator: " + annotator;
  buildButtons(); buildStrip(); show(); setState();
}
const firstUnanswered = () => items.findIndex(it => !answers[it.item_id]);
const nAnswered = () => items.filter(it => answers[it.item_id]).length;

// ---- screen ------------------------------------------------------------------------------------
function buildButtons() {
  const box = $("answers"); box.innerHTML = "";
  for (const a of ANS) {
    const b = document.createElement("button"); b.dataset.ans = a.id; b.title = a.description || "";
    b.innerHTML = `<b>${a.key ? esc(a.key.toUpperCase()) : "-"}</b>${esc(a.label)}`;
    b.onclick = () => { b.blur(); answer(a.id); }; box.appendChild(b);
  }
}
function buildStrip() {
  const s = $("strip"); s.innerHTML = "";
  items.forEach((it, i) => { const c = document.createElement("span"); c.textContent = i + 1; c.dataset.i = i; c.onclick = () => go(i); s.appendChild(c); });
}
function updateStrip() {
  [...$("strip").children].forEach((c, i) => { c.className = (answers[items[i].item_id] ? "ans " : "") + (i === pos ? "cur" : ""); c.title = items[i].item_id; });
}
async function setImg(kind, path) {
  const img = $("img-" + kind), m = $("miss-" + kind), f = await fileAt(path);
  if (!f) { img.style.display = "none"; img.removeAttribute("src"); m.style.display = ""; m.textContent = "image missing: " + path; return; }
  const u = URL.createObjectURL(f); urls.push(u); img.src = u; img.style.display = ""; m.style.display = "none";
}
let showSeq = 0;
function show() {
  const it = items[pos], e = answers[it.item_id], seq = ++showSeq;
  $("item-id").textContent = it.item_id;
  for (const b of $("answers").children) b.classList.toggle("sel", !!e && e.answer === b.dataset.ans);
  $("note").value = e ? (e.note || "") : (drafts[it.item_id] || "");
  $("h-prog").textContent = `item ${pos + 1} of ${items.length} | answered ${nAnswered()} of ${items.length}`;
  $("b-back").disabled = pos === 0; $("b-fwd").disabled = pos >= items.length - 1; $("b-undo").disabled = !undoStack.length;
  updateStrip();
  const old = urls; urls = [];
  Promise.all([setImg("patch", it.patch), setImg("context", it.context)]).then(() => { if (seq === showSeq) old.forEach(URL.revokeObjectURL); });
}
function go(i) { flushNote(); pos = Math.max(0, Math.min(items.length - 1, i)); show(); }

function answer(id) {
  if (!batch || galleryOpen()) return;
  flushNote();
  const it = items[pos], prev = answers[it.item_id], note = $("note").value;
  undoStack.push({ id: it.item_id, prev: prev ? { ...prev } : null, pos });
  answers[it.item_id] = { answer: id, note, answered_at: new Date().toISOString() };
  delete drafts[it.item_id];
  if (pos < items.length - 1) pos++;
  show(); save();
}
function undo() {
  if (!undoStack.length) return;
  flushNote();
  const u = undoStack.pop();
  if (u.prev) answers[u.id] = u.prev; else delete answers[u.id];
  pos = u.pos; show(); save();
}
function onNote() {
  const it = items[pos], e = answers[it.item_id];
  if (e) { e.note = $("note").value; clearTimeout(noteTimer); noteTimer = setTimeout(() => { noteTimer = null; save(); }, AUTOSAVE_NOTE_MS); setState("unsaved changes"); }
  else drafts[it.item_id] = $("note").value;          // kept in memory and written when the item is answered
}
function flushNote() { if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; save(); } }

// ---- saving ------------------------------------------------------------------------------------
function payload() {
  return { tool_version: TOOL_VERSION, format: FORMAT, batch_id: batch.batch_id, annotator, saved_at: new Date().toISOString(), answers };
}
function save() { dirty = true; setState(); const r = saveChain.then(doSave); saveChain = r.catch(() => {}); return r; }
async function doSave() {
  const p = payload(), file = annFile.split("/")[1];
  try {
    const dir = await root.getDirectoryHandle("annotations", { create: true });
    let old = null; try { old = await (await dir.getFileHandle(file)).getFile(); } catch (e) { /* first save */ }
    if (old) { const bk = await (await dir.getFileHandle(file + ".bak", { create: true })).createWritable(); await bk.write(await old.text()); await bk.close(); }
    const w = await (await dir.getFileHandle(file, { create: true })).createWritable(); await w.write(JSON.stringify(p, null, 1)); await w.close();
    saveErr = null; lastSaved = p.saved_at; dirty = !!noteTimer;
  } catch (e) { saveErr = "SAVE FAILED, your latest answer is NOT saved: " + (e && e.message || e); setState(); return false; }
  setState(); return true;
}
function setState(msg) {
  const el = $("h-state");
  if (saveErr) { el.textContent = saveErr; el.className = "state err"; return; }
  if (msg) { el.textContent = msg; el.className = "state unsaved"; return; }
  el.textContent = dirty ? "saving..." : (lastSaved ? "saved " + new Date(lastSaved).toLocaleTimeString() : "nothing saved yet");
  el.className = "state " + (dirty ? "unsaved" : lastSaved ? "saved" : "");
}
window.addEventListener("beforeunload", e => { if (dirty || noteTimer) { e.preventDefault(); e.returnValue = ""; } });

// ---- export ------------------------------------------------------------------------------------
function exportCsv() {
  flushNote();
  const q = v => { v = String(v === undefined || v === null ? "" : v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const rows = [["item_id", "answer", "note", "answered_at", "annotator", "batch_id"]];
  for (const it of items) { const e = answers[it.item_id]; if (e) rows.push([it.item_id, e.answer, e.note, e.answered_at, annotator, batch.batch_id]); }
  const blob = new Blob([rows.map(r => r.map(q).join(",")).join("\n") + "\n"], { type: "text/csv" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = `${batch.batch_id}_${sanitize(annotator)}.csv`; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// ---- reference gallery -------------------------------------------------------------------------
const galleryOpen = () => $("gallery").style.display !== "none";
async function openGallery() {
  const body = $("gbody"); body.innerHTML = ""; $("gallery").style.display = "";
  for (const a of ANS.filter(a => batch.classes.some(c => c.id === a.id))) {
    const d = document.createElement("div"); d.className = "gcls"; d.dataset.cls = a.id;
    d.innerHTML = `<h4><b>${a.key ? esc(a.key.toUpperCase()) : "-"}</b>${esc(a.label)}</h4><div class="desc">${esc(a.description)}</div>`;
    body.appendChild(d);
    for (const r of a.reference) {
      const f = await fileAt(r);
      if (!f) { const m = document.createElement("span"); m.className = "missing"; m.textContent = "missing: " + r; d.appendChild(m); continue; }
      const img = document.createElement("img"); const u = URL.createObjectURL(f); img.src = u; img.alt = r; d.appendChild(img);
    }
  }
}
function closeGallery() { $("gallery").style.display = "none"; $("gbody").innerHTML = ""; }

// ---- keys --------------------------------------------------------------------------------------
document.addEventListener("keydown", e => {
  if (!batch || $("loader").style.display !== "none") return;
  const tag = e.target && e.target.tagName;
  if (tag === "TEXTAREA" || tag === "INPUT") { if (e.key === "Escape") e.target.blur(); return; }   // typing never answers
  if (e.altKey || e.metaKey) return;
  const k = e.key.toLowerCase();
  if (galleryOpen()) { if (k === "escape" || k === "g") { closeGallery(); e.preventDefault(); } return; }
  if (e.ctrlKey) { if (k === "z") { undo(); e.preventDefault(); } return; }
  if (k === "g") { openGallery(); e.preventDefault(); return; }
  if (k === "arrowleft") { go(pos - 1); e.preventDefault(); return; }
  if (k === "arrowright") { go(pos + 1); e.preventDefault(); return; }
  const a = ANS.find(a => a.key && a.key === k);
  if (a) { answer(a.id); e.preventDefault(); }
});
$("note").addEventListener("input", onNote);
$("b-back").onclick = () => go(pos - 1); $("b-fwd").onclick = () => go(pos + 1);
$("b-undo").onclick = undo;
$("b-first").onclick = () => { const i = firstUnanswered(); go(i < 0 ? pos : i); };
$("b-ref").onclick = openGallery; $("b-gclose").onclick = closeGallery; $("b-export").onclick = exportCsv;
window.__dbg = () => ({ pos, answers: JSON.parse(JSON.stringify(answers)), undo: undoStack.length, keys: ANS.map(a => [a.id, a.key]), annFile, galleryOpen: galleryOpen() });
init();
