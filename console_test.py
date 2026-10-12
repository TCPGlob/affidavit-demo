"""Checks the console's JavaScript actually runs.

A single parse error in the console script kills every button, because the whole
script fails to load. That happened once: a duplicated `const total` in
renderLibrary meant Help, Instructions and every other control did nothing.

Reading the file would not have caught it. This extracts the script, parses it,
and then executes it against the real API payloads with a small DOM stub, which
catches both syntax errors and runtime errors in the render paths.

Node is used for this because it is already needed by nothing else here and is
present wherever this was developed. If Node is absent the checks are skipped
with a visible notice rather than failing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

RUNTIME_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
const missing = new Set();

function makeEl(id) {
  return {
    id, style: {}, dataset: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    _html: '', _text: '',
    get innerHTML(){ return this._html; }, set innerHTML(v){ this._html = String(v); },
    get textContent(){ return this._text; }, set textContent(v){ this._text = String(v); },
    value: '', open: true, checked: false, scrollTop: 0, offsetParent: {},
    appendChild(){}, focus(){}, scrollIntoView(){}, addEventListener(){},
    closest(){ return { offsetParent: {} }; },
    querySelectorAll(){ return []; },
  };
}
const els = {};
for (const id of ids) els[id] = makeEl(id);

const help = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const docs = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

const sandbox = {
  console,
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  location: { href: '', assign(){} },
  setTimeout: (fn) => { if (fn) fn(); return 0; },
  clearTimeout: () => {},
  confirm: () => false,
  alert: () => {},
  document: {
    getElementById(id) {
      if (!els[id]) { missing.add(id); els[id] = makeEl(id); }
      return els[id];
    },
    querySelectorAll(){ return []; },
    addEventListener(){},
    createElement: makeEl,
  },
  fetch: (url) => {
    const u = String(url);
    let body = {};
    if (u.includes('api/help')) body = help;
    else if (u.includes('api/documents')) body = docs;
    else if (u.includes('api/collections'))
      body = { collections: docs.collections || [], finished: [], finished_dir: '/x/finished' };
    else if (u.includes('api/ocr'))
      body = { engine_available: true, engine: 'tesseract', default_language: 'eng',
               unread: 1, read: 2, no_text: 1, failed: 0, characters: 265, languages: ['eng'] };
    else if (u.includes('api/sync'))
      body = { status: { watch_dir: 'intake/incoming', alive: true, owner: 'pc:1',
                         last_heartbeat: '', seconds_since_heartbeat: 5,
                         cloud_warning: null }, events: [] };
    else if (u.includes('api/team'))
      body = { auth_enabled: false, me: null, users: [], active: [], activity: [], note: '' };
    return Promise.resolve({ ok: true, status: 200,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)) });
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

const results = [];
function check(label, cond, detail) {
  results.push({ label, ok: !!cond, detail: detail || '' });
}

try {
  vm.runInContext(script, vm.createContext(sandbox), { filename: 'console.html' });
  check('the console script parses and loads', true);
} catch (e) {
  check('the console script parses and loads', false, e.message);
  console.log(JSON.stringify(results));
  process.exit(0);
}

// boot() resolves its fetches on microtasks; let them settle.
setTimeout(() => {
  try {
    const guide = els['guidebody'] ? els['guidebody'].innerHTML : '';
    check('the instructions panel is filled', guide.length > 300, guide.length + ' chars');
  } catch (e) { check('the instructions panel is filled', false, e.message); }

  try {
    sandbox.openHelp();
    const nav = els['helpnav'] ? els['helpnav'].innerHTML : '';
    const main = els['helpmain'] ? els['helpmain'].innerHTML : '';
    check('the Help window renders a topic list and a topic', nav.length > 100 && main.includes('<h3>'),
          nav.length + ' nav, ' + main.length + ' body');
  } catch (e) { check('the Help window renders a topic list and a topic', false, e.message); }

  try {
    els['helpq'].value = 'firewall';
    sandbox.renderHelp();
    const m = els['helpmain'].innerHTML;
    check('searching the help returns content', m.length > 100, m.length + ' chars');
  } catch (e) { check('searching the help returns content', false, e.message); }

  try {
    els['helpq'].value = 'zzzznotathing';
    sandbox.renderHelp();
    check('an unmatched search explains itself',
          els['helpmain'].innerHTML.includes('Nothing in the help matches'));
  } catch (e) { check('an unmatched search explains itself', false, e.message); }

  try {
    els['helpq'].value = '';
    sandbox.toggleGuide();
    sandbox.toggleGuide();
    check('the instructions toggle works',
          (els['guidehint'].textContent || '').includes('arrow'));
  } catch (e) { check('the instructions toggle works', false, e.message); }

  try {
    sandbox.renderLibrary();
    check('the Library renders without error',
          (els['stat'].textContent || '').length > 10, els['stat'].textContent || '');
  } catch (e) { check('the Library renders without error', false, e.message); }

  try {
    sandbox.renderCollections();
    check('Collections render without error', true);
  } catch (e) { check('Collections render without error', false, e.message); }

  check('every element the script asks for exists in the markup',
        missing.size === 0, [...missing].join(', '));

  console.log(JSON.stringify(results));
}, 60);
"""


