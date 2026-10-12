# Help

Everything the program does, what each part means, and how the pieces fit
together.

For getting started, see [QUICKSETUP.md](QUICKSETUP.md). When something is not
working, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## What this program is for

It takes a folder of mixed documents (Word files, spreadsheets, PDFs, scans,
photos, emails) and turns them into **numbered PDF bundles that are ready to
import into Zibbit**.

You do not have to convert anything by hand, rename anything, work out what order
things go in, or check that nothing was missed. Those are the parts it does.

**What it does not do:** it does not decide what belongs in a bundle, and it does
not talk to Zibbit. Zibbit is a Word add-in on the lawyer's own computer. This
program's job ends at handing it a clean, ordered folder of PDFs.

---

## The five parts

| Part | What it does |
|---|---|
| **Drop folder** | Watches a folder. Files you copy in are picked up automatically. |
| **Library** | Everything that has been received, converted and read. |
| **Collections** | Named bundles you build by ticking documents. |
| **Bundle** | The exported result: numbered PDFs, an index, and a marker. |
| **Finished folder** | Where exported bundles go, out of your way. |

---

## The drop folder

```
intake/incoming/
```

Copy documents in here. Within a few seconds they are copied into the library,
converted to PDF, read, and listed in the console. **You do not run anything.**

**Sub-folders work.** Keep your own structure and it is preserved.

### Things worth knowing

**Your file is copied, never moved.** It stays exactly where you put it. The
program never deletes or renames your documents, and a failed copy cannot lose
the only copy you have.

**A file is only taken once it stops changing.** Copying a large scan takes time.
Ingesting half of one would be worse than waiting.

**These are ignored on purpose:** `.crdownload`, `.part`, `.tmp`, `.lock`, `~$`
files, and anything starting with a dot. They are half-written, not documents.

**If the drop folder is inside OneDrive, Dropbox or Google Drive, the console
warns you.** Documents placed there are being copied to that service. That may be
exactly what you want, sharing a folder with a colleague for example, but it
should be a decision rather than an accident.

