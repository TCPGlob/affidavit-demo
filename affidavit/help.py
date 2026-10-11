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
        "title": "Documents arrive in the intake folder",
        "body": (
            "Everything you want to work with goes into the intake folder, in "
            "whatever folders you already keep. Sub-folders are kept as they are "
            "and nothing is moved or renamed where you put it."
        ),
    },
    {
        "n": 2,
        "title": "The pipeline reads and tags them",
        "body": (
            "Each file is identified, duplicates are collapsed, and the computer "
            "records what it can work out: the kind of document, its date, how "
            "many pages, and whether it is a scan it cannot read. This happens "
            "on its own -- you do not need to do anything."
        ),
    },
    {
        "n": 3,
        "title": "Scans are read automatically",
        "body": (
            "If any document is a scan or a photo, the pipeline reads the text "
            "out of it so it can be searched and titled. This happens on this "
            "machine only. Anything it cannot read is flagged for you to check "
            "by eye; the original scan is never altered."
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
            "your colleagues see."
        ),
    },
    {
        "n": 6,
        "title": "Convert and export",
        "body": (
            "Only the documents you ticked are converted. You get a folder "
            "containing a PDFs sub-folder of numbered PDFs, a Word index sheet, "
            "and a contents list. Anything that could not be converted is listed "
            "under 'Not included' rather than silently dropped."
        ),
    },
    {
        "n": 7,
        "title": "Import the PDFs into Zibbit",
        "body": (
            "Zibbit is fed PDFs, so the PDFs folder is the finished product -- the "
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
    "Tick documents, then name the collection -- the black bar appears as soon as you tick anything.",
    "The order of documents in a collection is set by where they were added. Use the arrows inside a collection to reorder.",
    "A document can be in more than one collection, and can be called something different in each.",
    "Leave the 'Name in this bundle' box empty to use the document's own title.",
    "A collection can be exported as many times as you like; each export rebuilds the folder from scratch.",
    "Your tags are yours and are preserved when the pipeline re-reads the documents.",
    "If a scan was read badly, 'Re-read all' on the Library tab tries again at full quality.",
    "Documents edited at the same time by two people are never silently overwritten -- you are asked which version to keep.",
]

# The console no longer assigns legal schedules, so these are not offered.
# Kept out deliberately: this stage prepares bundles, it does not classify them.


def as_dict() -> dict:
    return {
        "workflow": WORKFLOW,
        "glossary": GLOSSARY,
        "badges": BADGES,
        "tips": TIPS,
    }
