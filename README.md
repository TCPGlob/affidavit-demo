# Document Preparation Pipeline — feeding Zibbit

A local-first pipeline that takes a folder of mixed documents, converts them to
PDF, and produces **numbered, ordered PDF bundles ready to import into Zibbit**,
with a shared web console a non-technical user can work in.

The workflow, in one line:

> documents arrive → the pipeline tags them → you tick the ones you want →
> you name the bundle → **Convert & export** → import the numbered PDFs into Zibbit.

> **Design principle.** The pipeline converts, files, numbers and reconciles.
> It **never** decides what belongs in a bundle. That is the user's call, always.

---

## Zibbit is fed PDFs

That is the contract, so it shapes the output. **The `PDFs` folder is the
product** — its files are already numbered in the order you set, so Zibbit sees
the bundle in the right sequence.

```
output/collections/<Your Name>/
    PDFs/                          ← import THIS into Zibbit
        001 - Engagement Letter.pdf
        002 - Statement of Claim.pdf
        003 - Demand Letter.pdf
    index.csv                      contents list, for a spreadsheet
    manifest.json                  same, for later tooling
    00 - <Your Name> - Index.docx  readable index sheet for your own reference
```

The Word file is a convenience and a record of what was included — **Zibbit does
not need it**. It is generated because a human occasionally needs to read the
bundle list without opening eight PDFs.

---

## Quick start — one machine

```bash
python pipeline.py demo        # create a synthetic intake folder (17 files)
python pipeline.py run         # ingest, convert, tag
python pipeline.py review      # open the console
```

Then open <http://127.0.0.1:8765/>. Binds to localhost only, no sign-in needed.

In the console: tick documents in the **Library**, choose **+ New collection**,
name it, and hit **Create & convert**. The bundle is written and the path is
shown on screen.

## Quick start — show it to a client

One command, synthetic documents, sign-in off:

```bash
python pipeline.py review --demo
```

Or hand them a link — see [SETUP.md](SETUP.md) for a plain-language walkthrough,
GitHub Codespaces, Docker, and a five-minute demo script.

> **Demo mode is synthetic data only.** Anyone with the URL can reach it. Never
> upload client material to a demo instance.

## Quick start — Windows, no command line

Double-click one of these:

| File | What it does |
|---|---|
| **`start-windows.bat`** | Runs it for real. Each person gets their own sign-in. |
| **`demo-windows.bat`** | Sample documents, no sign-in, for showing a client. |

The first run opens a **Welcome** page in your browser where you create your own
account. **That first account is the administrator**, and you add colleagues from
the **Team** tab inside the app — no command line needed.

On macOS or Linux, run `./start-mac-linux.command`.

## Quick start — shared by a team

```bash
python pipeline.py review --users          # each person gets their own sign-in
```

Open <http://127.0.0.1:8765/> and create your account on the Welcome page.

From then on, the **Team** tab lets an administrator add colleagues, reset a
forgotten password, and disable someone who has left — all in the browser.

Command-line equivalents still exist if you prefer them:

```bash
python pipeline.py create-user --username jane --name "Jane Smith" --role admin
python pipeline.py users --reset-password jane
```

**Collections are shared.** Everyone sees every collection, so a colleague can
pick up work. Each collection records who started it and who last exported it,
and the Team tab shows a live activity feed and the record of who did what.

### Shared pool vs. sign-in — the distinction that matters

These are two independent settings, and it is easy to conflate them:

| | Shared pool | Sign-in off |
|---|---|---|
| Everyone sees every collection | ✅ always | ✅ always |
| Records *who* did what | ✅ | ❌ attributed to `local` |
| Detects conflicting edits | ✅ | ✅ |

Running without `--require-auth` gives you a shared pool with **no identity
tracking** — convenient on one laptop, but you lose the audit trail and every
edit is recorded as "local". For a team, use `--require-auth`.

### Conflicting edits are detected, never silent

Two people can work in the same collection at once. Each editable row carries a
version; when you save, you send the version you were looking at. If someone
else has changed it since, your save is **refused** and you are shown both
versions to choose between — rather than your typing quietly overwriting theirs.

