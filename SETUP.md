All is complete, just tweaks and modifications as per the client's requests
# Setting up, and showing it to a client

Two separate things:

- **Part 1**. getting it running for you and your team.
- **Part 2**. showing it to a client so they can decide.

You do **not** need a command line for either. Every account is created in the
browser.

---

---

# Part 1. Running it for your team

## On Windows: double-click a file

| Double-click this | What happens |
|---|---|
| **`start-windows.bat`** | Runs it properly. Each person gets their own sign-in. Just you. |
| **`share-windows.bat`** | Same, but colleagues on other computers can connect. Prints the address to send them. |
| **`demo-windows.bat`** | Runs it with sample documents and no sign-in, for showing someone. |

The first time you run `start-windows.bat`:

1. A black window opens and installs what the app needs (a minute or two).
2. Your browser opens on a **"Welcome, let's set up"** page.
3. You type your name, a username and a password. **That account is the
administrator.**
4. You are signed in and can start work.

On macOS or Linux, double-click **`start-mac-linux.command`** instead. (The first
time, macOS may ask you to confirm you trust the file.)

To stop the app, close the black window.

## Adding your colleagues. in the browser, no command line

Once you are signed in, open the **Team** tab:

1. Click **+ Add a colleague**.
2. Type their name, a username, and a temporary password.
3. Choose **Reviewer** (can work on documents) or **Administrator** (can also
manage accounts).
4. Click **Create account**, then tell them the password.

They can sign in immediately, and change their own password from the same screen.

On that same tab you can:

- **Reset password**. for someone who has forgotten theirs.
- **Disable**. for someone who has left. They are signed out at once and cannot
sign back in. Their work and the record of what they did are kept, and you can
re-enable them later.
- **Change my password**. for your own account.

Everything above is also possible from the command line (`python pipeline.py
create-user …`) if you prefer, but nothing requires it.

## The whole team at once: what to expect

This is the arrangement a firm ends up with, and it works out of the box:

```
        one always-on computer                everybody else
   ┌──────────────────────────────┐
   │  the app, running --users    │◀──── Tailscale ────  home, another office
   │  the shared drop folder      │◀──── same wifi ────  the next desk
   │  Tailscale installed         │
   └──────────────────────────────┘
```

### What each person needs

| | |
|---|---|
| An account | Created by an administrator on the **Team** tab |
| A role | **Reviewer** to do the work, **Administrator** also to manage people |
| The address | Sent once. Nothing to install except Tailscale |
| A browser | Any current one |

### The setup order that avoids trouble

1. **On the always-on machine**, install Python, LibreOffice and Tesseract, then
   copy the project folder somewhere sensible.
2. **Start it once with `start-windows.bat` and create the administrator account
   immediately.** Whoever opens the Welcome page first becomes the administrator,
   so do this before anyone else can reach the machine.
3. **Set the shared folder** from the console: drop folder panel, **Use a shared
   folder**. Point it at the folder everyone will drop into.
4. **Add everyone** on the Team tab.
5. **Install Tailscale** on that machine and on every colleague's machine, signed
   in to the same account.
6. **Double-click `share-windows.bat`** and send everyone the address labelled
   **works anywhere**.

### Day to day

- The always-on machine must be **on**, with the app **running**. Everything else
  is ordinary browser use.
- Somebody drops a document in the shared folder. It appears in everyone's
  Library within seconds, whoever dropped it.
- Anyone can start a collection, add to it, reorder it and export it.
- **Exported bundles** remain findable by everyone after they leave the working
  list.

### When two people touch the same thing

Nothing is silently overwritten. Each bundle carries a version, and a save made
against an old version is **refused**, with the current value shown so the person
can decide. Adding documents is safe to do at the same time from two computers:
adding the same document twice does nothing.

So the worst case is one person being asked to look again. That is the point.

### Dividing work so it does not come up

