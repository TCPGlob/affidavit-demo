# Troubleshooting

For the person setting this up, who is not a programmer.

Find the message you are seeing, or the thing that is not working, and follow the
steps. Every entry says **what you will see**, **why**, and **what to do**.

If nothing here matches, go to [Still stuck](#still-stuck) at the end and gather
three pieces of information before asking for help. That is usually enough to
solve it in one exchange.

---

## Starting up

### "Python is not installed on this computer"

The launcher looked for Python and could not find it.

**Do this:**
1. Go to https://www.python.org/downloads/ and install Python.
2. **On the first screen of the installer, tick "Add Python to PATH".** This is
the step people miss.
3. Double-click the launcher again.

**To check before retrying**. open a terminal and type `python --version`. If it
prints a version, you are fine. If it says "not recognised", PATH is still wrong:
reinstall and tick that box, or repair the existing installation.

---

### The black window flashes and disappears

Something failed before it could tell you why.

**Do this:**
1. Open a terminal in the folder (Shift + right-click the folder → *Open
PowerShell window here*).
2. Type the commands from the launcher by hand:
```
python pipeline.py review --users
```
3. Now the error stays on screen. Send that text to whoever is helping you.

The most common causes are covered below.

---

### "Could not bind 127.0.0.1:8765" or "address already in use"

Another copy is already running, or something else is using that port.

**Do this:**
1. Look for another black window and close it.
2. If none is visible, open Task Manager (`Ctrl+Shift+Esc`), find any `python`
process, and end it.
3. Start again.

**Or just use a different port:**
```
python pipeline.py review --users --port 8770
```

---

### The browser does not open

The app may still be running correctly. Only the automatic browser launch
failed.

**Do this:** open your browser yourself and go to:
```
http://127.0.0.1:8765/
```

If you changed the port, use `http://127.0.0.1:YOURPORT/`.

---

### "Welcome" page does not appear. it asks me to sign in instead

An account already exists, so setup has already been done. Someone created the
first account earlier.

**If you have forgotten the password:**
```
python pipeline.py users --reset-password your-username
```
It will ask you for a new one.

---

### I created my account but now it will not let me in

Check the username is exactly right. Usernames are saved in lowercase. If you
registered as `Jane`, sign in as `jane`.

If that is not it, reset the password as above.

---

## Windows Firewall

### A colleague cannot connect

**This is the single most common problem**, and the cause is nearly always that
the firewall prompt was dismissed.

**Do this:**
1. Stop the app (close the black window).
2. Start it again with `share-windows.bat`.
3. **When Windows asks whether to allow Python, choose Allow.**
4. If no prompt appears, allow it manually:
- Start → *Windows Defender Firewall* → *Allow an app through firewall*
- *Change settings* → *Allow another app* → *Browse*
- Find `python.exe` (usually `C:\Python312\python.exe` or in
`AppData\Local\Programs\Python\`)
- Tick **Private**, and **Public** if they are on a different network
- OK

**Then check the basics:**
- Are you both on the same network? A guest wifi often blocks this.
- Have your colleague `ping` the address first, to see whether it reaches the
machine at all.
- Is the black window still open? If it closed, the server is gone.

---

### "It worked yesterday and now it does not"

**The address changes.** `10.33.38.26` is handed out by your router and can
change when you reconnect. Re-run `share-windows.bat` and send the new address.

---

### They are at home / in another city and cannot connect

**A `10.x` or `192.168.x` address cannot work from outside your building.** This
is not a setting you can change; it is how home and office networks work.

**Do this:** both install [Tailscale](https://tailscale.com), sign in to the same
account, then run `share-windows.bat` again. It will print a second address
beginning `100.`. That one works from anywhere.

See [SETUP.md](SETUP.md#working-from-home).

---

## Documents

### I put files in the folder and nothing happens

**Check you used the right folder.** It is:
```
intake\incoming\
```
Not `intake\` and not `intake\source\`. The console shows the exact path in the
banner at the top of the Library tab.

**Other things to check:**
- **Wait about 10 seconds.** The watcher checks every few seconds, and a file
still being copied is deliberately left alone until it stops changing.
- **Is the watcher running?** The banner says when it last checked. If it says
"has stopped", restart the app.
- **Did the file arrive mid-copy?** A `.crdownload` or `.part` file is ignored on
purpose, because it is not finished. Wait for the download to complete.
- **Very unusual formats** are not supported. `.zip`, `.exe` and similar are
recorded as unsupported rather than silently dropped. Check the
reconciliation report.

---

### Something is listed as "Not included"

That is deliberate, and it is the honest behaviour: the document was ticked but
could not be turned into a PDF, so it is reported rather than quietly dropped. A
half-converted document in a bundle would be worse.

**The reason is stated** in the console, in `index.csv`, and in `manifest.json`.

The most common reason is a Word, Excel or PowerPoint file:
```
could not convert: LibreOffice not installed
```
**Do this:** `winget install TheDocumentFoundation.LibreOffice`, then restart and
export again.

---

### A drop-down shows "PLACEHOLDER" or "SKIPPED_NO_CONVERTER"

No tool was available to convert that file, so what exists is a **placeholder,
not the real document**. It is kept out of bundles on purpose.

**Do this:** install LibreOffice (above) and run the pipeline again:
```
python pipeline.py run
```

---

### A scan shows "OCR NEEDED" or "not read"

The document is a scan or photo with no text inside it, so nothing can search it
or read its date.

**Do this:** `winget install UB-Mannheim.TesseractOCR`, restart the app, then
either wait for the next start or run:
```
python pipeline.py ocr
```

The original scan is never altered. OCR writes a separate searchable copy used
only for reading.

---

### Text quality says "verify" or "check"

That scan was read, but not confidently. The percentage shown is how sure the
reading was.

**Do this:** open the document and check the important bits. dates, amounts,
names, against the image. The filter **"Scans to check by eye"** lists
everything in this state.

This is not an error. Some scans are simply poor, and the program is telling you
so rather than pretending.

---

### OCR fails with "Tesseract is not installed"

Installing it does not always put it on PATH, but this program looks in the usual
places. If it still cannot find it:

1. Check it exists at `C:\Program Files\Tesseract-OCR\tesseract.exe`.
2. If it does and the program still says missing, restart the app. PATH is read
at start-up.

---

### Dates are wrong on some documents

The program reads dates from the text. It prefers a labelled date (`Date:`,
`Dated:`, `Sent:`), then one near the top, then one in the file name. If a
document refers to an older date in its first lines, that older date may be
picked.

**Do this:** correct it in the bundle by naming the document in the collection,
or ignore it. The date in the index is a convenience, not a legal
determination. Every document is still listed and exported.

---

## Bundles and exporting

### "This collection has no documents in it yet"

You created a collection without ticking anything.

**Do this:** go to the Library, tick the documents, then use **Add to** on the
black bar and choose the collection.

---

### "A collection called.. already exists"

Two collections cannot share a name, because the name becomes the folder.

**Do this:** give it a different name, or open the existing one and add to it.

---

### My bundle disappeared after I exported it

**That is the design.** Exporting moves the bundle to:
```
output\collections\finished\
```
and takes it out of the console, so what you see under Collections is live work
only.

**To find it:** open that folder in File Explorer. Nothing is deleted.

---

### "Someone else changed this while you were editing"

Two people edited the same thing at once.

**Do this:** choose which version to keep when asked. Nothing is lost silently. your text is not overwritten without you agreeing to it.

To avoid it, agree who is working on which collection.

---

### The word "COMPLETE" file in a bundle

That is deliberate. It is written **last**, and contains a fingerprint of
everything else in the bundle. Any other tool should wait for it before using a
bundle. Its absence means the bundle was still being written.

---

## Accounts and sign-in

### I forgot my password

Three ways back in, depending on who you are.

**If somebody else can help:** ask an administrator to use **Reset password** on
the Team tab. Done in a few seconds.

**If you are the only administrator and are locked out:** use your **recovery
code**. On the sign-in page, click **Forgotten your password?**. It asks for your
username, the recovery code you were given when the account was created, and a
new password. Dashes and spaces in the code do not matter.

**If you have lost the recovery code as well:**
```
python pipeline.py users --reset-password your-username
```
It will ask you for a new password.

Once you are back in, print a fresh code with **Recovery code** on the Team tab,
and keep it somewhere other than this computer.

> **A recovery code works once.** When it has been used it is cleared, so an old
> note of it is worthless to anybody who finds it.

### "That username and recovery code do not match"

Check the username is exactly right (they are saved in lowercase), and that you
are using the **current** code. Issuing a new code on the Team tab replaces the
old one, so an older note of it will stop working.

If it still will not work, reset the password from the command line as above, then
print a new code.

### I want to add a colleague

Sign in as an administrator, open the **Team** tab, and use **+ Add a colleague**.
No command line needed.

### Someone has left

Team tab → **Disable** next to their name. They are signed out at once and cannot
sign back in. Their work and the record of what they did are kept.

### "Sign-in is switched off"

The app was started without accounts. Close it and start it with
`start-windows.bat` (or add `--users` to the command).

---

## The console itself

### The page looks broken or out of date

Press `Ctrl+F5` to force a full reload. Browser caching is the usual cause.

---

### Too many documents to scroll through

Use the pager at the top of the list. **Next**, **Last**, and jump buttons. 50
documents per page in the Library, 12 collections per page.

Use the **Show** filter and the search box to narrow things down instead of
scrolling.

---

### I hid the instructions and cannot get them back

Click the **arrow** at the left of the "How this works" bar, or the
**Instructions** button at the bottom right.

---

## Losing or rebuilding the record

### "THE WORKING DATABASE CANNOT BE OPENED"

The file that records what has been processed has been damaged, usually by a
crash or an interrupted copy.

**Your documents are not affected.** They are still in `intake\source\` exactly
as you left them.

**Do this:**
```
python pipeline.py run --fresh
```
It rebuilds the record from your documents. Depending on how many you have, this
may take a few minutes.

**If that also fails:**
```
ren work work-old
python pipeline.py run --fresh
```
Nothing is lost: `work\` contains only derived files, which the program can
regenerate.

---

### I want to start completely fresh

**Keep your documents, rebuild everything else:**
```
ren work work-old
ren output output-old
python pipeline.py run --fresh
```

**Delete the sample documents too:**
Empty `intake\source\` and `intake\incoming\`, then run the command above.

> Deleting `work\` loses the review decisions and the account list. The documents
> themselves are in `intake\source\` and are not touched.

---

## Checking on things

These commands are safe to run at any time and change nothing:

| Command | Tells you |
|---|---|
| `python pipeline.py status` | How many documents, and how they are arranged |
| `python pipeline.py collections` | Every bundle and what is in it |
| `python pipeline.py reconcile` | Whether every source file is accounted for |
| `python pipeline.py users` | Accounts, and who reviewed what |
| `python pipeline.py audit` | Who did what, and when |

---

## Still stuck

Before asking for help, gather these three things. They solve most problems
immediately:

**1. The exact words on screen.** Copy the whole error, not a summary. If the
window vanished, run the command by hand (see *The black window flashes and
disappears* above) so the message stays.

**2. The output of this command:**
```
python pipeline.py status
```

**3. The output of this command:**
```
python pipeline.py reconcile
```

That last one checks whether every file that arrived has been accounted for, and
it names anything that went wrong individually.

**Never send the documents themselves** when asking for help. The two commands
above print counts and file names, which is normally enough, and the documents
may be confidential.

---

## What this program will not do

Worth knowing, so you are not troubleshooting a thing that was never going to
work:

- **It does not upload anything anywhere.** No cloud service, no account. If your
network is unplugged it still works.
- **It does not talk to Zibbit.** Zibbit is a Word add-in on the lawyer's
computer; this prepares the PDFs it needs.
- **It does not decide anything about documents.** It converts, names, orders and
reports. What belongs in a bundle is your call.
- **It does not read handwriting** reliably, and does not read text out of
photographs of screens well. Poor scans stay poor.