Adding the same document twice is a no-op, so two people tidying the same bundle
cannot create duplicates.

### What is verified for multiple users

Tested directly with three accounts signed in at once:

| Behaviour | Result |
|---|---|
| Separate sign-in per person | 3/3, each request resolved to the right identity |
| Same shared library visible to all | 6 documents each |
| Concurrent collection creation | 3 collections created in parallel, no interference |
| Everyone sees every collection | all three saw all three |
| Simultaneous export of the *same* collection | 3/3 succeeded, bundle intact, not corrupted |
| No cross-user clobbering | each user's bundle kept its own contents |
| Attribution | `created_by` and `exported_by` recorded per person |
| Audit trail | every action attributed; admin-only to read in full |
| Conflicting edit to the same field | **refused**, not silently applied |

Concurrent exports of the same bundle are safe because each export rebuilds the
folder, and the last writer records itself as the exporter — the content is
identical either way.

**Conflicting edits are refused, not merged.** If two people edit the same field,
the second is told and chooses which version to keep. Nothing is lost silently,
but this is not real-time collaboration: it is optimistic concurrency control,
the same approach wikis use.

| Command | Purpose |
|---|---|
| `python pipeline.py share` | let colleagues connect, and print the address to give them |
| `python pipeline.py collections` | list bundles and what is in them |
| `python pipeline.py bundle --docs 8,1,11 --name "Bundle A"` | build and export a bundle without the browser |
| `python pipeline.py ocr` | read scanned documents again |
| `python pipeline.py users` | list accounts and how many documents each reviewed |
| `python pipeline.py audit` | show who changed what, and when |
| `python pipeline.py create-user …` | add an account |

