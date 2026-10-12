"""Plain-language help content for the preparation console.

This module is the single source of truth for what the workflow is and what the
labels mean. The web UI renders it, so the instructions a user reads on screen
cannot drift from the documentation.

Written for someone who has never seen this pipeline: what it does, what to
click, and what happens next. There is deliberately no legal vocabulary here --
this stage prepares documents for Zibbit; it does not classify them.
"""

from __future__ import annotations

WORKFLOW = [
    {
        "n": 1,
        "title": "Copy documents into the drop folder",
        "body": (
            "There is a folder for new documents. Copy files into it - from your "
            "desk, from email, from a shared drive - and they are picked up "
            "automatically, usually within a few seconds. Nothing else to run. "
            "The folder can itself be a shared or synced folder, so a colleague "
            "can drop a file in from another computer."
        ),
    },
    {
        "n": 2,
        "title": "The pipeline reads and tags them",
        "body": (
            "Each file is converted to PDF, duplicates are collapsed, and the "
            "computer records what it can work out: the kind of document, its "
            "date, how many pages, and whether it is a scan it cannot read. This "
            "happens on its own."
        ),
    },
    {
        "n": 3,
        "title": "Scans are read automatically",
        "body": (
            "If a document is a scan or a photo, the text is read out of it so it "
            "can be searched and titled. This happens on this machine only. Each "
            "scan gets a quality rating so you know which ones to check by eye. "
            "The original scan is never altered."
        ),
    },
    {
        "n": 4,
        "title": "You tick the documents you want",
        "body": (
            "In the Library, tick the documents that belong together. Use the "
            "search and filters to find them. Ticking does not change anything "
            "on disk."
        ),
    },
    {
        "n": 5,
        "title": "You name the collection",
        "body": (
            "Choose '+ New collection' and give it the name you want the folder "
            "to have. That name becomes the folder, the cover document, and what "
            "your colleagues see. It waits here until you export it."
        ),
    },
    {
        "n": 6,
        "title": "Convert and export",
        "body": (
            "Only the documents you ticked are converted. The bundle is written "
            "to the finished folder with a COMPLETE marker, and it leaves your "
            "Collections list - what remains there is live work only. Anything "
            "that could not be converted is listed under 'Not included' rather "
            "than silently dropped."
        ),
    },
    {
        "n": 7,
        "title": "Import the PDFs into Zibbit",
        "body": (
            "Zibbit is fed PDFs, so the PDFs folder is the finished product - the "
            "files are already numbered in the order you set. The Word sheet is "
            "just a readable index for your own reference."
        ),
    },
]

GLOSSARY = [
    {
        "term": "Library",
        "help": (
            "Every document the pipeline knows about. This is where you tick the "
            "documents you want to use."
        ),
    },
    {
        "term": "Collection",
        "help": (
            "A bundle of documents you have named and intend to turn into an "
            "exhibit. The name becomes the folder. Collections are shared: "
            "everyone on the team can see and work on every collection."
        ),
    },
    {
        "term": "Convert",
        "help": (
            "Turning a file into a PDF. Word documents, spreadsheets, images and "
            "plain text all become PDFs. Files that are already PDFs are copied "
            "as they are."
        ),
    },
    {
        "term": "Bundle",
        "help": (
            "What you get after exporting: a folder holding a PDFs sub-folder, "
            "the contents list, and a Word index sheet."
        ),
    },
    {
        "term": "PDFs folder",
        "help": (
            "The numbered PDFs. This is the part that is imported into Zibbit. "
            "The files are already in the order you arranged them, so Zibbit sees "
            "the bundle in the right sequence."
        ),
    },
    {
        "term": "Index sheet",
        "help": (
            "A Word document listing everything in the bundle, in order. It is for "
            "your own reference and for the file record -- Zibbit does not need it."
        ),
    },
    {
        "term": "Not included",
        "help": (
            "Documents you ticked that could not be converted. They are listed "
            "with the reason so the gap is a deliberate, visible decision rather "
            "than a silent omission."
        ),
    },
    {
        "term": "Index",
        "help": (
            "The contents list of the bundle, also written as index.csv for use "
            "in a spreadsheet and manifest.json for other tools."
        ),
    },
    {
        "term": "Tag",
        "help": (
            "A short label on a document, such as 'witness' or 'exhibit B'. Some "
            "tags are filled in automatically; the ones you add are yours and are "
            "never overwritten."
        ),
    },
    {
        "term": "OCR",
        "help": (
            "Optical Character Recognition: reading the text out of a scan or "
            "photo. It runs on this machine, so scanned documents are never sent "
            "anywhere. The bundle still exports the original scan; a separate "
            "searchable copy is used for titles, dates and search."
        ),
    },
]