**The drop folder can be a shared folder** so a colleague can drop a file in from
another computer. See [One shared folder for the whole team](#one-shared-folder-for-the-whole-team).

### If a file cannot be read

A note is written to `intake/rejected/` explaining why. **Your original is left
alone.** Nothing is deleted.

---

## One shared folder for the whole team

If everyone drops documents into one place, point the watcher at that folder
instead of the local default. Anything anyone puts there is picked up on its own,
exactly as before.

**In the console:** the drop folder panel has a **Use a shared folder** button.
Use **Browse...** to pick the folder, or type the path. The setting is saved, so
it still applies after a restart.

### What the folder can be

| Where it lives | What to give it |
|---|---|
| On this computer | `D:\Shared documents` |
| On the network | `\\server\share\documents`, or a mapped drive such as `Z:\Scans` |
| Inside OneDrive, Dropbox or Google Drive | The local folder it syncs to, such as `C:\Users\you\OneDrive - Firm\Intake` |
| A NAS | Its UNC path, or a mapped drive letter |

### Why this works across a network

The watcher **reads the folder** rather than subscribing to filesystem events.
That is deliberate:

- It works on network shares and on folders synced by other software, where
  filesystem notifications are unreliable or absent.
- It survives a dropped connection. If the share goes away and comes back, the
  next check finds it and carries on. No restart, no error.
- It waits until a file stops changing, so a colleague's slow copy is never
  ingested half-finished.

The cost is that a drop takes a few seconds rather than being instant. Within a
team workflow that is not noticeable.

### Things worth knowing

**Sub-folders are watched too.** People can keep their own structure inside the
shared folder, and it is preserved in the Library, so you can still tell where a
document came from.

**Your files are copied, never moved.** The shared folder is left exactly as it
was, so nobody's copy disappears.

**A folder that cannot be reached is refused, not accepted.** If you give a path
that does not exist and cannot be created, or that cannot be written to, the
console says so. This matters for a network share that has dropped out, because
it otherwise looks like a perfectly normal path.

**The folder chooser only works on the computer running the app.** A dialog
cannot be opened on somebody else's screen, so a colleague connecting over the
network is told to type the path instead.

**If the shared folder is inside OneDrive, Dropbox or Drive, the console warns
you.** Documents placed there are being copied to that service. That may be
exactly what you want, but it should be a decision rather than an accident.

### Running it on a machine that stays on

For a team, the weak point is running the app on somebody's laptop: close the lid
and it stops. Put it on a desktop that stays on, or a small always-on machine,
and point it at the shared folder. Then nobody has to think about it.

---

## Several people working at once

Everything is shared. There is one Library, one set of collections and one
activity record, and everyone signed in sees the same thing.

### What each person needs

| | |
|---|---|
| Their own account | Created by an administrator on the **Team** tab |
| A role | **Reviewer** to do the work, **Administrator** also to manage people |
| The address | Sent to them once. Nothing to install |
| A browser | Any current one |

Each person gets their **own session**, so signing out on one computer does not
affect anybody else, and nobody can act as somebody else.

### Two people editing the same bundle

This is handled, and the handling is worth knowing because it is deliberate.

Each bundle carries a version number. When you save, the app checks that the
version you were looking at is still the current one:

- **If nobody else has changed it**, your change is saved.
- **If somebody has**, your save is refused and you are shown the current value,
  so you can decide what to keep. Nothing is overwritten without you agreeing.

So the worst that happens is that one person is asked to look again. The thing
that must never happen, two people silently overwriting each other, cannot.

Adding documents is safe to do at the same time from two computers. Adding the
same document twice is a no-op, so two people tidying the same bundle cannot
create duplicates.

### What everyone can see

- The **Library**, which is the same for the whole team
- Every **collection**, including who started it and who last exported it
- The **Team** tab, showing who is signed in and a live activity feed
- **Exported bundles**, so a bundle that has left the working list can still be
  found

### A sensible way to divide work

- Give each person their own collection for the part they are assembling, then
  combine. Version conflicts only arise when two people edit the *same* bundle.
- Use **tags** to mark progress or ownership. Tags you add are never overwritten,
  even when the pipeline re-reads the documents.
- Export when a bundle is finished. It leaves the working list, which keeps the
  console showing live work only.

### Rough limits

The design is comfortable for a team of about **ten people working at once**.
Beyond that the database wants changing to something built for more writers.
For a firm-sized matter this is not a constraint.

---

## Working from anywhere: Tailscale

You do not need to open a port on your router, and you should not. Tailscale
builds a private encrypted network between your machines, so the central machine
can be reached from a home office or another city as though it were on the same
desk.

### Setting it up

On the **machine that runs the app**:

1. Install Tailscale: `winget install Tailscale.Tailscale`
2. Sign in. Use the same account you will use on the other machines, because
   only machines on your own network can reach each other.

On **each person's computer**:

3. Install Tailscale from https://tailscale.com and sign in to that same account.

Then, on the machine that runs the app, double-click **`share-windows.bat`**. It
prints the address to give people:

```
  Tailscale (works anywhere) http://100.70.246.36:8765/
  Same office / same wifi    http://192.168.146.58:8765/
```

**Give them the one labelled "works anywhere".** It starts with `100.`, which is
the Tailscale address, and it works from any location.

You can also run it by hand:

```
python pipeline.py share
python pipeline.py review --users --host 0.0.0.0
```

### Using it day to day

The machine that runs the app must be **on** and the app must be **running**.
Everything else is ordinary browser use.

- People open the `100.` address and sign in.
- Documents they drop into the shared folder are picked up on the central
  machine, whoever dropped them.
- Bundles are shared in the ordinary way.

### Things to get right

**Do not use `--secure-cookie`.** That flag tells the browser to only send the
sign-in cookie over HTTPS. Tailscale gives you a private encrypted network but a
plain `http://` address, so with that flag set **nobody could sign in**. The
console says HTTPS if it means HTTPS, and with Tailscale it does not.

**Never forward a port from the internet to this program.** It speaks plain HTTP,
so passwords would cross the internet unprotected. Tailscale exists to avoid
needing that.

**Use a machine that stays on.** If it is a laptop that gets closed, the app
stops and nobody can reach it. A desktop in the office is the right place.

**Sign-in must be on.** Always run with accounts when more than one person can
reach the address, which `share-windows.bat` and `start-windows.bat` both do.
Without it, anyone who can reach the address can read every document.

### What has been verified

Tested over a real Tailscale address with three people signed in at once as
separate sessions, one of them on the machine itself and two reaching it through
the Tailscale address:

- all three signed in and received their own session
- a made-up session token was refused
- all three saw the same shared folder and the same library
- five documents copied in by three people at the same time were all ingested
- two people editing one bundle: one saved, the other was told there was a
  conflict and shown the current value
- two people adding documents at the same time created no duplicates
- one person exported; all three then found the bundle under exported bundles
  and no longer in progress
- a write from a foreign website was refused
- every dropped file was still in the shared folder, unmodified
- signing out on one computer did not affect the other two

**What this does not prove:** that your particular network routes correctly, or
that a machine three thousand miles away feels quick. Reachability depends on
Tailscale, which is their job rather than this program's.

---

## The Library

Every document the program knows about. This is where you tick the ones you want
in a bundle.

### The columns

| Column | Meaning |
|---|---|
| **Document** | The name worked out from the file's contents |
| **Type** | Invoice, letter, pleading, and so on |
| **Date** | Taken from the document, or from its file name |
| **Pages** | Page count |
| **Text quality** | How confidently a scan was read |
| **Status** | Whether it is ready as a PDF |
| **Tags** | Your own labels, plus a few added automatically |
| **In collections** | Which bundles it is already part of |

### Text quality

Only meaningful for scans and photos, which have no text inside them until they
are read.

| Shown | Meaning |
|---|---|
| `text` | A normal document. It had readable text already. |
| `good 96%` | A scan that was read confidently. |
| `check 72%` | Read roughly. Check dates and figures against the image. |
| `verify 41%` | Read poorly. Check the document by eye before relying on it. |
| `no text` | Nothing readable was found. It may be blank or a poor image. |
| `not read` | OCR has not been run on it yet. |

Use the **"Scans to check by eye"** filter to list everything that needs a human
look. This is the program being honest rather than pretending a bad scan was
read well.

### The labels you will see

| Label | Meaning |
|---|---|
| `OCR NEEDED` | A scan whose contents have not been read |
| `SKIPPED_NO_CONVERTER` | No tool was available to convert it. **What exists is a placeholder, not the real document.** |
| `N COPIES` | Several files had the same content and were combined into one row |
| `suggested: ...` | Privilege wording was spotted in the text. A hint, not a decision. |

### Filtering and searching

- **Show** narrows the list to a category.
- **Search** matches names, types, dates, and tags.
- The **pager** at the top moves between pages: 50 documents per page.

### Tags

Type in the box under a document and press Enter. Write `witness: M. Reed` to set
a tag called `witness`. Just `exhibit B` sets a tag called `exhibit B`.

**Tags you add are yours and are never overwritten**, even when the program
re-reads the documents.

---

## Collections

A collection is a bundle you name. The name becomes the folder, so choose
something a colleague would recognise:

```
Harbourview Exhibit Bundle
Service Documents, September
Smith v Jones, Volume 1
```

### Making one

1. **Library tab.** Tick the documents that belong together.
2. A black bar appears at the bottom. Choose **+ New collection**.
3. Give it a name and, optionally, a description.
4. **Create & convert.**

### Reordering

The order is set by the order you added things. Use the **up and down arrows**
inside a collection to change it, and re-export when the order is right.

### Naming a document inside a bundle

Each row has a **Name in this bundle** box. Change it to have the document
appear differently in that bundle. Leave it empty to use the document's own
title.

**This only affects that one bundle.** The same document can be called something
different in another collection, and its original file is never renamed.

### Collections are shared

Everyone signed in can see and work on every collection. Each one records who
started it and who last exported it. The **Team** tab shows a live activity feed.

### If two people edit at once

Each editable row keeps a version. When you save, you send the version you were
looking at. If someone changed it since, **your save is refused** and you are
shown both versions to choose between. Nothing is overwritten without you
agreeing.

Adding the same document twice is harmless: it is a no-op, so two people tidying
the same bundle cannot create duplicates.

---

## Exporting a bundle

**Convert & export** turns the collection into a finished bundle.

Only the documents you ticked are converted. Anything that could not be converted
is listed under **Not included** with the reason, in the console, the Word sheet,
the index and the manifest.

### What you get

```
output/collections/finished/<Your Name>/
    PDFs/                            <- import THIS into Zibbit
        001 - Engagement Letter.pdf
        002 - Statement of Claim.pdf
        003 - Demand Letter.pdf
    index.csv                        contents list for a spreadsheet
    manifest.json                    the same, for other tools
    00 - <Your Name> - Index.docx    readable index sheet
    COMPLETE                         written last, carries a fingerprint
```

**The `PDFs` folder is the product.** Its files are already numbered in the order
you set, so Zibbit sees the bundle in the right sequence. The Word sheet is a
convenience for reading; Zibbit does not need it.

### The COMPLETE marker

Written **last**, and contains a fingerprint of every other file in the bundle.

Any other tool should wait for this file before using a bundle: its absence means
the bundle was still being written. The fingerprint also means a later change to
a bundle is detectable.

### Exported bundles leave the console

Exporting moves the bundle to `finished/` and takes it out of the Collections
list, so what you see there is live work only. **Nothing is deleted.** Open the
folder to find it.

### Exporting again

Exporting the same collection again rebuilds the bundle in place. Use this after
changing the order or adding documents.

---

## Formatting and conversion

### What gets converted

| Input | Becomes |
|---|---|
| Word (.doc, .docx), Excel, PowerPoint, RTF, ODF | PDF, using LibreOffice |
| Plain text (.txt, .md, .csv) | PDF, built in |
| Images (PNG, JPG, TIFF, HEIC, and others) | PDF, one page each |
| PDFs | Copied through unchanged |
| Anything else | Listed as unsupported, with a reason |

### Word documents need LibreOffice

```
winget install TheDocumentFoundation.LibreOffice
```

Without it, Word and Excel files become a clearly marked **placeholder**, not the
real document. They are kept out of bundles and listed under **Not included**, so
a placeholder can never be handed over by accident.

### Plain text needs nothing

Text files are converted by the program itself, so they work even without
LibreOffice.

---

## Reading scans (OCR)

Scans and photographs contain no text, so nothing can search them or work out
their date. OCR reads the text out of the image.

**It runs on this computer.** Tesseract is a local program. No cloud service, no
API keys, no account. Scanned documents never leave the machine.

### Installing it

```
winget install UB-Mannheim.TesseractOCR
```

Other systems: `sudo apt install tesseract-ocr` (Debian/Ubuntu) or
`brew install tesseract` (macOS).

### Running it

It runs automatically as part of the pipeline. To run it on its own, or to
re-read scans at full quality:

```
python pipeline.py ocr
python pipeline.py ocr --force
python pipeline.py ocr --lang eng+fra --dpi 300
```

The Library tab has the same thing as buttons.

### The original is never altered

A scanned page is evidence, and a re-rendered version of it is not the same
exhibit. So OCR writes a **separate searchable copy**, used only for titles,
dates and searching. The PDFs folder in your bundle still contains the original
scan.

### French, or other languages

Install the extra language data, then set it in `affidavit.config.json`:

```json
{ "ocr_lang": "eng+fra" }
```

Check what is available with `tesseract --list-langs`. A language that is not
installed falls back to English and says so.

### How well it works

Measured on the sample documents:

| Document | Result |
|---|---|
| A clean 300 dpi scan | 96 percent confidence, date and type correct |
| A poor photo of a receipt | 64 percent, key fields still recovered |
| A blank page | Reports `no text` rather than inventing something |

Dates survive common scanning damage: `202404-12` and `20240412` are both read as
`2024-04-12`, while `20241350` is rejected because month 13 is impossible.

---

## Duplicate documents

The program combines documents with the same content, so you do not review the
same thing twice.

It works on the **text inside** the document, not its name or its bytes. That
matters: the same letter saved twice by Word, or exported to PDF and then
photographed, is the same document and is treated as such.

A combined row shows `N COPIES`, and the reconciliation report names every
original path so nothing is lost track of.

Near-duplicates, which differ only by a signature block for example, are combined
only when both the text and the significant words closely match. Those are
labelled **"near-identical text, confirm it is the same instrument"**, because
the program should not be the last word on whether two documents are the same.

---

## Accounts and sign-in

Sign-in is optional. On one computer it is off by default, and everything is
attributed to "local".

To give each person their own sign-in:

```
python pipeline.py review --users
```

or double-click `start-windows.bat`.

### The first account

The first person to open the Welcome page creates the administrator account.
**Whoever gets there first becomes the administrator.** On a machine reachable
from the network, set it up before sharing the address.

Setup is only possible while no accounts exist, so that door closes behind you.

### Managing people

An **administrator** opens the **Team** tab and can:

- **Add a colleague**, choosing Reviewer or Administrator
- **Reset a forgotten password**
- **Disable** someone who has left. They are signed out at once and cannot sign
  back in. Their work and the record of what they did are kept, and they can be
  re-enabled.
- **Change their own password**

A **Reviewer** can work on documents but cannot manage accounts.

Every one of these is written to the activity record.

### The activity record

The Team tab shows who is signed in, and what everyone has done. From the command
line:

```
python pipeline.py audit
python pipeline.py users
```

### Forgotten passwords

There are three ways back in, and it is worth knowing which applies.

| Situation | What to do |
|---|---|
| You can still sign in | **Change my password** on the Team tab |
| Somebody else can help | An administrator uses **Reset password** on the Team tab |
| You are the only administrator and you are locked out | Use your **recovery code** |

**The recovery code** is issued when the account is created and shown **once**,
on a page that asks you to write it down. It is stored hashed, exactly like a
password, so nobody can look it up later, including an administrator reading the
database.

If you forget your password, use **Forgotten your password?** on the sign-in
page. It asks for your username, the code, and a new password. Dashes and spaces
in the code do not matter.

**A code works once.** As soon as it is used it is cleared, so a piece of paper
that turns up later is worthless.

**To replace a code**, use **Recovery code** on the Team tab. An administrator can
issue one for anybody; anyone can issue one for themselves. Issuing a new code
replaces the old one, which is how you deal with a code that has been lost or
seen by the wrong person.

> **Write it down somewhere other than this machine.** A recovery code kept in a
> file on the same computer is no use if that computer is the thing you cannot
> reach.

---

## Working with other people

### The same office

Double-click `share-windows.bat`. It prints an address like:

```
Same office / same wifi    http://10.33.38.26:8765/
```

Colleagues open that. They need nothing installed.

### Somewhere else

A `10.x` or `192.168.x` address only exists inside one building and cannot work
from outside it. Both sides need a private network between their computers.
Tailscale is the easy answer, is free for small teams, and requires no changes to
your router:

1. Install Tailscale on this computer and sign in.
2. Install it on each colleague's computer with the same account.
3. Run `share-windows.bat` again. It prints a second address beginning `100.`
   That one works from anywhere.

See [SETUP.md](SETUP.md#working-from-home) for the detail.

### What not to do

**Do not forward a port from the internet to this program.** It speaks plain
HTTP, so passwords would cross the internet unprotected, and the built-in server
is not built to be the thing the public internet talks to. If a firm insists on a
plain web address, it must sit behind HTTPS.

---

## Data and confidentiality

**The program makes no network calls.** No cloud service, no API keys, no
telemetry. Converting, reading scans, hashing and indexing all happen locally.
You can unplug the network and it still works.

**Nothing in `intake/source/` is ever modified.** Files are copied into it, never
moved or renamed.

**`intake/`, `work/`, `output/` and `affidavit.config.json` are excluded from
version control**, and the automated checks fail if that ever stops being true.

### If you share it with a team

- **Keep sign-in on.** Without it, anyone who can reach the address can read
  every document.
- **Prefer a private network** such as Tailscale or a VPN over an open port.
- **Encrypt the disk** holding `intake/`, `work/` and `output/`.
- **Back up `work/pipeline.sqlite3`** with the same care as the documents.

---

## Where everything lives

| Path | What it is | Safe to delete? |
|---|---|---|
| `intake/incoming/` | Copy new documents here | Yes, after they are picked up |
| `intake/source/` | The library, your originals | **No. These are your documents.** |
| `intake/rejected/` | Notes about files that could not be read | Yes |
| `work/` | Derived files: normalised PDFs, searchable copies, the database | Yes, it can be rebuilt |
| `work/pipeline.sqlite3` | The record of what has been processed | Yes, but you lose review decisions and accounts |
| `output/collections/` | Bundles in progress | Yes |
| `output/collections/finished/` | Exported bundles | Yes, once imported into Zibbit |
| `output/reports/` | The reconciliation report | Yes |

---

## Commands

Everything is also available from a terminal. These change nothing unless stated.

| Command | Purpose |
|---|---|
| `python pipeline.py review` | Open the console (and the folder watcher) |
| `python pipeline.py review --users` | The same, requiring sign-in |
| `python pipeline.py review --demo` | Sample documents, no sign-in, for showing a client |
| `python pipeline.py share` | Let colleagues connect, and print the address |
| `python pipeline.py watch` | Run the folder watcher on its own |
| `python pipeline.py watch --once` | A single check, then exit |
| `python pipeline.py run` | Process anything not yet done |
| `python pipeline.py run --fresh` | Rebuild the record from scratch |
| `python pipeline.py ocr` | Read scanned documents |
| `python pipeline.py ocr --force` | Re-read them all |
| `python pipeline.py collections` | List bundles and what is in them |
| `python pipeline.py bundle --docs 1,2,3 --name "Bundle"` | Build and export without the browser |
| `python pipeline.py status` | How many documents, and how they are arranged |
| `python pipeline.py reconcile` | Check every source file is accounted for |
| `python pipeline.py users` | Accounts and what each person reviewed |
| `python pipeline.py users --reset-password NAME` | Reset a password |
| `python pipeline.py create-user ...` | Add an account from the command line |
| `python pipeline.py audit` | Who did what, and when |

---

## Settings

Defaults are built in. To change them, create a settings file once:

```
python pipeline.py init
```

That writes `affidavit.config.json`. The ones people actually change:

| Setting | Default | What it does |
|---|---|---|
| `ocr_lang` | `"eng"` | OCR language. Use `"eng+fra"` for French too. |
| `ocr_dpi` | `200` | Higher reads poor scans better and takes longer |
| `ocr_max_pages` | `25` | Long scans are read up to this many pages |
| `ocr_enabled` | `true` | Turn scanning off entirely |
| `sync_watch_dir` | `"intake/incoming"` | Which folder to watch |
| `sync_poll_seconds` | `4.0` | How often to check |
| `sync_settle_seconds` | `3.0` | How long a file must stop changing |
| `auto_sync_enabled` | `true` | Turn the folder watcher off |
| `filename_template` | date, type, title | How normalised files are named |

**Restart the app after changing anything here.** Settings are read at start-up.

---

## Checking nothing was missed

```
python pipeline.py reconcile
```

This is the safety net. It proves that **every file that arrived is accounted
for**: converted, combined with a duplicate, or named as unsupported with a
reason. It writes a readable report to `output/reports/` and a full
file-by-file trace to `traceability.csv`.

It also reports:

- Documents that could not be converted
- Scans that were never read, or that yielded nothing
- Unsupported formats

**Run it before relying on a bundle.** It is the answer to "did anything get
lost?", which is the question that matters.

---

## Things this program will not do

Worth knowing, so you do not wait for something that was never going to happen:

- **No internet, ever.** No cloud, no accounts, no telemetry.
- **No Zibbit integration.** Zibbit runs on the lawyer's computer. This prepares
  the PDFs it needs.
- **No decisions about documents.** It converts, names, orders and reports. What
  belongs in a bundle is yours.
- **No handwriting**, reliably. No reading text out of photographs of screens. A
  poor scan stays poor.
- **No SharePoint or Google Drive connection.** Documents are read from the drop
  folder, which can itself be a folder those services sync.
- **No more than about ten people working at once.** Beyond that the database
  needs changing.
