# Quick setup

Get from a downloaded folder to a working console in about five minutes.

---

## Step 1. Install Python (once per computer)

Go to **https://www.python.org/downloads/** and install the latest version.

> **Windows: tick "Add Python to PATH" on the first screen of the installer.**
> If you miss this, the launcher will not find Python and will tell you so.

To check it worked, open a terminal and type:

```
python --version
```

It should print a version number like `Python 3.12.4`. If it says "not
recognised", Python is not on PATH, so reinstall and tick the box.

---

## Step 2. Start it

Unzip the folder somewhere sensible, then **double-click one of these**:

| Double-click | When |
|---|---|
| **`start-windows.bat`** | Normal use. Each person gets their own sign-in. |
| **`share-windows.bat`** | Also let colleagues connect from their computers. |
| **`demo-windows.bat`** | Show it to a client using sample documents. |

On **macOS or Linux**, run `./start-mac-linux.command` instead.

A black window opens. The first time, it installs what it needs, which takes a minute or
two. **Leave this window open.** It *is* the program.

---

## Step 3. Create your account

Your browser opens on a **Welcome** page. Type your name, a username and a
password (at least 10 characters).

**That first account is the administrator.** You can add colleagues from the
Team tab later, in the browser, with no command line needed.

> If Windows asks whether to allow Python through the firewall, choose **Allow**.
> Without it, nobody else can connect. If you miss the prompt, see
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Step 4. Add your own documents

The first run creates **sample documents** so there is something to look at.
Delete them when you are ready and use your own instead.

Create a shortcut to the folder you copy documents into:

```
intake\incoming\
```

Drop files in there, from your desk, from email, or from a shared folder. They are
picked up within a few seconds and appear in the console on their own. **You do
not run anything.**

Sub-folders work, so you can keep your own structure.

---

## Step 5. Make a bundle

In the console:

1. **Library tab**: tick the documents that belong together.
2. **+ New collection** on the black bar, and give it a name.
3. **Create & convert.**
4. The bundle is written and the path is shown on screen.

**Convert & export** moves the bundle to `output\collections\finished\` and it
leaves the console. What remains in Collections is live work only.

Import the **`PDFs`** folder into Zibbit. The files are already numbered in the
order you set.

---

### A shared folder the whole team drops into

If everyone puts documents in one place, point the watcher at it. In the console,
use **Use a shared folder** on the drop folder panel, then **Browse...** or type
the path. It is saved, so it still applies after a restart.

Network paths look like `\\server\share\documents`, or a mapped drive such as
`Z:\Scans`. Sub-folders are watched too, and files are copied, never moved.

Detail, including why this works over a network and what happens when a share
drops out, is in [HELP.md](HELP.md).

---

## Stopping and restarting

- **To stop:** close the black window, or press Ctrl+C in it.
- **To start again:** double-click the same file. It picks up exactly where you
left off, and nothing is lost.

---

## Optional extras

### Reading scanned documents (OCR)

Scans and photos have no text in them, so nothing can search them or work out
their date. Installing Tesseract fixes that, and it runs on this computer only.

```
winget install UB-Mannheim.TesseractOCR
```

Then restart the app. Existing scans are read on the next start, or run:

```
python pipeline.py ocr
```

### Converting Word documents

Word, Excel and PowerPoint files are converted to PDF. This needs LibreOffice:

```
winget install TheDocumentFoundation.LibreOffice
```

Without it, those files are listed as **Not included** rather than converted.

### For French documents

Install the French language data for Tesseract, then edit
`affidavit.config.json` and set:

```json
{ "ocr_lang": "eng+fra" }
```

---

## Letting colleagues use it

**In the same office:** double-click `share-windows.bat`. It prints an address
like `http://10.33.38.26:8765/`. Send them that; they need nothing installed.

**At home, or another city:** that address will not work outside your network.
You both need **Tailscale** (free, five minutes) first:

1. Install Tailscale on this computer and sign in.
2. Install it on each colleague's computer with the same account.
3. Run `share-windows.bat` again. It will now print a second address beginning
`100.` **That** is the one that works from anywhere.

Full detail, and the warning about what not to do, is in
[SETUP.md](SETUP.md#working-from-home).

---

## Where everything lives

| Folder | What it is |
|---|---|
| `intake\incoming\` | **Copy new documents here** |
| `intake\source\` | The library. your originals, untouched |
| `intake\rejected\` | Files that could not be read, with the reason |
| `work\` | Working files. Safe to delete to start over |
| `output\collections\` | Bundles in progress |
| `output\collections\finished\` | Exported bundles, ready for Zibbit |
| `output\reports\` | The reconciliation report |

**Nothing in `intake\source\` is ever modified.** Files are copied into it, never
moved or changed.

---

## Check it is working

```
python pipeline.py status
```

That prints how many documents are in the library and how they are arranged. If
it prints numbers, you are set up correctly.

---

## If something goes wrong

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md). It covers the handful of things
that actually go wrong, with the exact words you will see on screen.

## Everything else

See [HELP.md](HELP.md) for what the program does and how each part works.