BADGES = [
    {
        "badge": "OCR NEEDED",
        "tone": "amber",
        "help": (
            "A scan or photo with no readable text. It still exports, but nobody "
            "has read its contents. Open the original before relying on it."
        ),
    },
    {
        "badge": "SKIPPED_NO_CONVERTER",
        "tone": "red",
        "help": (
            "No tool was available to convert this file, so what exists is a "
            "placeholder, NOT the real document. Install the missing converter "
            "and re-run, or it will be listed under 'Not included'."
        ),
    },
    {
        "badge": "N COPIES",
        "tone": "purple",
        "help": (
            "Several source files had identical content. They were collapsed into "
            "this one row so you do not add the same document twice."
        ),
    },
]

TIPS = [
    "Press F1 at any time for the full help, or use the Help button at the top.",
    "Tick documents, then name the collection. The black bar appears as soon as you tick anything.",
    "The order of documents in a collection is set by where they were added. Use the arrows inside a collection to reorder.",
    "A document can be in more than one collection, and can be called something different in each.",
    "Leave the 'Name in this bundle' box empty to use the document's own title.",
    "A collection can be exported as many times as you like. Each export rebuilds the folder from scratch.",
    "Your tags are yours and are preserved when the pipeline re-reads the documents.",
    "If a scan was read badly, 'Re-read all' on the Library tab tries again at full quality.",
    "Documents edited at the same time by two people are never silently overwritten. You are asked which version to keep.",
    "Exported bundles move to the finished folder and leave this list. Nothing is deleted.",
]

# The console no longer assigns legal schedules, so these are not offered.
# Kept out deliberately: this stage prepares bundles, it does not classify them.


def as_dict() -> dict:
    return {
        "workflow": WORKFLOW,
        "glossary": GLOSSARY,
        "badges": BADGES,
        "tips": TIPS,
        "reference": REFERENCE,
    }


# ---------------------------------------------------------------------------
# The full reference, shown in the console's Help window.
#
# Plain text with a little markup so it reads well without a Markdown library:
#   "## "  section heading
#   "- "   bullet
#   "1. "  numbered step
#   "> "   highlighted note
#   **bold** and `code`
# ---------------------------------------------------------------------------

