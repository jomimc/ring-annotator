"""Click-through test of the ring annotator with Playwright (real mouse and keyboard events).

Run from anywhere:  python3 tests/click_through.py
Needs: playwright (python) with a Chromium, and Pillow (to draw the synthetic jpgs).
The native folder dialog cannot be driven, so window.showDirectoryPicker is replaced by a function that
returns a folder of the browser's private file system (OPFS), filled with a made-up batch generated here.
The made-up batches are written to temp/ (git-ignored) and removed again at the end.
"""
import functools, glob, http.server, json, os, shutil, socketserver, sys, threading
from pathlib import Path
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
TEMP = REPO / "temp"
CHROME = os.environ.get("CHROME") or next(iter(sorted(
    glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium*/chrome-linux*/chrome")) +
    glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell*/chrome-linux*/headless_shell")))), None)

results = []
def ck(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)), flush=True)

# ---- made-up batches ---------------------------------------------------------------------------
def jpg(path, text, colour, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, colour); d = ImageDraw.Draw(im); d.text((4, 4), text, fill=(255, 255, 255))
    im.save(path, "JPEG")

def make_batch(name, n_items, n_classes, bid):
    top = TEMP / name
    if top.exists(): shutil.rmtree(top)
    classes = []
    for c in range(n_classes):
        refs = [f"reference/c{c}_{k}.jpg" for k in range(2)]
        for r in refs: jpg(top / r, f"ref c{c}", (40 * c % 255, 90, 160), (60, 40))
        classes.append({"id": f"cls_{c + 1}", "label": f"Class number {c + 1}", "description": f"description {c + 1}", "reference": refs})
    items = []
    for i in range(n_items):
        iid = f"it_{i:03d}"
        jpg(top / "patches" / f"{iid}.jpg", iid, (30, 30 + 20 * i, 30), (50, 30))
        jpg(top / "context" / f"{iid}.jpg", iid + " ctx", (30, 30, 30 + 20 * i), (160, 120))
        items.append({"item_id": iid, "patch": f"patches/{iid}.jpg", "context": f"context/{iid}.jpg"})
    (top / "batch.json").write_text(json.dumps({"format": 1, "batch_id": bid, "title": f"Title of {name}",
        "instruction": f"Instruction text for {name}.", "classes": classes, "items": items}, indent=1))
    return top

def files_of(top): return sorted(str(p.relative_to(top)) for p in top.rglob("*") if p.is_file())

make = lambda *a: make_batch(*a)
if TEMP.exists(): shutil.rmtree(TEMP)
A = make_batch("a6", 6, 3, "batch_A")
B = make_batch("b8", 4, 8, "batch_B")
C = make_batch("c11", 2, 11, "batch_C")
M = make_batch("miss", 4, 3, "batch_M")
(M / "patches" / "it_002.jpg").unlink(); (M / "reference" / "c1_1.jpg").unlink()
ALL = {"a6": A, "b8": B, "c11": C, "miss": M}

# ---- local server ------------------------------------------------------------------------------
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(REPO)))
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://localhost:{PORT}/tool/index.html"

PICKER = """() => { window.showDirectoryPicker = async () => {
  const r = await navigator.storage.getDirectory(); return r.getDirectoryHandle(window.__pick); }; }"""
MK = """async ({name, base, files}) => {
  const root = await navigator.storage.getDirectory();
  try { await root.removeEntry(name, {recursive: true}); } catch (e) {}
  const top = await root.getDirectoryHandle(name, {create: true});
  for (const path of files) {
    const parts = path.split('/'); let d = top;
    for (const p of parts.slice(0, -1)) d = await d.getDirectoryHandle(p, {create: true});
    const r = await fetch('/' + base + '/' + path); const blob = await r.blob();
    const w = await (await d.getFileHandle(parts[parts.length-1], {create: true})).createWritable(); await w.write(blob); await w.close();
  } }"""
READ = """async ({name, path}) => {
  try { let d = await (await navigator.storage.getDirectory()).getDirectoryHandle(name);
    const parts = path.split('/'); for (const p of parts.slice(0, -1)) d = await d.getDirectoryHandle(p);
    return await (await d.getFileHandle(parts[parts.length-1])).getFile().then(f => f.text()); } catch (e) { return null; } }"""
