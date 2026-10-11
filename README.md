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

Or hand them a link — see [DEPLOY.md](DEPLOY.md) for GitHub Codespaces, Docker,
and a five-minute demo script.

> **Demo mode is synthetic data only.** Anyone with the URL can reach it. Never
> upload client material to a demo instance.

## Quick start — shared by a team

```bash
# 1. create an account for each person (prompts for the password)
python pipeline.py create-user --username jane --name "Jane Smith" --role admin
python pipeline.py create-user --username raj  --name "Raj Patel"

# 2. serve it to the team, with sign-in required
python pipeline.py review --host 0.0.0.0 --require-auth --secure-cookie
```

Colleagues open `http://<this-machine-ip>:8765/` and sign in.

**Collections are shared.** Everyone sees every collection, so a colleague can
pick up work. Each collection records who started it and who last exported it,
and the Team tab shows a live activity feed.

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
| `python pipeline.py collections` | list bundles and what is in them |
| `python pipeline.py bundle --docs 8,1,11 --name "Bundle A"` | build and export a bundle without the browser |
| `python pipeline.py users` | list accounts and how many documents each reviewed |
| `python pipeline.py audit` | show who changed what, and when |
| `python pipeline.py create-user …` | add an account |

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

- **No OCR yet.** Scans are detected, flagged and exported, but their contents
  are not read. Wiring in local Tesseract via `ocrmypdf` is the next task.
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
