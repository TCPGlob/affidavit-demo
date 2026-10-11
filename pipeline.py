#!/usr/bin/env python
"""Document preparation pipeline - produces PDF bundles for Zibbit.

    python pipeline.py demo                  create a sample intake folder
    python pipeline.py run                   ingest, convert, tag
    python pipeline.py review                open the console (tick, name, convert)
    python pipeline.py collections           list bundles
    python pipeline.py bundle --docs 1,2,3 --name "My Bundle"
    python pipeline.py create-user ...       add an account for shared use

Typical flow: demo -> run -> review -> tick documents -> name the collection ->
Convert & export -> import the PDFs folder into Zibbit.

Everything is local. No network. No client document leaves the machine.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from affidavit import assemble as assemble_mod  # noqa: E402
from affidavit import auth, collections, db, fixtures, pipeline, reconcile, review  # noqa: E402
from affidavit.config import CONFIG_FILENAME, Config, load_config  # noqa: E402

BANNER = "=" * 66


def _open_db(cfg: Config, reset: bool = False):
    conn = db.connect(cfg.db_path)
    db.init(conn)
    if reset:
        db.reset(conn)
    return conn


def cmd_init(args) -> int:
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / CONFIG_FILENAME
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)")
        return 0
    cfg = Config()
    path.write_text(cfg.to_json(), encoding="utf-8")
    cfg.source_dir = root / cfg.source_dir
    cfg.work_dir = root / cfg.work_dir
    cfg.output_dir = root / cfg.output_dir
    cfg.ensure_dirs()
    print(f"Wrote {path}")
    print("Edit it to set the court, file number, parties and deponent,")
    print("then drop client documents into:", cfg.source_dir)
    return 0


def cmd_demo(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    cfg.ensure_dirs()
    result = fixtures.generate(cfg.source_dir, clean=not args.keep)
    print(BANNER)
    print("  DEMO INTAKE CREATED")
    print(BANNER)
    print(f"  {result['written']} synthetic documents in {result['dest']}")
    print()
    print("  Note: this is fabricated test data shaped like a real Ontario")
    print("  matter. Never mix it with actual client files.")
    print()
    print("  Next:  python pipeline.py run")
    return 0


def cmd_run(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg, reset=args.fresh)
    try:
        result = pipeline.run(
            conn, cfg, fresh=args.fresh, skip_ingest=args.skip_ingest,
            ocr=not args.no_ocr, ocr_force=args.ocr_force,
        )
        reconcile.reconcile(conn, cfg)
    finally:
        conn.close()

    if not result["tools"].get("libreoffice", False):
        print("  NOTE: LibreOffice is not installed, so Office formats")
        print("  (DOCX/XLSX/PPTX) could not be converted to real PDFs. Those")
        print("  files appear as PLACEHOLDERS and are flagged in the report.")
        print("  Install it and re-run for a clean result.\n")
    print("  Next:  python pipeline.py review")
    return 0


def cmd_share(args) -> int:
    """Start reachable by colleagues, and print the address to give them."""
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        addresses = share_addresses(args.port)
        print(BANNER)
        print("  SHARING THIS APP WITH COLLEAGUES")
        print(BANNER)
        if addresses:
            for kind, addr in addresses:
                print(f"  {kind:<26} {addr}")
        else:
            print("  Could not work out this machine's address automatically.")
            print(f"  Share:  http://<this-machine-ip>:{args.port}/")
        print()
        print("  The person running this keeps the window open. Others need")
        print("  nothing installed - just the address above in a browser.")
        print()
        print("  IF A COLLEAGUE CANNOT CONNECT:")
        print("    - Windows Firewall may have blocked Python. Re-run and choose")
        print("      Allow, or allow Python on Private networks in Firewall settings.")
        print("    - Someone at home cannot use a 192.168/10.x address. See")
        print("      SETUP.md - 'Working from home'.")
        print()
        review.serve(
            conn, cfg,
            port=args.port,
            open_browser=not args.no_browser,
            host="0.0.0.0",
            require_auth=not args.no_auth,
            secure_cookie=args.secure_cookie,
        )
    finally:
        conn.close()
    return 0


def share_addresses(port: int, host: str = "0.0.0.0") -> list[tuple[str, str]]:
    """Work out the addresses a colleague could use, best first.

    Tailscale addresses come first because they work from anywhere and are
    already encrypted; a plain LAN address only works on the same network.
    """
    import socket

    found: list[str] = []
    try:
        # Does not send traffic; just asks the routing table which local
        # address would be used to reach the outside world.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass

    out: list[tuple[str, str]] = []
    for ip in found:
        if ip.startswith("100."):
            # 100.64.0.0/10 is the carrier-grade NAT range Tailscale uses.
            out.append(("Tailscale (works anywhere)", f"http://{ip}:{port}/"))
    for ip in found:
        if not ip.startswith("100."):
            out.append(("Same office / same wifi", f"http://{ip}:{port}/"))
    return out


def cmd_review(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        if args.demo:
            print("=" * 66)
            print("  DEMO MODE")
            print("=" * 66)
            print("  Synthetic documents only. Do not upload client material to a")
            print("  demo instance - anyone with the link can reach it.\n")
            if not cfg.source_dir.exists() or not any(cfg.source_dir.iterdir()):
                fixtures.generate(cfg.source_dir, clean=True)
                print(f"  Created sample documents in {cfg.source_dir}")
            docs = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
            if not docs:
                print("  Running the pipeline over them...")
                pipeline.run(conn, cfg, fresh=False, skip_ingest=False)
            print()
        elif conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 0:
            # Nothing has been processed yet. Rather than dropping someone into
            # an empty console with no clue what to do, prepare sample documents
            # so there is something to look at and learn from.
            print("=" * 66)
            print("  FIRST RUN - preparing sample documents")
            print("=" * 66)
            print("  Nothing has been processed yet, so sample documents are being")
            print("  created to give you something to work with.")
            print("  Replace them with real documents at any time by clearing the")
            print(f"  intake folder: {cfg.source_dir}\n")
            try:
                fixtures.generate(cfg.source_dir, clean=True)
                pipeline.run(conn, cfg, fresh=False, skip_ingest=False)
                print("  Sample documents ready.\n")
            except Exception as exc:  # noqa: BLE001
                print(f"  Could not prepare samples ({exc}).")
                print("  The console will still start; add documents and run:")
                print("    python pipeline.py demo")
                print("    python pipeline.py run\n")

        review.serve(
            conn, cfg,
            port=args.port,
            open_browser=not args.no_browser,
            host=args.host,
            require_auth=args.require_auth or args.users,
            secure_cookie=args.secure_cookie,
        )
    finally:
        conn.close()
    return 0


def cmd_create_user(args) -> int:
    import getpass

    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        auth.init_auth(conn)
        password = args.password
        if not password:
            password = getpass.getpass("Password (min 10 chars): ")
            again = getpass.getpass("Confirm password: ")
            if password != again:
                print("Passwords did not match.")
                return 1
        uid = auth.create_user(conn, args.username, args.name, password, args.role)
        print(f"Created user #{uid}: {args.username} "
              f"({args.name or args.username}, role={args.role})")
        print("Start the shared console with:")
        print("  python pipeline.py review --host 0.0.0.0 --require-auth --secure-cookie")
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        conn.close()
    return 0


def cmd_users(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        auth.init_auth(conn)
        users = auth.list_users(conn)
        if not users:
            print("No users yet. Create one:")
            print("  python pipeline.py create-user --username you --name \"Your Name\" "
                  "--role admin")
            return 0
        print(f"{'username':<18} {'name':<24} {'role':<10} {'reviewed':>8}  last login")
        print("-" * 84)
        for u in users:
            state = " (disabled)" if u["disabled"] else ""
            print(f"{u['username']:<18} {u['display_name'][:23]:<24} {u['role']:<10} "
                  f"{u['reviewed']:>8}  {u['last_login'] or 'never'}{state}")
        print()
        if args.reset_password:
            import getpass

            pw = getpass.getpass(f"New password for {args.reset_password}: ")
            print("Updated." if auth.set_password(conn, args.reset_password, pw)
                  else "No such user.")
    finally:
        conn.close()
    return 0


def cmd_audit(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        auth.init_auth(conn)
        entries = auth.recent_audit(conn, args.limit)
        if not entries:
            print("No audit entries yet.")
            return 0
        for e in entries:
            doc = f"doc {e['doc_id']}" if e["doc_id"] else "     "
            title = (e["title_guess"] or "")[:34]
            print(f"{e['at'][:19]}  {e['username']:<14} {doc:<7} {e['action']:<13} "
                  f"{title:<34} {e['detail'][:40]}")
    finally:
        conn.close()
    return 0


def cmd_collections(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        rows = db.list_collections(conn)
        if not rows:
            print("No collections yet. Create one in the console:")
            print("  python pipeline.py review")
            print("or from the command line:")
            print("  python pipeline.py collections --new \"My Bundle\" --docs 1,2,3")
            return 0
        print(f"{'id':>4}  {'documents':>9}  {'pages':>6}  {'exported':<20}  name")
        print("-" * 88)
        for c in rows:
            when = (c["exported_at"] or "never")[:19]
            flags = []
            if c["needs_ocr"]:
                flags.append(f"{c['needs_ocr']} OCR")
            if c["not_converted"]:
                flags.append(f"{c['not_converted']} not pdf")
            suffix = f"  ({', '.join(flags)})" if flags else ""
            print(f"{c['id']:>4}  {c['item_count']:>9}  {c['page_total']:>6}  {when:<20}  "
                  f"{c['name']}{suffix}")
        return 0
    finally:
        conn.close()


def cmd_bundle(args) -> int:
    """Create a collection from document ids and export it, without the browser."""
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        doc_ids = [int(x) for x in re.split(r"[,\s]+", args.docs.strip()) if x.strip()]
        if not doc_ids:
            print("Give at least one document id with --docs.")
            return 1

        # Reuse an existing collection of the same name -- that is what someone
        # re-running the command expects, not a duplicate-name error. Both
        # --collection and --name are honoured.
        wanted = (args.collection or args.name or "").strip()
        cid = None
        if wanted:
            existing = [c for c in db.list_collections(conn) if c["name"] == wanted]
            if existing:
                cid = existing[0]["id"]
                print(f"Reusing existing collection #{cid}: {wanted}")

        if cid is None:
            cid = db.create_collection(conn, args.name or args.collection or "Bundle",
                                       args.description, args.user)

        # Adding is idempotent, so re-running tops up rather than duplicating.
        added = db.add_to_collection(conn, cid, doc_ids, args.user)
        print(f"Collection #{cid}: {added} document(s) added, "
              f"{len(db.collection_items(conn, cid))} in total")
        result = collections.export_collection(conn, cfg, cid, username=args.user)

        print(BANNER)
        print("  BUNDLE EXPORTED")
        print(BANNER)
        print(f"  {len(result['exported'])} document(s), {result['pages']} page(s)")
        print(f"  {result['bundle']}")
        print()
        print("  Import the PDFs folder into Zibbit:")
        print(f"    {Path(result['bundle']) / 'PDFs'}")
        for e in result["exported"]:
            print(f"      {e['file_name']}")
        if result["skipped"]:
            print(f"\n  NOT INCLUDED ({len(result['skipped'])}):")
            for e in result["skipped"]:
                print(f"      {e['title'][:44]:<46} {e['reason'][:50]}")
        print()
        return 0
    except db.CollectionError as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        conn.close()


def cmd_ocr(args) -> int:
    """Read scanned documents. Safe to re-run."""
    root = Path(args.root).resolve()
    cfg = load_config(root)
    if args.lang:
        cfg.ocr_lang = args.lang
    if args.max_pages:
        cfg.ocr_max_pages = args.max_pages
    if args.dpi:
        cfg.ocr_dpi = args.dpi
    conn = _open_db(cfg)
    try:
        print(BANNER)
        print("  OCR  -  reading scanned documents (local, no cloud)")
        print(BANNER)
        stats = pipeline.run_ocr_stage(conn, cfg, {}, force=args.force)
        print()
        if not stats["available"]:
            print("  Install Tesseract, then re-run this command:")
            print("    winget install UB-Mannheim.TesseractOCR")
            print("  For French too, install the fra language data and set")
            print('    "ocr_lang": "eng+fra"   in affidavit.config.json')
            return 1
        print(f"  read        {stats['succeeded']}")
        print(f"  no text     {stats['empty']}")
        print(f"  failed      {stats['failed']}")
        print(f"  characters  {stats['chars']:,}")
        print()
        print("  Note: the exported bundle still contains the ORIGINAL scans.")
        print("  The searchable copies live in work/ocr/ and are used only for")
        print("  reading, titles, dates and search.")
        return 0
    finally:
        conn.close()


def cmd_assemble(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        result = assemble_mod.assemble(conn, cfg, stamp=args.stamp)
        counts = result["counts"]
        print(BANNER)
        print("  PACKAGE ASSEMBLED")
        print(BANNER)
        print(f"  Schedule A (produce)       {counts.get('A', 0)}")
        print(f"  Schedule B (privilege)     {counts.get('B', 0)}")
        print(f"  Schedule C (no longer held){counts.get('C', 0)}")
        print(f"  Excluded (not relevant)    {counts.get('excluded', 0)}")
        print(f"  Unclassified               {counts.get('unclassified', 0)}")
        if counts.get("unclassified", 0):
            print()
            print("  NOT READY TO FILE - unclassified documents remain.")
        print()
        print(f"  Package : {cfg.package_dir}")
        print(f"  Index   : {cfg.schedules_dir / 'index.docx'}   <- open in Word")
        print(f"  Index   : {cfg.schedules_dir / 'index.csv'}")
        if (cfg.schedules_dir / "index.xlsx").exists():
            print(f"  Index   : {cfg.schedules_dir / 'index.xlsx'}")
        print(f"  Report  : {cfg.reports_dir / 'reconciliation.md'}")
        print()
    finally:
        conn.close()
    return 0


def cmd_reconcile(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        reconcile.reconcile(conn, cfg)
    finally:
        conn.close()
    # Exit 0 even when problems are listed. The report is the deliverable, and
    # "a .docx could not be converted" is something to read, not a failed run --
    # returning non-zero here made a documented state look like a crash.
    return 0


def cmd_status(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root)
    conn = _open_db(cfg)
    try:
        total = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        if not total:
            print("No documents yet. Run: python pipeline.py demo && python pipeline.py run")
            return 0
        rows = conn.execute(
            """SELECT COALESCE(dec.schedule,'(unreviewed)') s, COUNT(*) c
               FROM documents d LEFT JOIN decisions dec ON dec.doc_id=d.id
               GROUP BY s ORDER BY s"""
        ).fetchall()
        print(BANNER)
        print("  STATUS")
        print(BANNER)
        for r in rows:
            print(f"  {r['s']:<16} {r['c']}")
        print()
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Turn a folder of documents into numbered PDF bundles for Zibbit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--root",
        default=str(here),
        help="workspace folder holding intake/, work/ and output/ (default: script folder)",
    )

    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write affidavit.config.json to edit")
    s.add_argument("--force", action="store_true", help="overwrite an existing config")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("demo", help="generate a synthetic intake folder")
    s.add_argument("--keep", action="store_true", help="do not wipe the existing intake folder")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("run", help="ingest, convert, extract, read scans")
    s.add_argument("--fresh", action="store_true", help="discard all state and start over")
    s.add_argument("--skip-ingest", action="store_true", help="reuse the existing file inventory")
    s.add_argument("--no-ocr", action="store_true",
                   help="skip reading scans (OCR also runs on its own: pipeline.py ocr)")
    s.add_argument("--ocr-force", action="store_true",
                   help="re-read scans that were already OCR'd")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("review", help="open the review console")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="do not auto-open a browser")
    s.add_argument(
        "--host", default="127.0.0.1",
        help="interface to bind. Use 0.0.0.0 to let the team connect (default: localhost only)",
    )
    s.add_argument(
        "--require-auth", action="store_true",
        help="require sign-in (mandatory before exposing this to a network)",
    )
    s.add_argument(
        "--users", action="store_true",
        help="plain-language alias for --require-auth: each person gets their own "
             "sign-in. The first account is created in the browser.",
    )
    s.add_argument(
        "--secure-cookie", action="store_true",
        help="mark the session cookie Secure - use when serving over HTTPS",
    )
    s.add_argument(
        "--demo", action="store_true",
        help="create synthetic documents and skip sign-in, for showing the tool to a client. "
             "Never use this with real client material.",
    )
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("create-user", help="add a reviewer account for shared use")
    s.add_argument("--username", required=True)
    s.add_argument("--name", default="", help="display name, e.g. \"Jane Smith\"")
    s.add_argument("--password", default="", help="omit to be prompted (recommended)")
    s.add_argument("--role", default="reviewer", choices=list(auth.ROLES))
    s.set_defaults(func=cmd_create_user)

    s = sub.add_parser("users", help="list reviewer accounts")
    s.add_argument("--reset-password", default="", metavar="USERNAME")
    s.set_defaults(func=cmd_users)

    s = sub.add_parser("audit", help="show who changed what")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("assemble", help="(legacy) build the affidavit-style package")
    s.add_argument(
        "--stamp",
        action="store_true",
        help="overlay 'Schedule X - N' footers on each page (off by default)",
    )
    s.set_defaults(func=cmd_assemble)

    s = sub.add_parser("collections", help="list bundles and their contents")
    s.set_defaults(func=cmd_collections)

    s = sub.add_parser(
        "share",
        help="let colleagues connect, and print the address to give them",
    )
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--secure-cookie", action="store_true",
                   help="use when the address is HTTPS (a VPN that adds a padlock)")
    s.add_argument("--no-auth", action="store_true",
                   help="NOT recommended: drop the sign-in requirement")
    s.set_defaults(func=cmd_share)

    s = sub.add_parser("ocr", help="read scanned documents (requires Tesseract)")
    s.add_argument("--force", action="store_true",
                   help="re-read documents that were already OCR'd")
    s.add_argument("--lang", default="", help='Tesseract language, e.g. "eng" or "eng+fra"')
    s.add_argument("--dpi", type=int, default=0, help="render resolution (default 200)")
    s.add_argument("--max-pages", type=int, default=0,
                   help="give up after this many pages per document (default 25)")
    s.set_defaults(func=cmd_ocr)

    s = sub.add_parser(
        "bundle",
        help="create a collection from document ids and export it (no browser needed)",
    )
    s.add_argument("--docs", required=True, help="document ids, e.g. 3,7,9")
    s.add_argument("--name", default="", help="collection name to create")
    s.add_argument("--collection", default="", help="reuse an existing collection by name")
    s.add_argument("--description", default="")
    s.add_argument("--user", default="cli", help="who to attribute this to")
    s.set_defaults(func=cmd_bundle)

    s = sub.add_parser("reconcile", help="verify every source file was accounted for")
    s.set_defaults(func=cmd_reconcile)

    s = sub.add_parser("status", help="show review progress")
    s.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