- Give each person **their own collection** for the part they are assembling,
  then combine. Conflicts only arise when two people edit the *same* bundle.
- Use **tags** to mark progress or ownership. Tags you add are never overwritten,
  even when the pipeline re-reads the documents.
- Export when a bundle is finished, which keeps the console showing live work.

### Before you rely on it: the checks worth running

- Everyone signs in and sees the same Library
- Two people each add a document at the same time, with no duplicate
- Two people edit one bundle's description at the same time, and one is told
  there is a conflict
- Somebody at home drops a file in, and it appears for everyone else
- Export a bundle, then confirm everyone finds it under **Exported bundles**

### Rough limit

Comfortable for about **ten people working at once**. Beyond that the database
wants changing to something built for more writers. For a firm-sized matter this
is not a constraint.

### Backups

Back up the **`work` folder** and the **`intake` folder** together. `work`
contains the record of what has been processed, the review decisions and the
account list; `intake` contains the documents. `output` can be rebuilt from a
collection whenever you need it.

## Letting colleagues on other computers reach it

By default the app is reachable **only from the computer it runs on**. That is the
safe default.

To let colleagues connect, **double-click `share-windows.bat`**. It prints the
address to hand out:

```
Same office / same wifi http://10.33.38.26:8765/
```

Give colleagues that address. They need nothing installed, just a browser. You
keep the black window open; it is the server.

The same thing from a terminal, if you prefer:

```
python pipeline.py share
```

**If a colleague cannot connect, it is almost always Windows Firewall.** Re-run
and choose **Allow** when Windows asks, or allow Python on *Private* networks in
Windows Firewall settings.

On macOS or Linux, run `./start-mac-linux.command` and add `--host 0.0.0.0` to
the last line.

---

# Working from home

There are two different situations, and they need different answers.

| Where the colleague is | What works |
|---|---|
| Same office or same wifi | The address `share` prints. Nothing else needed. |
| At home, or on mobile data | A **private network between the computers**. The office address will not work. |

A `10.33.x.x` or `192.168.x.x` address only exists inside one building. It is
meaningless from a home connection. This is not a setting you can change, it is
how home and office networks work.

## The easy answer: Tailscale