Reaching colleagues in another building, or at home, needs a private network
rather than a plain address — see [SETUP.md](SETUP.md#working-from-home).

Build a bundle entirely from the command line:

```bash
python pipeline.py bundle --docs 8,1,11,7 --name "Harbourview Bundle" --user jane
```

Re-running the same command **tops the collection up** rather than erroring or
duplicating: adding a document that is already present is a no-op.

---

## The console

Written for someone who has never seen this pipeline:

- **How this works** — a six-step guide at the top, plus a glossary of every term
  (Library, Collection, Bundle, PDFs folder, Index sheet, Tag, OCR) and what each
  status label means. Collapsible once you know it.
- **Two tabs** — *Library* (everything the pipeline knows about) and *Collections*
  (your bundles). Both show live counts.
- **A Team tab** — who is signed in right now, every account, and a running feed
  of what everyone has done ("Raj exported a bundle", "Jane created a collection").
  Readable by every signed-in user, not just admins: on a shared pool, knowing who
  is working on what is the difference between collaboration and collision.
- **Tick → name → convert.** The black action bar appears as soon as you tick
  anything, offering **Convert & export as bundle** or **Add to** an existing one.
- **In-page dialogs, not browser popups.** Creating, renaming and describing all
  happen in a proper modal.
- **Reorder inside a collection** with ↑/↓, and rename a document *within that
  bundle* without affecting any other bundle it appears in.
- **Tags** — type `witness: M. Reed` under any document. Tags you add are yours
  and are never overwritten when the pipeline re-reads the files.
- **Exclusions are visible.** Documents that could not be converted appear under
  **Not included** with the reason, in the console, the Word sheet, `index.csv`
  and `manifest.json`. A gap you can see beats a silent omission.

---

## OCR — reading scans, locally

Scanned documents and phone photos have no text layer, so nothing can search
them or work out their date. OCR fixes that.

**It runs on this machine.** Tesseract is a local program; there are no cloud
calls and no API keys, so scanned client material never leaves the computer.

### Installing it

```bash
winget install UB-Mannheim.TesseractOCR     # Windows
sudo apt install tesseract-ocr              # Debian/Ubuntu
brew install tesseract                      # macOS
```

The pipeline finds it even when the installer does not add it to `PATH`. With
Tesseract absent, everything still runs — scans are exported as images, flagged
`OCR NEEDED`, and the pipeline tells you what to install.

For French documents, install the extra language data and set it in
`affidavit.config.json`:

```json
{ "ocr_lang": "eng+fra" }
```

Check what is available with `tesseract --list-langs`. A language that is not
installed falls back to `eng` and says so, rather than silently producing
nothing.

### Using it

It runs automatically as step 4 of `python pipeline.py run`. To run it on its own,
or re-read scans at full quality:

```bash
python pipeline.py ocr              # read anything not yet read
python pipeline.py ocr --force      # re-read everything, including what succeeded
python pipeline.py ocr --lang eng+fra --dpi 300 --max-pages 50
```

The Library tab has the same thing as buttons, with a live count of what is
unread.

### Two design decisions worth knowing

**OCR never alters the exported document.** A scanned page is evidence, and a
re-rendered version of it is not the same exhibit. OCR writes a *separate*
searchable copy to `work/ocr/`, used only for titles, dates and search. The PDFs
folder in your bundle still contains the original scans.

**OCR recovers metadata, not just text.** Once a scan can be read, its title,
document type and date are filled in from the recognised text — so a scanned
invoice stops being an undated blank in the index.

### What to expect

Measured on the sample documents:

| Document | Result |
|---|---|
| A clean 300 dpi scan | **96% confidence**, date and type recovered correctly |
| A low-quality photo of a receipt | 64% confidence, key fields (date, total, receipt no.) still recovered and searchable |
| A genuinely blank page | `no_text_found` — reported honestly, not invented |

OCR is not perfect, and it depends on the source image. Before relying on a
scanned document, open it and check the fields OCR filled in. The `OCR NEEDED`
badge and the reconciliation report both tell you which documents were read
mechanically.

Date parsing is deliberately lenient about OCR damage: `202404-12` and
`20240412` are both read as `2024-04-12`, while `20241350` (month 13) is
correctly rejected so reference numbers never become dates.

---

## What it does

| Stage | Module | Output |
|---|---|---|
| Ingest | `ingest.py` | Walk `intake/source`, hash bytes, fingerprint text |
| De-duplicate | `ingest.py` | Collapse exact and near-duplicates, keep every original path |
| Convert | `convert.py` | PDF, image, Office, plain text → PDF, with graceful degradation |
| Tag | `extract.py`, `db.py` | Type, date, page count, OCR flag, free-form user tags |
| Collections | `db.py`, `collections.py` | Named bundles, ordering, per-bundle naming |
| Export | `collections.py` + `docxwriter.py` | Numbered PDFs, Word index, CSV, manifest |
| Auth | `auth.py` | Accounts, sessions, roles, audit trail |
| Reconcile | `reconcile.py` | Traceability report proving nothing was lost |

### De-duplication

Two content-based passes:

1. **Exact** — group by a fingerprint of the *extracted text*, falling back to a
   byte hash when no text can be read. Fingerprinting text rather than bytes is
   deliberate: the same letter re-saved by Word, or exported to PDF and then
   photographed, is the same instrument, and a `foo.pdf` / `foo.docx` pair should
   resolve to one document.
2. **Near** — merge by similarity, requiring **both** character similarity
   (`near_dup_threshold`, default 0.90) **and** significant-token overlap
   (`near_dup_min_token_overlap`, default 0.85).

The token test is load-bearing. `difflib.quick_ratio()` compares character
*multisets*, so two unrelated legal documents sharing ordinary vocabulary score
near 1.0 — during development it merged a Statement of Claim into an engagement
letter. Silently merging two different documents into one bundle entry is a
correctness failure, not a cosmetic one.

### File names inside a bundle

In priority order: a name you set for this bundle → the document's own title
(derived from its original file name) → the source path as a last resort. The
sequence number is always prefixed: `003 - Demand Letter.pdf`.

Setting a name inside one collection does **not** affect the same document in
another collection.

---

## Graceful degradation

External tools are optional; a missing one produces a clearly-flagged outcome,
never a silent skip.

| Tool | Needed for | If missing |
|---|---|---|
| **LibreOffice** | DOCX/XLSX/PPTX → PDF | A marked placeholder, flagged, and listed under **Not included** rather than numbered |
| **Tesseract** | OCR of image-only scans | Scan still exports; flagged `OCR NEEDED` everywhere |
| **PyMuPDF** | PDF read/write, image→PDF | Required in practice |
| **Pillow** | Image formats | Image conversion fails explicitly |
| **openpyxl** | `index.xlsx` (legacy path only) | Skipped; Word/CSV remain |

```bash
winget install TheDocumentFoundation.LibreOffice
winget install UB-Mannheim.TesseractOCR
```

A document that fails to convert **never takes a number**, so the sequence stays
gapless and Zibbit never receives a placeholder in the middle of a bundle.

Word output has **no** dependency: `docxwriter.py` uses only the standard library.

---

## Verification

```bash
python collections_test.py   # tick -> name -> export, ordering, tags, HTTP surface
python ocr_test.py           # engine detection, real OCR, searchability, date parsing
python smoke_test.py         # console reads and writes, persistence, bad input
python auth_test.py          # accounts, sessions, attribution, CSRF, audit
python e2e_test.py           # the legacy affidavit-style export path
```

All four pass. `collections_test.py` asserts, among other things, that
re-exporting does not duplicate files, that removing a document from a bundle
does not delete it from the library, that per-collection names stay independent,
that positions stay contiguous from 1, and that an empty bundle is refused.

---

## Data handling

The pipeline makes **no network calls**. Conversion, hashing, filing and index
generation are entirely local.

Sharing changes the threat model, so:

- **Never expose the console without `--require-auth`.** The server warns loudly
  if you bind to `0.0.0.0` without it.
- **Terminate TLS in front of it.** Run a reverse proxy (Caddy, nginx, IIS) with
  a real certificate and use `--secure-cookie`.
- **Prefer a private network** — a VPN or Tailscale — over a public port.
- **Encrypt the disk** holding `intake/`, `work/` and `output/`, and back up
  `work/pipeline.sqlite3` with the same care as the documents.
- **Get written direction** on where matter data may reside before hosting it
  anywhere. The `Dockerfile` is for a private host, not a public one.

`intake/`, `work/`, `output/` and `affidavit.config.json` are git-ignored, so
client material cannot leak into version control.

---

## Known limitations

- **OCR accuracy depends on the scan.** A clean 300 dpi scan reads well; a poor
  photo may misread words. Dates and totals are usually recovered; verify
  anything that matters by opening the original.
- **OCR reads the first 25 pages by default** (`ocr_max_pages`). Long scanned
  documents are partially read and the component says so.
- **SQLite and a single write lock.** Fine for a handful of users. Past roughly
  ten concurrent editors, move to Postgres.
- **No cloud storage connector.** Files are read from `intake/source` only.
  SharePoint/Drive ingestion is not implemented.
- **Zibbit is not called.** It is a Word add-in with no API; this pipeline's job
  ends at producing the PDFs it consumes.
- **No drag-and-drop reordering.** Order is set by add-order plus the ↑/↓ buttons.
- **Near-duplicate detection is O(n²)** against cluster representatives. Fine for
  hundreds of documents; needs MinHash/LSH beyond a few thousand.
- **Date parsing is heuristic.** Ambiguous `03/04/2024` is read day-first per
  Canadian practice. Verify anything that matters.

### Legacy code

An earlier iteration targeted a formal *Affidavit of Documents* with fixed
Schedule A/B/C classification. That model was wrong for this use case — the
taxonomy is the user's, not the court's — and the console no longer uses it.

`assemble.py` and `python pipeline.py assemble` remain, and are covered by
`e2e_test.py`, but they are a separate export shape rather than the main path.
They can be deleted once the collection workflow is settled.

---

## Why a local pipeline rather than a hosted agent

An MCP server driving a hosted model has two problems here:

1. **Confidentiality.** Converting through a model API means client material
   transits a third party. That is a professional responsibility question before
   it is a technical one.
2. **Determinism.** The same inputs must produce the same bundle, with a
   traceable reason for every placement. Deterministic conversion and
   reconciliation give that; a conversational agent does not.

The narrow place a model genuinely helps is *suggesting a document type* or
*drafting an index description* — both cosmetic, both reversible by a human.
Conversion, naming, filing and numbering should stay deterministic.
