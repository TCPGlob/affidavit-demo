"""Tests for the collection workflow: tick documents, name a bundle, export.

Runs the real review console in-process against a throwaway database, so it
never touches working state.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import collections as col  # noqa: E402
from affidavit import db, review  # noqa: E402
from affidavit.config import load_config  # noqa: E402
from affidavit.docxwriter import read_docx_text  # noqa: E402

PORT = 8807
BASE = f"http://127.0.0.1:{PORT}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = BASE + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _OPENER.open(req, timeout=15) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {"_bytes": len(body)}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"_error": raw[:200].decode("utf-8", "replace")}


def main() -> int:
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not cond:
            failures.append(label)

    root = Path(__file__).resolve().parent
    cfg = load_config(root)

    tmp = root / "work" / "_colltest"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    # Point the whole thing at a scratch database and scratch output folder.
    cfg.db_path = tmp / "coll.sqlite3"
    cfg.output_dir = tmp / "output"
    cfg.ensure_dirs()

    conn = db.connect(cfg.db_path)
    db.init(conn)

    # Seed a small library rather than depending on a prior pipeline run.
    doc_ids = []
    for i, (title, src, needs_ocr) in enumerate([
        ("Engagement Letter", "01 - Agreements/Engagement Letter.pdf", 0),
        ("Records Retention Policy", "05 - Misc/Records Retention Policy.pdf", 0),
        ("Receipt HV-2291", "03 - Financial/Receipt HV-2291.png", 1),
        ("Contact list", "05 - Misc/Contact list.txt", 0),
    ], start=1):
        pdf = tmp / f"src{i}.pdf"
        _make_pdf(pdf, title)
        doc_id = db.upsert_document(
            conn, sha256=f"seed{i}", canonical_src=src, ext=".pdf",
            pdf_path=str(pdf), pdf_status="ok", page_count=i,
            title_guess=title, doc_type="Document" if i != 3 else "Receipt",
            doc_date=f"2024-0{i}-15", needs_ocr=needs_ocr, has_text_layer=0 if needs_ocr else 1,
            text_fingerprint=f"fp{i}",
            # profiled_at marks conversion and metadata reading as finished.
            # Export refuses documents still being prepared, so the seed data
            # has to look finished.
            profiled_at=db.utcnow(),
        )
        doc_ids.append(doc_id)
    conn.commit()

    try:
        # ---------------- naming rules -----------------------------------
        try:
            db.create_collection(conn, "  ", "", "tester")
            check("reject an empty collection name", False, "no error raised")
        except db.CollectionError:
            check("reject an empty collection name", True)

        cid = db.create_collection(conn, "Harbourview Exhibit Bundle",
                                   "Volume 1", "jane")
        check("create a collection", cid > 0)

        try:
            db.create_collection(conn, "Harbourview Exhibit Bundle", "", "raj")
            check("reject a duplicate collection name", False, "no error raised")
        except db.CollectionError:
            check("reject a duplicate collection name", True)

        cid2 = db.create_collection(conn, 'Bad/Name: With*Illegal?Chars',
                                    "", "raj")
        c2 = db.get_collection(conn, cid2)
        check("sanitise illegal characters in the folder name",
              c2["name"] == "Bad-Name- With-Illegal-Chars", f"got={c2['name']!r}")

        # ---------------- membership -------------------------------------
        added = db.add_to_collection(conn, cid, doc_ids, "jane")
        check("add documents to a collection", added == len(doc_ids), f"added={added}")
        added_again = db.add_to_collection(conn, cid, doc_ids, "raj")
        check("adding the same document twice is a no-op", added_again == 0)

        # The same document can live in a second collection under a new name.
        db.add_to_collection(conn, cid2, [doc_ids[0]], "raj")
        db.set_item_field(conn, cid2, doc_ids[0], "display_name", "Different name here")
        name_in_1 = db.collection_items(conn, cid)[0]["display_name"]
        name_in_2 = db.collection_items(conn, cid2)[0]["display_name"]
        check("per-collection display names are independent",
              name_in_1 == "" and name_in_2 == "Different name here",
              f"{name_in_1!r} vs {name_in_2!r}")

        # ---------------- ordering ---------------------------------------
        db.set_item_field(conn, cid, doc_ids[0], "display_name", "Engagement Letter (signed)")
        first_before = db.collection_items(conn, cid)[0]["id"]
        db.move_item(conn, cid, first_before, 1)
        first_after = db.collection_items(conn, cid)[0]["id"]
        check("moving an item down changes the order", first_after != first_before)
        # Move the *same* item back up: it is now at index 1, so move that one.
        db.move_item(conn, cid, first_before, -1)
        check("moving it back restores the order",
              db.collection_items(conn, cid)[0]["id"] == first_before)
        db.move_item(conn, cid, first_before, -1)
        check("moving the first item up is a safe no-op",
              db.collection_items(conn, cid)[0]["id"] == first_before)
        positions = [i["position"] for i in db.collection_items(conn, cid)]
        check("positions stay contiguous from 1",
              positions == list(range(1, len(positions) + 1)), str(positions))

        # ---------------- tags -------------------------------------------
        db.set_tags(conn, doc_ids[1], {"exhibit": "B", "witness": "M. Reed"})
        db.set_tags(conn, doc_ids[1], {"converted_by": "extractor"}, source="auto")
        tags = db.tags_for(conn, doc_ids[1])
        check("user tags persist", tags.get("exhibit") == "B" and tags.get("witness") == "M. Reed")
        check("auto tags coexist with user tags", tags.get("converted_by") == "extractor")

        # ---------------- conflict detection (shared pool safety) ---------
        # Two people read the same item, both edit, and the second must be told
        # rather than silently overwriting the first.
        v_seen = db.collection_items(conn, cid)[0]["version"]
        v_new = db.set_item_field(conn, cid, doc_ids[0], "display_name",
                                  "First editor", expected_version=v_seen)
        check("a versioned write bumps the version", v_new == v_seen + 1,
              f"{v_seen} -> {v_new}")
        try:
            db.set_item_field(conn, cid, doc_ids[0], "display_name",
                              "Second editor", expected_version=v_seen)
            check("a stale write is refused", False, "overwrite was allowed")
        except db.ConflictError as exc:
            check("a stale write is refused", True)
            check("the conflicting value is reported back",
                  exc.current.get("current_value") == "First editor",
                  str(exc.current))
        current_value = next(i for i in db.collection_items(conn, cid)
                             if i["id"] == doc_ids[0])["display_name"]
        check("the first editor's value survived the stale write",
              current_value == "First editor", f"got={current_value!r}")

        fresh_version = next(i for i in db.collection_items(conn, cid)
                             if i["id"] == doc_ids[0])["version"]
        db.set_item_field(conn, cid, doc_ids[0], "display_name",
                          "Second editor", expected_version=fresh_version)
        check("reloading and retrying succeeds",
              next(i for i in db.collection_items(conn, cid)
                   if i["id"] == doc_ids[0])["display_name"] == "Second editor")

        db.set_item_field(conn, cid, doc_ids[0], "display_name", "Script write")
        check("omitting the version keeps the old behaviour for scripts",
              next(i for i in db.collection_items(conn, cid)
                   if i["id"] == doc_ids[0])["display_name"] == "Script write")

        col_version = db.get_collection(conn, cid)["version"]
        db.set_collection_fields(conn, cid, name="Renamed By First",
                                 expected_version=col_version)
        try:
            db.set_collection_fields(conn, cid, description="Second's description",
                                     expected_version=col_version)
            check("a stale collection edit is refused", False, "overwrite was allowed")
        except db.ConflictError:
            check("a stale collection edit is refused", True)
        check("the collection rename survived",
              db.get_collection(conn, cid)["name"] == "Renamed By First")
        cid_name = db.get_collection(conn, cid)["name"]
        db.set_collection_fields(conn, cid, name="Harbourview Exhibit Bundle")

        # Restore the display name the export assertions below expect.
        db.set_item_field(conn, cid, doc_ids[0], "display_name",
                          "Engagement Letter (signed)")

        # ---------------- export -----------------------------------------
        result = col.export_collection(conn, cfg, cid, username="jane")
        bundle = Path(result["bundle"])
        check("bundle folder created", bundle.exists())
        check("all four documents exported", len(result["exported"]) == 4,
              f"exported={len(result['exported'])}")
        check("bundle is inside the collections output folder",
              cfg.collections_dir in bundle.parents, str(bundle))

        pdfs = sorted((bundle / "PDFs").glob("*.pdf"))
        check("numbered PDFs written", len(pdfs) == 4, f"found={len(pdfs)}")
        check("PDFs are zero-padded and sequential",
              [p.name[:3] for p in pdfs] == ["001", "002", "003", "004"],
              str([p.name[:3] for p in pdfs]))
        check("custom display name is used in the file name",
              any("Engagement Letter (signed)" in p.name for p in pdfs),
              str([p.name for p in pdfs]))
        check("default file names come from the document title",
              any("Records Retention Policy" in p.name for p in pdfs))
        check("no 'document.pdf' fallback names",
              not any(p.name.endswith(" - document.pdf") for p in pdfs))

        cover = next(bundle.glob("*.docx"), None)
        check("cover Word document written", cover is not None)
        if cover:
            text = read_docx_text(cover)
            check("cover document names the collection", "Harbourview Exhibit Bundle" in text)
            check("cover document lists the documents", "Records Retention Policy" in text)
            check("cover document explains the PDFs folder", "PDFs folder" in text)
            check("cover document shows the order", "001 - " in text)

        check("index.csv written", (bundle / "index.csv").exists())
        check("manifest.json written", (bundle / "manifest.json").exists())
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        check("manifest records the exporter", manifest["collection"]["exported_by"] == "jane")
        check("manifest totals match", manifest["totals"]["documents"] == 4)
        check("manifest records the OCR warning",
              any("OCR" in (d.get("reason") or "") for d in manifest["documents"]))

        # Re-export must be clean, not additive.
        again = col.export_collection(conn, cfg, cid, username="raj")
        check("re-export does not duplicate files",
              len(list((bundle / "PDFs").glob("*.pdf"))) == 4,
              f"found={len(list((bundle / 'PDFs').glob('*.pdf')))}")
        check("re-export records the new exporter",
              json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
              ["collection"]["exported_by"] == "raj")

        # ---------------- removal ----------------------------------------
        db.remove_from_collection(conn, cid, [doc_ids[3]])
        check("remove a document from a collection",
              len(db.collection_items(conn, cid)) == 3)
        after_removal = col.export_collection(conn, cfg, cid, username="jane")
        check("removing from a collection does not delete the document",
              conn.execute("SELECT COUNT(*) c FROM documents WHERE id=?",
                           (doc_ids[3],)).fetchone()["c"] == 1)
        check("re-export after removal has three documents",
              len(after_removal["exported"]) == 3)

        # ---------------- export refusals --------------------------------
        empty_cid = db.create_collection(conn, "Empty Bundle", "", "jane")
        try:
            col.export_collection(conn, cfg, empty_cid, username="jane")
            check("refuse to export an empty collection", False, "no error raised")
        except db.CollectionError:
            check("refuse to export an empty collection", True)

        # A document the watcher has not finished preparing. Exporting it would
        # produce an unnamed, undated file, so it must be refused.
        pending_pdf = tmp / "pending.pdf"
        _make_pdf(pending_pdf, "Not Ready Yet")
        pending_id = db.upsert_document(
            conn, sha256="pending1", canonical_src="pending.pdf", ext=".pdf",
            pdf_path=str(pending_pdf), pdf_status="pending",
            title_guess="Notice of Motion",
        )
        conn.commit()
        pending_cid = db.create_collection(conn, "Pending Bundle", "", "jane")
        db.add_to_collection(conn, pending_cid, [pending_id], "jane")
        try:
            col.export_collection(conn, cfg, pending_cid, username="jane")
            check("refuse to export a document still being prepared", False,
                  "it exported an unfinished document")
        except db.CollectionError as exc:
            check("refuse to export a document still being prepared", True)
            check("and it says which document",
                  "still being prepared" in str(exc), str(exc)[:70])

        # Once prepared, the same collection exports.
        conn.execute("UPDATE documents SET profiled_at=?, pdf_status='ok' WHERE id=?",
                     (db.utcnow(), pending_id))
        conn.commit()
        result_pending = col.export_collection(conn, cfg, pending_cid, username="jane")
        check("it exports once preparation has finished",
              len(result_pending["exported"]) == 1)
        check("and the file is named, not just 'document'",
              "document.pdf" not in result_pending["exported"][0]["file_name"],
              result_pending["exported"][0]["file_name"])

        # ---------------- delete -----------------------------------------
        db.delete_collection(conn, cid2)
        check("deleting a collection removes it", db.get_collection(conn, cid2) is None)
        check("deleting a collection leaves the document",
              conn.execute("SELECT COUNT(*) c FROM documents WHERE id=?",
                           (doc_ids[0],)).fetchone()["c"] == 1)

        # ---------------- HTTP surface -----------------------------------
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT),
                                    review._make_handler(conn, cfg))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        try:
            status, body = call("/api/help")
            check("help endpoint serves the glossary",
                  status == 200 and any(g["term"] == "Collection"
                                        for g in body.get("glossary", [])))

            status, body = call("/api/documents")
            check("documents endpoint returns tags", status == 200 and
                  any(isinstance(d.get("tags"), dict) for d in body.get("documents", [])))
            check("documents endpoint returns collection membership",
                  any("collection_names" in d for d in body.get("documents", [])))

            status, body = call("/api/collections")
            check("collections endpoint responds", status == 200)
            live = [c["name"] for c in body.get("collections", [])]
            finished = [c["name"] for c in body.get("finished", [])]
            check("an exported bundle leaves the live list",
                  "Harbourview Exhibit Bundle" not in live, str(live))
            check("but it is still listed as finished",
                  "Harbourview Exhibit Bundle" in finished, str(finished))
            check("the finished folder is reported",
                  body.get("finished_dir", "").endswith("finished"), body.get("finished_dir", ""))

            status, body = call("/api/team")
            check("team endpoint responds without auth", status == 200)
            check("team endpoint explains that sign-in is off",
                  body.get("auth_enabled") is False and bool(body.get("note")),
                  str(body.get("note"))[:60])
            check("team endpoint still reports activity",
                  isinstance(body.get("activity"), list))

            status, body = call("/api/collections/create",
                                {"name": "Created Over HTTP", "description": "via api"})
            check("create a collection over HTTP",
                  status == 200 and body.get("ok") and "Created Over HTTP" in
                  [c["name"] for c in body.get("collections", [])])
            new_cid = body.get("collection_id")

            status, body = call("/api/collections/action",
                                {"action": "add", "collection_id": new_cid,
                                 "doc_ids": doc_ids[:2]})
            check("add documents over HTTP", status == 200 and body.get("ok"))

            status, body = call("/api/collections/action",
                                {"action": "name_item", "collection_id": new_cid,
                                 "doc_id": doc_ids[0], "display_name": "Renamed in bundle"})
            check("rename an item over HTTP", status == 200 and body.get("ok"))

            status, body = call(f"/api/collections/{new_cid}")
            check("collection detail returns its items",
                  status == 200 and len(body.get("items", [])) == 2)

            status, body = call("/api/collections/export", {"collection_id": new_cid})
            check("export over HTTP succeeds", status == 200 and body.get("ok"))
            check("export reports the bundle path",
                  "Created Over HTTP" in str(body.get("bundle", "")), str(body.get("bundle")))
            check("export reports the cover document", bool(body.get("cover_doc")))

            status, body = call("/api/collections/action",
                                {"action": "delete", "collection_id": new_cid})
            check("delete a collection over HTTP", status == 200 and body.get("ok"))

            status, body = call("/api/collections/action",
                                {"action": "nonsense", "collection_id": cid})
            check("unknown action is rejected", status == 400, f"status={status}")

            status, body = call("/api/collections/create", {"name": "  "})
            check("empty name rejected over HTTP", status == 400, f"status={status}")

            status, body = call("/api/collections/create", {"name": "Harbourview Exhibit Bundle"})
            check("duplicate name rejected over HTTP", status == 400, f"status={status}")
        finally:
            httpd.shutdown()

    finally:
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL COLLECTION CHECKS PASSED")
    return 0


def _make_pdf(path: Path, title: str) -> None:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), title, fontsize=13)
    page.insert_text((72, 120), f"Reference document for {title}.", fontsize=10)
    doc.save(str(path))
    doc.close()


if __name__ == "__main__":
    raise SystemExit(main())