[Tailscale](https://tailscale.com) creates a private, encrypted network between
computers as if they were on the same wifi, wherever they are. It is free for
small teams, takes about five minutes, and **needs no changes to your office
router and nothing exposed to the internet.**

1. Install Tailscale on the computer that will run the app, and sign in.
2. Install it on each colleague's computer, and sign in with the same account.
3. Run `python pipeline.py share` on the host, or double-click
   `share-windows.bat`.

Addresses beginning `100.` in the output are the Tailscale ones and **work from
anywhere**. Give colleagues that address instead of the office one:

```
Tailscale (works anywhere) http://100.70.246.36:8765/
Same office / same wifi    http://192.168.146.58:8765/
```

The Tailscale address is listed first, so the one to send is the one at the top.

That is the whole setup. The documents never touch the public internet; Tailscale
carries the traffic directly between your computers, encrypted.

> **WireGuard** is already installed on some machines and does the same job, but
> it requires someone to configure a server and hand out keys. Tailscale is the
> same technology with the setup done for you. If your IT already runs a
> WireGuard or OpenVPN server, use that instead. Connect first, then use the
> address `share` prints.

### Do not use `--secure-cookie` with Tailscale

`--secure-cookie` tells the browser to send the sign-in cookie **only over
HTTPS**. Tailscale gives you a private encrypted network but a plain `http://`
address, so with that flag set the cookie is never sent and **nobody can sign
in**. If the address is `http://`, leave that flag alone.

### Never forward a port from the internet

Not instead of Tailscale, and not as well as. The app speaks plain HTTP, so
passwords would cross the public internet unprotected, and its built-in server is
not built to be the thing the public internet talks to. That is exactly the
problem Tailscale removes.

### What was actually tested

Verified over a real Tailscale address with three people signed in at once, two
of them reaching the app through the Tailscale address:

| Checked | Result |
|---|---|
| Each person signs in and gets their own session | passed |
| A made-up session token is refused | passed |
| All three see the same shared folder and library | passed |
| Five documents dropped by three people at once | all ingested |
| Two people editing one bundle | one saved, the other told of the conflict |
| Two people adding documents at once | no duplicates |
| One exports, all three see it under exported bundles | passed |
| A write from a foreign website | refused |
| Dropped files still in the shared folder, unmodified | passed |
| Signing out on one computer | other two unaffected |

**Not proven by this:** that your particular network routes correctly, or that a
machine far away feels quick. Reachability is Tailscale's job rather than this
program's.

## The better answer for a real firm: a machine of their own

For ongoing client work, running it on somebody's laptop is the weak point: close the lid and the app is down for everyone. The sturdier arrangement:

- One always-on computer at the firm (a small server, or a machine nobody moves)
- Tailscale installed on it and on everyone who needs access
- The app running there with `--users`, so each person signs in
- Automatic backups of the `work` folder

Nothing is exposed to the internet, and it keeps working when laptops close.

## When it must face the internet

Sometimes a firm insists on a plain web address. Then it **must** sit behind
HTTPS, and `--secure-cookie` must be used. Without the padlock, sign-in
passwords travel in the clear across the internet.

Ask whoever manages their IT to put a small piece of software in front of it
(Caddy and nginx are the usual choices) that adds the padlock and forwards to
`http://127.0.0.1:8765`. Do not simply forward a port from the internet to this
app: the built-in server speaks plain HTTP and is not built to be the thing the
public internet talks to.

## When someone genuinely cannot connect

The last resort is to install the app on their own computer, with their own copy
of the documents. It works, but **each copy is its own separate library**, collections are not shared, and two people will not see each other's work. Use it
only if a private network is impossible.

---

## Quick reference

| Situation | What to do |
|---|---|
| Just me, this laptop | Double-click `start-windows.bat` |
| Show a client | Double-click `demo-windows.bat` |
| Colleagues in the same office | Double-click `share-windows.bat` |
| A colleague at home | Install Tailscale on both, then `share-windows.bat` |
| A firm running it properly | Always-on machine + Tailscale + `--users` |
| Must be a public web address | HTTPS in front, plus `--secure-cookie` |

---

---

# Part 2. Showing it to a client

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

Say that out loud during the demo. It is not a weakness: the pipeline's job is
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
first. The note at the end of this file explains that if it is not there yet.
Then open a Codespace on it and, in the terminal that appears, run:

```bash
python -m pip install pymupdf pillow openpyxl
python pipeline.py review --demo --host 0.0.0.0 --port 8765
```

Codespaces forwards the port; set it to **Public** and send them the URL.

## Docker, if your IT prefers it

```bash
docker build -t aod.
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
machine, with no cloud service. This receipt had no date we could see; now it's
2024-04-12."
3. **Tick three or four documents.** The black bar appears.
4. **Create a collection** and name it. "That name becomes the folder."
5. **Convert & export.** The result appears with the folder path.
6. **Open the folder.** Show `PDFs/`, the numbered files, the Word index and
`index.csv`.
7. **Open the Word index.** Everything in order, with dates and page counts.
8. **Import into Zibbit.** Say clearly: this part is on their machine.
9. **Team tab.** Show the activity record of who did what, and the account list.

### The two questions they will ask

**"What if it gets a document wrong?"**
It never decides anything about content. Conversion, naming, ordering and
numbering are mechanical. If a document cannot be converted it is listed under
**Not included** with the reason. visibly, in the console, the Word sheet, the
CSV and the manifest, rather than quietly disappearing.

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
git add.
git status # read this: intake, work and output must NOT appear
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
| "Address already in use" | The app is probably already running. check for the black window. |
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