def main() -> int:
    failures: list[str] = []
    skipped: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    console = ROOT / "affidavit" / "console.html"
    check("the console file exists", console.exists(), str(console))
    if not console.exists():
        return 1

    html = console.read_text(encoding="utf-8")

    # ---------------- structural checks (no Node needed) ---------------
    print("--- markup ---")
    import re

    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'getElementById\(.([A-Za-z0-9_]+).\)', html))
    check("every element the script asks for is in the markup",
          not (used - ids), str(sorted(used - ids)))

    funcs = set(re.findall(r"function ([A-Za-z0-9_]+)", html))
    called = set(re.findall(r'on(?:click|change|input|submit)="([A-Za-z0-9_]+)\(', html))
    helpers = {"if", "qualityCell", "loadSync", "renderSync", "pagerHtml",
               "gotoPage", "mdToHtml", "inline"}
    check("every button calls a function that exists",
          not (called - funcs - helpers), str(sorted(called - funcs - helpers)))

    for label, needle in (("a Help button", 'onclick="openHelp()"'),
                          ("an Instructions button", 'onclick="toggleGuide()"'),
                          ("the help window", 'id="help"'),
                          ("the help topic list", 'id="helpnav"'),
                          ("the help body", 'id="helpmain"'),
                          ("a help search box", 'id="helpq"'),
                          ("the instructions body", 'id="guidebody"')):
        check(f"the console has {label}", needle in html)

    # ---------------- runtime checks (need Node) -----------------------
    print("\n--- running the script ---")
    node = shutil.which("node")
    if not node:
        skipped.append("all runtime checks")
        print("[SKIP] Node is not installed, so the runtime checks were skipped.")
    else:
        # Real payloads, so the render paths see realistic data.
        sys.path.insert(0, str(ROOT))
        from affidavit import help as help_mod  # noqa: E402

        tmp = Path(tempfile.mkdtemp(prefix="console-check-"))
        try:
            help_json = tmp / "help.json"
            docs_json = tmp / "docs.json"
            harness = tmp / "harness.js"

            help_json.write_text(json.dumps(help_mod.as_dict()), encoding="utf-8")
            docs_json.write_text(json.dumps({
                "documents": [
                    {"id": 1, "title_guess": "Engagement Letter", "doc_type": "Letter",
                     "doc_date": "2024-02-03", "date_source": "filename", "page_count": 2,
                     "pdf_status": "ok", "needs_ocr": 0, "ocr_quality": "text",
                     "ocr_quality_label": "text", "needs_verification": False,
                     "privilege_flags": [], "dup_count": 1, "tags": {},
                     "collection_names": [], "canonical_src": "a.pdf"},
                    {"id": 2, "title_guess": "Scanned Invoice", "doc_type": "Invoice",
                     "doc_date": "2024-04-30", "date_source": "labelled date field",
                     "page_count": 1, "pdf_status": "ok", "needs_ocr": 0,
                     "ocr_quality": "good", "ocr_quality_label": "96%",
                     "ocr_quality_advice": "", "needs_verification": False,
                     "privilege_flags": [], "dup_count": 1, "tags": {"exhibit": "B"},
                     "collection_names": ["Bundle A"], "canonical_src": "b.pdf"},
                    {"id": 3, "title_guess": "Poor Scan", "doc_type": "Receipt",
                     "doc_date": "", "date_source": "", "page_count": 1,
                     "pdf_status": "ok", "needs_ocr": 0, "ocr_quality": "poor",
                     "ocr_quality_label": "41%",
                     "ocr_quality_advice": "Read poorly.", "needs_verification": True,
                     "privilege_flags": [], "dup_count": 1, "tags": {},
                     "collection_names": [], "canonical_src": "c.pdf"},
                ],
                "collections": [{"id": 1, "name": "Bundle A", "item_count": 1,
                                 "page_total": 1, "created_by": "jane",
                                 "description": "", "version": 1}],
            }), encoding="utf-8")
            harness.write_text(RUNTIME_HARNESS, encoding="utf-8")

            proc = subprocess.run(
                [node, str(harness), str(console), str(help_json), str(docs_json)],
                capture_output=True, text=True, timeout=120,
            )
            out = (proc.stdout or "").strip()
            if not out:
                check("the runtime harness produced results", False,
                      (proc.stderr or "")[:300])
            else:
                try:
                    results = json.loads(out.splitlines()[-1])
                except json.JSONDecodeError:
                    check("the runtime harness produced valid results", False, out[:300])
                    results = []
                for r in results:
                    check(r["label"], r["ok"], r.get("detail", ""))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    if skipped:
        print(f"{len(skipped)} check group(s) skipped (no Node).")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CONSOLE SCRIPT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
