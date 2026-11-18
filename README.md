# Ring annotator

**Proprietary, all rights reserved. Not open source. Nothing here may be copied, reused, shared or used to train or evaluate any AI system: see `LICENSE`.**

A small web page for labelling pictures of leg rings on birds: for each picture you say whether it shows a ring and, if so, which type.
It runs in your browser and reads and writes one folder on your computer; nothing is uploaded by the page.

## For the annotator

### Start
1. Download the batch folder you were given and unzip it if needed.
2. Open the annotator page (the address you were given) in **Chrome or Edge** on a computer. Firefox and Safari cannot read and write a folder, so the page only shows a message there.
3. Click **Choose batch folder**, pick the unzipped batch folder, and allow the browser to view and edit its files when it asks.
4. Read the report: batch title, instruction, number of items, any missing image files, and annotation files already in the folder. If it says "not a batch folder", you picked the wrong folder (often one level too high or too low).
5. Type your name and click **Start**. Use the same name every time: if a file for that name exists you carry on at your first unanswered item. Other people's files in the same folder are not touched.

If you reload the page you have to pick the folder again and type your name; your answers are read back from `annotations/`.

### Screen
Left: the ring patch, enlarged, and next to it the whole bird with the patch outlined. Right: the answer buttons (each shows its key), a note field, Back / Forward, Undo, First unanswered, **Reference**, **Export CSV**. Below: a strip with one cell per item (green = answered, yellow outline = the one you are on); click a cell to jump there.

### Answers
Exactly one answer per item: one of the ring types listed in the batch (digit keys 1, 2, 3, ... in the order of the buttons), **0** not a ring, **R** ring but can't tell which type, **X** can't tell if it is a ring. Answering moves to the next item. If a batch has more than nine types, the tenth and later get the letters A, B, C, ... (see the key on each button).

| Key | Action |
|---|---|
| 1 2 3 ... , 0, R, X | answer (the key is shown on each button) |
| Left / Right arrow | back / forward (to revisit and change an answer) |
| Ctrl+Z | undo the last answer or change |
| G | open the reference gallery; G or Esc closes it |

Typing in the note field never answers an item. A note typed before you answer is saved with the answer; a note typed on an already answered item is saved on its own. **Reference** can be opened and closed at any time; you stay on the same item and answers are not possible while it is open.

### Saving and sending results back
Every answer and every note change is saved at once to `annotations/<your name>.json` inside the batch folder (the previous version is kept as `.json.bak`). The header shows "saved <time>"; a red message means a save failed and your latest change is not saved yet. When you have finished, send back the whole batch folder (with `annotations/` inside) as instructed. **Export CSV** downloads one CSV of your answers (`item_id, answer, note, answered_at, annotator, batch_id`; answered items only); sending it is optional. Do not rename the files.

## For the maintainer

### Browser support
File System Access API (`window.showDirectoryPicker`, read and write): Chrome and Edge on desktop. Firefox and Safari get a message naming Chrome or Edge. It needs a secure context: https (GitHub Pages) or `localhost`. The native folder dialog is not covered by the automated test.

### Requirements
No server and no packages for the annotator: the repository root is a static site (`index.html` redirects to `tool/`). Images are never in this repository; batch folders are shared separately.

### Run locally

    python3 -m http.server 8000      # from the repository root
    # open http://localhost:8000/ and pick a batch folder

### Test
Needs Python 3 with `playwright` (and a Chromium for it) and `Pillow`:

    python3 tests/click_through.py

It builds small synthetic batches in `temp/` (git-ignored, deleted at the end), serves the page, replaces the folder dialog by a folder in the browser's private file system, and drives real keyboard and mouse events. It asserts on the saved JSON and the exported CSV. Set `CHROME=/path/to/chrome` to choose the browser.

### Batch folder format

    <batch>/batch.json
    <batch>/patches/<item_id>.jpg
    <batch>/context/<item_id>.jpg
    <batch>/reference/<file>.jpg
    <batch>/annotations/<annotator>.json      (written by the page, plus .bak)

`batch.json`: `{"format": 1, "batch_id", "title", "instruction", "classes": [{"id", "label", "description", "reference": ["reference/x.jpg", ...]}, ...], "items": [{"item_id", "patch", "context"}, ...]}`. Items are shown in this order. Buttons, keys and the gallery are built from `classes` in this order. Class ids must not be `not_ring`, `ring_unknown` or `unsure` and must be unique; so must `item_id`. `item_id` must not reveal video, bird or model output. The outline is drawn into the context image by the batch builder. Missing image files are reported on the start screen and shown as a message on the item; the answer buttons still work.

Saved file `annotations/<name>.json` (name = the typed name with anything but letters, digits, `.`, `_`, `-` replaced by `_`): `{"tool_version", "format", "batch_id", "annotator", "saved_at", "answers": {"<item_id>": {"answer": "<class id>" | "not_ring" | "ring_unknown" | "unsure", "note", "answered_at"}}}`. A saved file whose `batch_id` differs from the batch blocks Start for that name.

Keep any key file (item_id to video, bird, model scores) outside this repository; `keys/` is git-ignored.

### Licence
All rights reserved, University of Vienna (see `LICENSE`).
