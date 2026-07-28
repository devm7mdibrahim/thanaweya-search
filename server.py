#!/usr/bin/env python3
"""خادم محلي للبحث في نتيجة الثانوية العامة 2026."""
import json
import os
import re
import sqlite3
import sys
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "results.db")
PORT = int(os.environ.get("PORT", 8000))
LIMIT = 100

local = threading.local()


def db():
    if not hasattr(local, "con"):
        local.con = sqlite3.connect(DB, check_same_thread=False)
        local.con.row_factory = sqlite3.Row
    return local.con


def normalize(s):
    s = re.sub(r"[ً-ْـ]", "", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip()


def search(q):
    q = (q or "").strip()
    if not q:
        return []
    con = db()
    if q.isdigit():
        rows = con.execute(
            "SELECT seating_no, name, total, status FROM students WHERE seating_no = ?",
            (int(q),)).fetchall()
        if rows:
            return [dict(r) for r in rows]
        return []
    # بحث بالاسم: كل كلمة لازم تظهر، والأخيرة تقبل بداية الكلمة فقط
    words = [w for w in re.split(r"\s+", normalize(q)) if w]
    if not words:
        return []
    terms = ['"%s"' % w.replace('"', "") for w in words[:-1]]
    terms.append('"%s"*' % words[-1].replace('"', ""))
    try:
        rows = con.execute(
            "SELECT s.seating_no, s.name, s.total, s.status "
            "FROM names n JOIN students s ON s.seating_no = n.rowid "
            "WHERE names MATCH ? ORDER BY s.total DESC LIMIT ?",
            (" AND ".join(terms), LIMIT)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/search":
            q = parse_qs(url.query).get("q", [""])[0]
            results = search(q)
            body = json.dumps(
                {"count": len(results), "limit": LIMIT, "results": results},
                ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not os.path.exists(DB):
        sys.exit("قاعدة البيانات غير موجودة. شغّل أولاً:  python3 build_db.py")
    total = db().execute("SELECT COUNT(*) FROM students").fetchone()[0]
    url = f"http://localhost:{PORT}"
    print(f"عدد الطلاب: {total:,}")
    print(f"الموقع يعمل على: {url}   (اضغط Ctrl+C للإيقاف)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nتم الإيقاف.")