LIST = """async ({name, path}) => { try { let d = await (await navigator.storage.getDirectory()).getDirectoryHandle(name);
  for (const p of path.split('/').filter(x => x)) d = await d.getDirectoryHandle(p);
  const o = []; for await (const [n] of d.entries()) o.push(n); return o.sort(); } catch (e) { return null; } }"""

with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"]) if CHROME else pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script("window.__pick = sessionStorage.getItem('pick');")

    def mk(name, top, drop=()):
        page.evaluate(MK, {"name": name, "base": str(top.relative_to(REPO)), "files": [f for f in files_of(top) if f not in drop]})
    def open_page():
        page.goto(URL); page.evaluate(PICKER)
    def pick(name):
        page.evaluate("n => { window.__pick = n; sessionStorage.setItem('pick', n); }", name)
        old = page.evaluate("document.getElementById('ld-report').textContent")
        if page.locator("#ld-choose").is_visible(): page.click("#ld-choose")
        else: page.click("#ld-again")
        page.wait_for_selector("#ld-report", state="visible")
        page.wait_for_function("old => document.getElementById('ld-report').textContent !== old", arg=old)
        return page.inner_text("#ld-report")
    def start(folder, who):
        rep = pick(folder); page.fill("#ld-name", who); page.click("#ld-start")
        page.wait_for_selector("#loader", state="hidden"); page.wait_for_function("window.__dbg && __dbg().keys.length")
        return rep
    def dbg(): return page.evaluate("__dbg()")
    def settle():
        page.wait_for_function("() => /^saved|^nothing/.test(document.getElementById('h-state').textContent) || document.getElementById('h-state').className.includes('err')", timeout=5000)
        page.wait_for_timeout(50)
    def key(k): page.keyboard.press(k); page.wait_for_timeout(60)
    def saved(folder, who):
        t = page.evaluate(READ, {"name": folder, "path": f"annotations/{who}.json"}); return json.loads(t) if t else None
    def ans(folder, who):
        s = saved(folder, who); return {k: v["answer"] for k, v in s["answers"].items()} if s else None
    def vis(sel): return page.locator(sel).is_visible()
    def img_ok(sel): return page.evaluate(f"() => {{ const i = document.querySelector('{sel}'); return i && i.complete && i.naturalWidth > 0; }}")
    def cur_img_ok():
        page.wait_for_timeout(150); return img_ok("#img-patch") and img_ok("#img-context")
    def cls(i): return f"cls_{i}"

    page.goto(URL)
    mk("a6", A); mk("b8", B); mk("c11", C); mk("miss", M)
    mk("notbatch", A, drop=["batch.json"])
    open_page()

    # ---- 1. report screen ------------------------------------------------------------------------
    rep = pick("a6"); page.screenshot(path=str(TEMP / "shot-report.png"))
    ck("1a report: title, instruction, 6 items, 3 classes", all(s in rep for s in ["Title of a6", "Instruction text for a6.", "batch_A"]) and "Items\t6" in rep and "Classes\t3" in rep, rep)
    ck("1b report: nothing missing, no annotations", rep.count("none") >= 4, rep)
    ck("1c Start disabled until a name is typed", page.locator("#ld-start").is_disabled())
    page.fill("#ld-name", "Ann Lee/2 ")
    ck("1d name sanitised in the shown file name", "annotations/Ann_Lee_2.json" in page.inner_text("#ld-nameinfo") and page.locator("#ld-start").is_enabled(), page.inner_text("#ld-nameinfo"))
    rep = pick("notbatch"); ck("1e folder without batch.json: 'not a batch folder', no Start", "not a batch folder" in rep and page.locator("#ld-start").count() == 0, rep)

    # ---- 2. answers by key and button, notes, back and change, undo -------------------------------
    open_page(); start("a6", "ann")
    d = dbg()
    ck("2a keys built from batch.json: 1..3, 0, r, x", d["keys"] == [["cls_1", "1"], ["cls_2", "2"], ["cls_3", "3"], ["not_ring", "0"], ["ring_unknown", "r"], ["unsure", "x"]], d["keys"])
    ck("2b 6 answer buttons with key shown", page.locator("#answers button").count() == 6 and "Class number 2" in page.inner_text("#answers button:nth-child(2)") and page.inner_text("#answers button:nth-child(5)").startswith("R"))
    ck("2c patch and context images load", cur_img_ok())
    ck("2d progress shown", "item 1 of 6" in page.inner_text("#h-prog"), page.inner_text("#h-prog"))
    key("1"); settle()
    s = saved("a6", "ann")
    ck("2e key 1 answers item 0, moves on, file written with all fields", ans("a6", "ann") == {"it_000": "cls_1"} and dbg()["pos"] == 1
       and s["tool_version"] == "v1.0" and s["format"] == 1 and s["batch_id"] == "batch_A" and s["annotator"] == "ann" and s["saved_at"]
       and s["answers"]["it_000"]["answered_at"] and s["answers"]["it_000"]["note"] == "", s)
    page.click("#answers button[data-ans=cls_2]"); settle()
    ck("2f button click answers item 1", ans("a6", "ann") == {"it_000": "cls_1", "it_001": "cls_2"} and dbg()["pos"] == 2, ans("a6", "ann"))
    key("0"); settle()
    ck("2g key 0 = not_ring", ans("a6", "ann")["it_002"] == "not_ring" and dbg()["pos"] == 3)
    page.click("#note"); page.keyboard.type("x1r0 3"); page.wait_for_timeout(100)
    ck("2h typing in the note field answers nothing", set(dbg()["answers"]) == {"it_000", "it_001", "it_002"} and page.input_value("#note") == "x1r0 3" and dbg()["pos"] == 3)
    page.keyboard.press("Escape"); key("r"); settle()
    s = saved("a6", "ann")
    ck("2i key R = ring_unknown, note typed before answering is saved", s["answers"]["it_003"]["answer"] == "ring_unknown" and s["answers"]["it_003"]["note"] == "x1r0 3", s["answers"].get("it_003"))
    ck("2j note field cleared on the next item", page.input_value("#note") == "" and dbg()["pos"] == 4)
    key("ArrowLeft"); key("ArrowLeft")
    ck("2k Back twice: item 2, shows its answer selected", dbg()["pos"] == 2 and page.locator("#answers button.sel").get_attribute("data-ans") == "not_ring")
    key("3"); settle()
    ck("2l change an answer: saved, moves to next", ans("a6", "ann")["it_002"] == "cls_3" and dbg()["pos"] == 3 and len(ans("a6", "ann")) == 4, ans("a6", "ann"))
    ck(".bak kept next to the annotation file", "ann.json.bak" in page.evaluate(LIST, {"name": "a6", "path": "annotations"}))
    key("Control+z"); settle()
    ck("2m Undo (Ctrl+Z) restores previous answer and place", ans("a6", "ann")["it_002"] == "not_ring" and dbg()["pos"] == 2)
    page.click("#b-undo"); settle()
    a = ans("a6", "ann")
    ck("2n Undo button removes the answer given before (item 3 unanswered again)", "it_003" not in a and len(a) == 3 and dbg()["pos"] == 3, a)

    # ---- 3. reference gallery mid-batch ---------------------------------------------------------
    before = dbg()
    key("g"); page.wait_for_timeout(300)
    ck("3a G opens gallery with one block per class and loaded images", vis("#gallery") and page.locator("#gbody .gcls").count() == 3 and page.locator("#gbody img").count() == 6 and img_ok("#gbody img"), page.locator("#gbody .gcls").count())
    ck("3b gallery shows labels and descriptions from batch.json", "Class number 3" in page.inner_text("#gbody") and "description 2" in page.inner_text("#gbody"))
    key("1"); key("ArrowLeft")
    ck("3c answer and move keys do nothing while gallery is open", dbg()["answers"] == before["answers"] and dbg()["pos"] == before["pos"])
    key("Escape")
    ck("3d Esc closes gallery, place and answers unchanged", not vis("#gallery") and dbg()["pos"] == before["pos"] and dbg()["answers"] == before["answers"])
    page.click("#b-ref"); ck("3e button opens", vis("#gallery")); page.click("#b-gclose")
    ck("3f Close button closes", not vis("#gallery") and dbg()["pos"] == before["pos"])
    key("x"); key("2"); settle()
    ck("3g continue after gallery: item 3 unsure, item 4 cls_2", ans("a6", "ann")["it_003"] == "unsure" and ans("a6", "ann")["it_004"] == "cls_2" and dbg()["pos"] == 5)

    # ---- 4. strip, jump, note change on an answered item, export ----------------------------------
    ck("4a strip: 6 cells, 5 answered, current marked", page.locator("#strip span").count() == 6 and page.locator("#strip span.ans").count() == 5 and page.locator("#strip span.cur").count() == 1)
    page.click("#strip span:nth-child(1)"); ck("4b click strip jumps", dbg()["pos"] == 0)
    page.click("#b-first"); ck("4c First unanswered jumps to item 5", dbg()["pos"] == 5)
    page.click("#strip span:nth-child(1)"); page.click("#note"); page.keyboard.type("hello, \"quoted\""); page.wait_for_timeout(900); settle()
    s = saved("a6", "ann")
    ck("4d note edit on answered item autosaved, answer unchanged", s["answers"]["it_000"]["note"] == 'hello, "quoted"' and s["answers"]["it_000"]["answer"] == "cls_1", s["answers"]["it_000"])
    with page.expect_download() as dl: page.click("#b-export")
    csv_path = dl.value.path(); csv_text = Path(csv_path).read_text().splitlines()
    ck("4e Export CSV: header and 5 answered rows with annotator and batch_id", csv_text[0] == "item_id,answer,note,answered_at,annotator,batch_id" and len(csv_text) == 6
       and csv_text[1].startswith('it_000,cls_1,"hello, ""quoted""",') and csv_text[1].endswith(",ann,batch_A"), csv_text[:3])

    # ---- 5. reload and resume ---------------------------------------------------------------------
    open_page(); rep = pick("a6")
    ck("5a report after reload lists the existing annotation file with its count", "ann.json: 5 of 6 answered" in rep, rep)
    page.fill("#ld-name", "ann")
    ck("5b same name shows it will resume", "you will resume" in page.inner_text("#ld-nameinfo"))
    page.click("#ld-start"); page.wait_for_selector("#loader", state="hidden"); page.wait_for_function("window.__dbg && __dbg().keys.length")
    d = dbg()
    ck("5c resumes at first unanswered item (5) with earlier answers loaded", d["pos"] == 5 and len(d["answers"]) == 5 and d["answers"]["it_003"]["answer"] == "unsure", (d["pos"], len(d["answers"])))
    key("2"); settle()
    ck("5d last item answered: file has all 6, position stays on last", len(ans("a6", "ann")) == 6 and dbg()["pos"] == 5 and page.locator("#strip span.ans").count() == 6)

    # ---- 6. two annotator names in one folder ------------------------------------------------------
    open_page(); start("a6", "bob")
    ck("6a second name starts fresh at item 0", dbg()["pos"] == 0 and dbg()["answers"] == {})
    key("2"); settle()
    ck("6b two files in annotations/, each with its own answers", ans("a6", "bob") == {"it_000": "cls_2"} and ans("a6", "ann")["it_000"] == "cls_1" and len(ans("a6", "ann")) == 6
       and saved("a6", "bob")["annotator"] == "bob", (ans("a6", "bob"), ans("a6", "ann")))
    open_page(); rep = pick("a6")
    ck("6c report lists both files", "ann.json: 6 of 6" in rep and "bob.json: 1 of 6" in rep, rep)

    # ---- 7. save failure ---------------------------------------------------------------------------
    page.evaluate("() => { window.__orig = FileSystemFileHandle.prototype.createWritable; FileSystemFileHandle.prototype.createWritable = async () => { throw new Error('disk full'); }; }")
    page.fill("#ld-name", "bob"); page.click("#ld-start"); page.wait_for_selector("#loader", state="hidden")
    key("3"); page.wait_for_timeout(300)
    st = page.evaluate("() => [document.getElementById('h-state').textContent, getComputedStyle(document.getElementById('h-state')).backgroundColor]")
    ck("7a failed save shows a red message", "SAVE FAILED" in st[0] and "disk full" in st[0] and st[1] == "rgb(154, 42, 42)", st)
    page.evaluate("() => { FileSystemFileHandle.prototype.createWritable = window.__orig; }")
    key("3"); settle()
    ck("7b recovers when writes work again", "SAVE FAILED" not in page.inner_text("#h-state") and "it_002" in (ans("a6", "bob") or {}), ans("a6", "bob"))

    # ---- 8. different class list (8 classes) --------------------------------------------------------
    open_page(); rep = start("b8", "carl")
    ck("8a 8 classes + 3 fixed buttons from batch.json", page.locator("#answers button").count() == 11 and [k for _, k in dbg()["keys"]][:8] == list("12345678"), dbg()["keys"])
    key("8"); settle()
    key("4"); settle()
    key("0"); settle()
    ck("8b digit 8 gives the 8th class, saved with batch_B", ans("b8", "carl") == {"it_000": "cls_8", "it_001": "cls_4", "it_002": "not_ring"} and saved("b8", "carl")["batch_id"] == "batch_B", ans("b8", "carl"))
    key("g"); page.wait_for_timeout(300)
    ck("8c gallery has 8 class blocks", page.locator("#gbody .gcls").count() == 8); key("Escape")
    ck("8d earlier batch's labels not present", "Class number 8" in page.inner_text("#answers") and "Title of b8" in page.inner_text("#h-batch"))

    # ---- 9. more than 9 classes ---------------------------------------------------------------------
    open_page(); start("c11", "dee")
    ks = dict(dbg()["keys"])
    ck("9a classes 10 and 11 get letters a, b; 1..9 as digits", ks["cls_9"] == "9" and ks["cls_10"] == "a" and ks["cls_11"] == "b" and ks["ring_unknown"] == "r", ks)
    key("a"); settle()
    ck("9b letter key answers class 10", ans("c11", "dee") == {"it_000": "cls_10"}, ans("c11", "dee"))

    # ---- 10. missing images -------------------------------------------------------------------------
    open_page(); rep = pick("miss"); page.screenshot(path=str(TEMP / "shot-missing.png"))
    ck("10a report lists missing patch and missing reference file", "1 missing: patches/it_002.jpg" in rep and "reference/c1_1.jpg" in rep and "Missing context files\tnone" in rep, rep)
    ck("10b Start still possible with a name", (page.fill("#ld-name", "eve"), page.locator("#ld-start").is_enabled())[1])
    page.click("#ld-start"); page.wait_for_selector("#loader", state="hidden"); page.wait_for_function("window.__dbg && __dbg().keys.length")
    key("1"); key("1"); settle(); page.wait_for_timeout(200)
    ck("10c item with missing patch shows a message, context still shown", vis("#miss-patch") and "patches/it_002.jpg" in page.inner_text("#miss-patch") and img_ok("#img-context") and not vis("#img-patch"))
    key("1"); page.wait_for_timeout(300)
    ck("10d next item shows both images again", not vis("#miss-patch") and img_ok("#img-patch"))
    key("g"); page.wait_for_timeout(300)
    ck("10e gallery shows missing reference by name", "missing: reference/c1_1.jpg" in page.inner_text("#gbody")); key("Escape")

    # ---- 11. unsupported browser --------------------------------------------------------------------
    p2 = ctx.new_page(); p2.add_init_script("delete window.showDirectoryPicker;"); p2.goto(URL)
    ck("11 no folder API: message naming Chrome or Edge, no picker button", "Chrome or Edge" in p2.inner_text("#ld-unsupported") and not p2.locator("#ld-choose").is_visible())

    ck("no uncaught page errors", not errors, errors)
    br.close()

shutil.rmtree(TEMP, ignore_errors=True)
fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
sys.exit(1 if fails else 0)