REFERENCE: list[dict] = [
    {
        "id": "start",
        "title": "Getting started",
        "body": """
## The short version

1. Copy documents into the **drop folder**.
2. They appear in the **Library** on their own.
3. Tick the ones you want, and give the bundle a name.
4. Click **Convert and export**.
5. Import the **PDFs** folder into Zibbit.

Nothing else is required. You never have to run a command while using the
console.

## Where the drop folder is

The exact path is shown in the banner at the top of the Library tab, under
"Watching for dropped files". It is normally:

`intake/incoming`

Sub-folders work, so you can keep your own structure.

> **Your file is copied, never moved.** It stays exactly where you put it.
""",
    },
    {
        "id": "library",
        "title": "The Library",
        "body": """
## What it is

Every document the program knows about. This is where you tick the ones you want
in a bundle.

## The columns

- **Document**: the name worked out from the file's contents.
- **Type**: invoice, letter, pleading, and so on.
- **Date**: taken from the document, or from its file name.
- **Pages**: page count.
- **Text quality**: how confidently a scan was read.
- **Status**: whether it is ready as a PDF.
- **Tags**: your own labels, plus a few added automatically.
- **In collections**: which bundles it is already part of.

## Text quality

Only meaningful for scans and photos, which have no text inside them until they
are read.

- `good 96%`: read confidently. Nothing to do.
- `check 72%`: read roughly. Check dates and figures against the image.
- `verify 41%`: read poorly. Check the document by eye before relying on it.
- `no text`: nothing readable was found. It may be blank or a poor image.
- `not read`: OCR has not been run on it yet.

Use the **Scans to check by eye** filter to list everything needing a human
look. The program says this rather than pretending a bad scan was read well.

## Paging and searching

- **Show** narrows the list to a category.
- **Search** matches names, types, dates and tags.
- The **pager** at the top moves between pages, 50 documents per page.

## Tags

Type in the box under a document and press Enter. Write `witness: M. Reed` to set
a tag called `witness`. Tags you add are yours and are never overwritten, even
when the program re-reads the documents.
""",
    },
    {
        "id": "collections",
        "title": "Collections and bundles",
        "body": """
## What a collection is

A bundle you name. The name becomes the folder, so choose something a colleague
would recognise.

## Making one

1. Tick documents in the **Library**.
2. A black bar appears at the bottom. Choose **+ New collection**.
3. Give it a name, and a description if you like.
4. Click **Create and convert**.

## Reordering

Order is set by the order you added things. Use the **up and down arrows** inside
a collection to change it, then export again.

## Naming a document inside a bundle

Each row has a **Name in this bundle** box. Change it to have the document appear
differently in that bundle. Leave it empty to use the document's own title.

**This affects only that one bundle.** The same document can be called something
different elsewhere, and its original file is never renamed.

## Collections are shared

Everyone signed in can see and work on every collection. Each records who started
it and who last exported it. The **Team** tab shows a live activity feed.

> **If two people edit at once**, the second save is refused and both versions
> are shown, so you choose. Nothing is overwritten without you agreeing.

## What you get on export

- **PDFs/**: the numbered documents. **This is what goes into Zibbit.**
- **index.csv** and **manifest.json**: the contents list for other tools.
- **00 - Index.docx**: a readable index sheet for your own reference.
- **COMPLETE**: written last, with a fingerprint of everything else.

Exported bundles move to `output/collections/finished/` and leave the Collections
list, so what you see there is live work only. **Nothing is deleted.**
""",
    },
    {
        "id": "scans",
        "title": "Scanned documents and OCR",
        "body": """
## Why scans need reading

A scan or photo has no text inside it, so nothing can search it or work out its
date. OCR reads the text out of the image.

**It runs on this computer.** Tesseract is a local program. No cloud service, no
API keys, no account. Scanned documents never leave the machine.

## If it is not installed

Install it, then restart the app:

`winget install UB-Mannheim.TesseractOCR`

Other systems: `sudo apt install tesseract-ocr` or `brew install tesseract`.

## Reading scans again

The panel on the Library tab reads anything not yet read. To re-read everything,
including scans that were already read, use **Re-read all**.

To do the same from a terminal:

- `python pipeline.py ocr`
- `python pipeline.py ocr --force`
- `python pipeline.py ocr --lang eng+fra --dpi 300`

## The original is never altered

A scanned page is evidence, and a re-rendered version of it is not the same
exhibit. OCR writes a **separate searchable copy**, used only for titles, dates
and searching. The PDFs folder in your bundle still contains the original scan.

## French, or other languages

Install the extra language data, then add to `affidavit.config.json`:

`{ "ocr_lang": "eng+fra" }`

Check what is available with `tesseract --list-langs`. A language that is not
installed falls back to English and says so.

## How well it works

- A clean 300 dpi scan: around 96 percent confidence, date and type correct.
- A poor phone photo: around 64 percent, though key fields are usually still
  recovered.
- A blank page: reports "no text" rather than inventing something.

Dates survive common scanning damage. `202404-12` and `20240412` are both read as
`2024-04-12`, while `20241350` is rejected because month 13 is impossible.
""",
    },
    {
        "id": "formats",
        "title": "File formats and conversion",
        "body": """
## What becomes a PDF

- **Word, Excel, PowerPoint, RTF, ODF**: converted using LibreOffice.
- **Plain text** (.txt, .md, .csv): converted by the program itself.
- **Images** (PNG, JPG, TIFF, HEIC and others): one page each.
- **PDFs**: copied through unchanged.
- **Anything else**: listed as unsupported, with a reason.

## Word documents need LibreOffice

`winget install TheDocumentFoundation.LibreOffice`

Without it, Word and Excel files become a clearly marked **placeholder**, not the
real document. They are kept out of bundles and listed under **Not included**, so
a placeholder can never be handed over by accident.

Plain text needs nothing extra.

## "Not included"

Documents you ticked that could not be converted. They are reported with the
reason in the console, the Word sheet, the index and the manifest.

This is deliberate. A half-converted document inside a bundle would be worse than
a gap you can see.
""",
    },
    {
        "id": "duplicates",
        "title": "Duplicate documents",
        "body": """
## How duplicates are found

By the **text inside** the document, not its name or its bytes. That matters: the
same letter saved twice by Word, or exported to PDF and then photographed, is the
same document and is treated as one.

A combined row shows `N COPIES`. The reconciliation report names every original
path, so nothing is lost track of.

## Near duplicates

Documents that differ only slightly, by a signature block for example, are
combined only when both the text and the significant words closely match. Those
are labelled **"near-identical text, confirm it is the same instrument"**.

The program should not be the last word on whether two documents are the same.
If it matters, check.
""",
    },
    {
        "id": "accounts",
        "title": "Accounts and people",
        "body": """
## Signing in

Sign-in is optional. On one computer it is off by default and everything is
attributed to "local".

To give each person their own sign-in, start the app with accounts. The
`start-windows.bat` launcher does this already.

## The first account

**Whoever opens the Welcome page first becomes the administrator.** On a machine
reachable from the network, set it up before sharing the address.

## Managing people

An **administrator** opens the **Team** tab and can:

- Add a colleague, as Reviewer or Administrator.
- Reset a forgotten password.
- Disable someone who has left. They are signed out at once. Their work and the
  record of what they did are kept, and they can be re-enabled.
- Change their own password.

A **Reviewer** can work on documents but cannot manage accounts.

Every one of these is written to the activity record.

## Forgotten passwords

Three ways back in, and which one applies depends on who you are.

- **You can still sign in**: use **Change my password** on the Team tab.
- **Somebody else can help**: an administrator uses **Reset password** on the
  Team tab.
- **You are the only administrator and you are locked out**: use your
  **recovery code**.

The recovery code is issued when the account is created and shown **once**, on a
page that asks you to write it down. It is stored hashed, like a password, so
nobody can look it up later.

If you forget your password, use **Forgotten your password?** on the sign-in page.
It asks for your username, the code and a new password. Dashes and spaces in the
code do not matter.

- A code **works once**, then it is cleared. A piece of paper that turns up later
  is worthless.
- To replace one, use **Recovery code** on the Team tab. An administrator can
  issue one for anybody; anyone can issue one for themselves. A new code replaces
  the old one.
- **Keep it somewhere other than this machine.** A code in a file on the same
  computer is no help if that computer is what you cannot reach.

## Sharing with colleagues

**Same office**: use the `share-windows.bat` launcher. It prints an address such
as `http://10.33.38.26:8765/`. Colleagues need nothing installed.

**Somewhere else**: an address beginning `10.` or `192.168.` only exists inside
one building and cannot work from outside it. Both sides need a private network
between their computers. Tailscale is the easy answer, is free for small teams,
and needs no changes to your router.

> **Do not forward a port from the internet to this program.** It speaks plain
> HTTP, so passwords would cross the internet unprotected.
""",
    },
    {
        "id": "privacy",
        "title": "Privacy and where files live",
        "body": """
## Nothing leaves the machine

The program makes no network calls. No cloud service, no API keys, no telemetry.
Converting, reading scans, hashing and indexing all happen locally. You can
unplug the network and it still works.

## Your originals are not touched

Files are copied into the library, never moved or renamed. Nothing in
`intake/source` is ever modified.

## If the drop folder is inside OneDrive, Dropbox or Google Drive

The console warns you, because documents placed there are being copied to that
service. That may be exactly what you want, sharing a folder with a colleague for
example, but it should be a decision rather than an accident.

## Where everything lives

- `intake/incoming`: copy new documents here.
- `intake/source`: the library, your originals. **Never delete these.**
- `intake/rejected`: notes about files that could not be read.
- `work`: derived files and the database. Can be rebuilt if lost.
- `output/collections`: bundles in progress.
- `output/collections/finished`: exported bundles, ready for Zibbit.
- `output/reports`: the reconciliation report.
""",
    },
    {
        "id": "assurance",
        "title": "Checking nothing was missed",
        "body": """
## The reconciliation report

The single most useful check. It proves that every file which arrived is
accounted for: converted, combined with a duplicate, or named as unsupported with
a reason.

It writes a readable report to `output/reports/reconciliation.md` and a
file-by-file trace to `output/reports/traceability.csv`.

It also reports documents that could not be converted, scans never read or that
yielded nothing, and unsupported formats.

**Run it before relying on a bundle.** It answers "did anything get lost?", which
is the question that matters.
""",
    },
    {
        "id": "team",
        "title": "Working as a team, from anywhere",
        "body": """
## One shared folder

If everyone drops documents into one place, point the watcher at it. On the drop
folder panel use **Use a shared folder**, then **Browse...** or type the path.

- **On this computer**: `D:\\Shared documents`
- **On the network**: `\\\\server\\share\\documents`, or a mapped drive such as `Z:\\Scans`
- **A synced service**: the local folder it syncs to, such as
  `C:\\Users\\you\\OneDrive - Firm\\Intake`

Sub-folders are watched too. Files are copied, never moved, so the shared folder
is left exactly as it was.

## The central machine

For a team, the weak point is running this on somebody's laptop: close the lid and
it stops for everyone. Put it on a desktop that stays on.

1. Install Python, LibreOffice and Tesseract on that machine.
2. Start it once and **create the administrator account straight away**, because
   whoever opens the Welcome page first becomes the administrator.
3. Set the shared folder from the drop folder panel.
4. Add everyone on the **Team** tab.
5. Install Tailscale on that machine and on every colleague's computer, signed in
   to the same account, then run `share-windows.bat`.

## Reaching it from another place

Tailscale builds a private encrypted network between your machines, so no port
needs opening on your router and nothing is exposed to the internet.

Install it on the machine running the app and on each person's computer, signed
in to the same account. Then `share-windows.bat` prints two addresses:

```
Tailscale (works anywhere) http://100.70.246.36:8765/
Same office / same wifi    http://192.168.146.58:8765/
```

**Send the one labelled "works anywhere".** It begins `100.` and works from any
location. The other only works inside the building.

> **Do not use `--secure-cookie` with Tailscale.** That flag sends the sign-in
> cookie only over HTTPS, and Tailscale gives you a plain `http://` address, so
> nobody would be able to sign in.

> **Never forward a port from the internet to this app.** It speaks plain HTTP, so
> passwords would cross the internet unprotected.

## Several people at once

Everything is shared: one Library, one set of collections, one activity record.
Everyone signed in sees the same thing, and each person has their own session, so
signing out on one computer does not affect anybody else.

**When two people touch the same bundle**, the one whose save is based on an
older version is refused and shown the current value, so they can decide what to
keep. Nothing is overwritten without agreement. Adding documents at the same time
is safe: adding the same one twice does nothing.

To avoid it entirely, give each person their own collection for their part and
combine later. Use tags to mark progress, since tags you add are never
overwritten.

Comfortable for about **ten people working at once**. Beyond that the database
wants changing to something built for more writers.

## Backups

Back up **`work`** and **`intake`** together. `work` holds the record of what has
been processed, the review decisions and the account list; `intake` holds the
documents. `output` can be rebuilt from a collection whenever you need it.
""",
    },
    {
        "id": "limits",
        "title": "What this program will not do",
        "body": """
## Deliberate limits

Worth knowing, so you do not wait for something that was never going to happen.

- **No internet, ever.** No cloud, no accounts, no telemetry.
- **No Zibbit integration.** Zibbit is a Word add-in on the lawyer's computer.
  This prepares the PDFs it needs. The last step happens on their machine.
- **No decisions about documents.** It converts, names, orders and reports. What
  belongs in a bundle is your call.
- **No handwriting**, reliably. Nothing reads text out of photographs of screens
  well. A poor scan stays poor.
- **No SharePoint or Google Drive connection.** Documents are read from the drop
  folder, which can itself be a folder those services sync.
- **No more than about ten people working at once.** Beyond that the database
  needs changing.
""",
    },
]
