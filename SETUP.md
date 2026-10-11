# Setting up, and showing it to a client

Two separate things:

- **Part 1** — getting it running for you and your team.
- **Part 2** — showing it to a client so they can decide.

You do **not** need a command line for either. Every account is created in the
browser.

---

# Part 1 — Running it for your team

## On Windows: double-click a file

| Double-click this | What happens |
|---|---|
| **`start-windows.bat`** | Runs it properly. Each person gets their own sign-in. |
| **`demo-windows.bat`** | Runs it with sample documents and no sign-in, for showing someone. |

The first time you run `start-windows.bat`:

1. A black window opens and installs what the app needs (a minute or two).
2. Your browser opens on a **"Welcome — let's set up"** page.
3. You type your name, a username and a password. **That account is the
   administrator.**
4. You are signed in and can start work.

On macOS or Linux, double-click **`start-mac-linux.command`** instead. (The first
time, macOS may ask you to confirm you trust the file.)

To stop the app, close the black window.

## Adding your colleagues — in the browser, no command line

Once you are signed in, open the **Team** tab:

1. Click **+ Add a colleague**.
2. Type their name, a username, and a temporary password.
3. Choose **Reviewer** (can work on documents) or **Administrator** (can also
   manage accounts).
4. Click **Create account**, then tell them the password.

They can sign in immediately, and change their own password from the same screen.

On that same tab you can:

- **Reset password** — for someone who has forgotten theirs.
- **Disable** — for someone who has left. They are signed out at once and cannot
  sign back in. Their work and the record of what they did are kept, and you can
  re-enable them later.
- **Change my password** — for your own account.

Everything above is also possible from the command line (`python pipeline.py
create-user …`) if you prefer, but nothing requires it.

## Letting colleagues on other computers reach it

By default the app is reachable **only from the computer it runs on**. That is the
safe default.

To let the team connect, a helper needs to start it so it listens on the network.
Editing `start-windows.bat` and changing the last line to add `--host 0.0.0.0`
does it:

```
%PY% pipeline.py review --users --host 0.0.0.0
```

Then colleagues open `http://<your-computer-address>:8765/` in their browser.

**Before you do this, two things:**

1. **Keep `--users` on.** Without it, anyone who can reach the address can read
   every document, and no one has to sign in.
2. **Put it on a private network** — a VPN or Tailscale — rather than opening it
   to the internet. For client material this is much the safer choice, and it
   avoids needing certificates altogether.

If it does need to face the internet, it must sit behind HTTPS. Ask whoever
manages your IT to put a small piece of software in front of it (Caddy and nginx
are the usual choices) that adds the padlock, and start the app with the extra
flag `--secure-cookie`.

---

# Part 2 — Showing it to a client

## The one thing to be clear about

**Zibbit is an add-in that runs inside Microsoft Word, on the lawyer's own
computer. It is not a website and cannot be sent documents.**

So a demo can show everything *up to* Zibbit, but not Zibbit itself:

| Shown in the demo | Happens on their machine |
|---|---|
| Finding and tagging documents | |
| Ticking the ones you want | |
| Naming the bundle | |
| Converting to PDF and numbering | |
| Producing the index | |
| | Importing the PDFs into Zibbit |

Say that out loud during the demo. It is not a weakness — the pipeline's job is
to hand Zibbit a clean, ordered bundle, and that is the part that takes the time.

**In normal use everything stays on the firm's own computer.** The app makes no
internet calls at all. You can prove this: unplug the network and the demo still
works.

## Easiest: your own laptop, on a screen share

```bash
python pipeline.py review --demo
```

Or just double-click **`demo-windows.bat`**.

Sample documents are created automatically, sign-in is off, and the console opens
with everything ready. Nothing to install and no link to share.

> Sample documents only. Never point this at real client files, because anyone
> who can reach the address can read them.

## Sending them a link: GitHub Codespaces

Use this when you want the client to click around on their own, without
installing anything on their computer. It needs the project to be on GitHub
first — the note at the end of this file explains that if it is not there yet.
Then open a Codespace on it and, in the terminal that appears, run:

```bash
python -m pip install pymupdf pillow openpyxl
python pipeline.py review --demo --host 0.0.0.0 --port 8765
```

Codespaces forwards the port; set it to **Public** and send them the URL.

## Docker, if your IT prefers it

```bash
docker build -t aod .
docker run -d --name aod-demo -p 8080:8765 aod \
  python pipeline.py --root /data review --demo \
  --host 0.0.0.0 --port 8765 --no-browser
```

For real use, run it with sign-in required (the default in the image) and behind
HTTPS. Create the first account from the browser, exactly as above.

---

## A five-minute demo script

1. **The Library.** "This is everything that arrived, already converted to PDF
   and tagged with its type, date and page count. Duplicates were collapsed."
   Point at the `2 COPIES` badge on the invoice.
2. **Scanned documents.** Point at the OCR panel. "Scans get read too, on this
   machine — no cloud service. This receipt had no date we could see; now it's
   2024-04-12."
3. **Tick three or four documents.** The black bar appears.
4. **Create a collection** and name it. "That name becomes the folder."
5. **Convert & export.** The result appears with the folder path.
6. **Open the folder.** Show `PDFs/`, the numbered files, the Word index and
   `index.csv`.
7. **Open the Word index.** Everything in order, with dates and page counts.
8. **Import into Zibbit.** Say clearly: this part is on their machine.
9. **Team tab.** Show the activity record — who did what — and the account list.

### The two questions they will ask

**"What if it gets a document wrong?"**
It never decides anything about content. Conversion, naming, ordering and
numbering are mechanical. If a document cannot be converted it is listed under
**Not included** with the reason — visibly, in the console, the Word sheet, the
CSV and the manifest — rather than quietly disappearing.

**"What about confidentiality?"**
Nothing leaves the machine. No accounts with cloud services, no API keys. Offer
to switch the WiFi off and carry on using it.

---

## Ground rules about sample data

- **A demo instance uses sample documents only.** Anyone with the link can reach it.
- **Never put a real client file into a demo.** Once it is uploaded, it is on
  whatever computer is hosting the demo.
- For real work, run it on the firm's own machine or private server, with
  sign-in turned on.

The project is set up so that **documents are never uploaded to GitHub**. The
intake folder, the working files and the finished bundles are all excluded, and
the automated checks fail the build if that ever stops being true. Only the
program itself lives on GitHub.

---

## If the project is not on GitHub yet

This is a one-off job, and only needed for the Codespaces option. In a terminal
in the project folder:

```
git init
git add .
git status          # read this: intake, work and output must NOT appear
git commit -m "Document preparation pipeline"
git remote add origin https://github.com/<your-account>/<your-project>.git
git push -u origin main
```

Read what `git status` lists before committing. Once a document is in the
project's history it is genuinely hard to remove, and that is the one mistake
here that the automated checks cannot undo for you.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| "Python is not installed" | Install it from python.org and tick **Add Python to PATH** during setup. |
| The browser does not open | Open `http://127.0.0.1:8765/` yourself. |
| "Address already in use" | The app is probably already running — check for the black window. |
| Scans are not being read | OCR is not installed. Run `winget install UB-Mannheim.TesseractOCR` and restart. |
| You forgot your administrator password | Stop the app, then run `python pipeline.py users --reset-password your-username`. |
| A conversion shows `PLACEHOLDER` | LibreOffice is missing: `winget install TheDocumentFoundation.LibreOffice`. |
| Nothing at all works | Delete the `work` folder and start again, then run `python pipeline.py demo` followed by `python pipeline.py run`. |

---

## What is already done, and what is not

Working: conversion, duplicate handling, tagging, OCR, bundles, the Word index,
multiple people with their own sign-ins, an activity record, and honest reporting
of anything that could not be processed.

Not yet:

- Long scanned documents are read up to the first 25 pages by default
  (`ocr_max_pages` in `affidavit.config.json`).
- No connection to SharePoint or Google Drive; documents are read from the
  `intake` folder.
- Built for a handful of people. Beyond roughly ten working at once, it needs a
  different database.
