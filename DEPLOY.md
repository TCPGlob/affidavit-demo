# Deploying a demo

How to put this in front of a client so they can decide whether they want it.

---

## Read this first: what a demo can and cannot show

**Zibbit is a Microsoft Word add-in running on the user's own desktop.** It is
not a service that accepts uploads. That has a consequence you need to
understand before promising anything:

> A cloud-hosted demo can show the *pipeline* — ingest, tagging, tick, name,
> convert, bundle. It **cannot** complete the Zibbit step, because Zibbit runs
> on the lawyer's machine, not on your server.

So the demo proves the part you are actually selling: **the bundle that lands on
the lawyer's desk is correct, ordered, and complete.** The last click happens
locally, exactly as it will in production. Say this out loud during the demo
rather than letting them discover it.

**The production shape is therefore:**

| Where | What runs there |
|---|---|
| The firm's own machine or private server | the pipeline and the console |
| The lawyer's desktop | Word + Zibbit, consuming the `PDFs` folder |
| Nowhere | any third party — the pipeline makes no network calls |

The demo instance is for *showing* the workflow. Production should run on their
own infrastructure.

---

## Option 1 — demo on your own laptop (simplest, best for a screen share)

Nothing to deploy. One command:

```bash
python pipeline.py review --demo
```

That creates synthetic documents, runs the pipeline over them, and opens the
console at <http://127.0.0.1:8765/> with sign-in disabled. You get a fully
populated tool to click through in about ten seconds.

For a screen-share call this is the best option: no hosting, no credentials, no
risk of client data touching a server.

```bash
# if you want colleagues to follow along on the same network
python pipeline.py review --demo --host 0.0.0.0
```

The server prints a warning when bound to `0.0.0.0` without authentication. That
is fine for a demo on a trusted network; do not do it on a public one.

---

## Option 2 — GitHub Codespaces (a link you can send)

Good when you want the client to click around themselves without installing
anything.

```bash
# 1. push the repo (see "Getting it onto GitHub" below)
# 2. create a Codespace on the repo
# 3. in the Codespace terminal:
python -m pip install pymupdf pillow openpyxl
python pipeline.py review --demo --host 0.0.0.0 --port 8765
# 4. Codespaces forwards port 8765 - make the port Public and copy the URL
```

**Set the port visibility to Public** so the client can reach it, or share the
private URL with them.

> ⚠️ A Codespace is a real internet-facing host. Run it in **demo mode with
> synthetic data only**. Never upload client documents to it. Read the notice in
> the console every time it starts.

A `.devcontainer/devcontainer.json` is included so the environment is ready when
the Codespace opens.

---

## Option 3 — Docker on any VM (closest to production)

```bash
docker build -t aod .
docker run -d --name aod-demo -p 8080:8765 aod \
  python pipeline.py --root /data review --demo \
  --host 0.0.0.0 --port 8765 --no-browser
```

Then put a reverse proxy with TLS in front. For a demo on a throwaway VPS that is
acceptable; for anything with real documents, see the production run below.

### Production run

```bash
# create the first account (users live in the mounted volume)
docker run --rm -v aod-data:/data aod \
  python pipeline.py --root /data create-user \
  --username jane --name "Jane Smith" --role admin

# run, bound to loopback only, with TLS in front and sign-in required
docker run -d --name aod -p 127.0.0.1:8765:8765 -v aod-data:/data aod
```

The default `CMD` already includes `--require-auth` and `--secure-cookie`. Bind
to `127.0.0.1` and let a reverse proxy (Caddy, nginx, IIS) terminate TLS — or
better, keep it on a VPN/Tailscale and skip the public internet entirely.

---

## Getting it onto GitHub

This folder is not yet a git repository. To publish it:

```bash
cd affidavit-poc

# verify nothing sensitive would be committed BEFORE the first commit
git init
git add .
git status            # intake/, work/, output/ must NOT appear
git commit -m "Document preparation pipeline for Zibbit"

git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

**The `.gitignore` excludes `intake/`, `work/`, `output/` and
`affidavit.config.json`.** The CI workflow asserts this on every push, so a
mistake fails the build rather than publishing client material. Run
`git status` and read it before your first commit anyway — once client documents
are in git history, they are extremely hard to remove.

If you have already run the pipeline locally, `git status` should show only
source files, docs, `Dockerfile` and `.github/`.

---

## What the CI does

`.github/workflows/tests.yml` runs on every push, on **both Linux and Windows**
(Windows matters: the team runs Word there, and path handling is the most likely
thing to break).

It installs LibreOffice and Tesseract on Linux, runs the pipeline end to end,
runs all four test suites, builds a bundle, and then **fails the build if
`intake/`, `work/`, `output/` or `affidavit.config.json` are not git-ignored.**

---

## Demo script

A five-minute walkthrough that lands the point:

1. **The Library** — "this is everything that arrived, already converted to PDF
   and tagged with type, date and page count. Duplicates were collapsed."
   Point at the `2 COPIES` badge on the invoice.
2. **Tick three or four documents.** Show the black bar appear.
3. **Create a collection** and name it. "That name becomes the folder."
4. **Convert & export.** The result panel appears with the bundle path.
5. **Open the folder in Explorer.** Show `PDFs/`, the numbered files, the Word
   index, and `index.csv`.
6. **Open the Word index** — it lists everything in order with dates and pages.
7. **Import the PDFs into Zibbit.** This is the part that happens on their
   machine; say so.
8. **Show the audit trail** on the Team tab, and reorder a document with the
   arrows, then re-export, to prove the order is theirs to control.

### The two questions they will ask

**"What if it gets a document wrong?"**
It never decides anything. Conversion, naming, ordering and numbering are
mechanical. If a document cannot be converted it is listed under **Not
included** with the reason — visibly, in the console, the Word sheet, the CSV
and the manifest — instead of silently vanishing.

**"What about confidentiality?"**
Nothing leaves the machine. There are no API keys, no cloud calls, no model
providers. Conversion and hashing are local operations. Say this plainly; it is
the strongest thing you have, and it is verifiable — you can switch off the
network and the demo still works. Prove that live if you can.

---

## Known limits to be upfront about

- **No OCR yet.** Scans are detected, flagged `OCR NEEDED` and exported, but
  their contents are not read. Install Tesseract and this becomes the next task.
- **SQLite with a single write lock.** Fine for a handful of people. Past roughly
  ten concurrent editors, move to Postgres.
- **No SharePoint/Drive connector.** Documents are read from the intake folder.
- **Conflicting edits are detected, not merged.** If two people edit the same
  field, the second is told and chooses. Nothing is silently lost, but it is not
  real-time collaboration either.
