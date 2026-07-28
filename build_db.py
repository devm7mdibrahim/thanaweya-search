#!/usr/bin/env python3
"""يبني قاعدة بيانات SQLite من ملف الإكسل (مرة واحدة فقط)."""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(HERE), "نتيجة ثانوية عامة نظام حديث (1).xlsx")
DB = os.path.join(HERE, "results.db")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def normalize(s):
    """توحيد شكل الحروف العربية حتى ينجح البحث مهما اختلف الإملاء."""
    s = re.sub(r"[ً-ْـ]", "", s)   # التشكيل والتطويل
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip()


def shared_strings(z):
    try:
        raw = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(raw).findall(NS + "si")]


def rows(z, strings):
    """قراءة الصفوف بالتدريج حتى لا يمتلئ الرام."""
    with z.open("xl/worksheets/sheet1.xml") as fh:
        for event, el in ET.iterparse(fh, events=("end",)):
            if el.tag != NS + "row":
                continue
            out = []
            for c in el.findall(NS + "c"):
                v = c.find(NS + "v")
                if v is None:
                    t = c.find(NS + "is/" + NS + "t")
                    out.append(t.text if t is not None else "")
                elif c.get("t") == "s":
                    out.append(strings[int(v.text)])
                else:
                    out.append(v.text or "")
            yield out
            el.clear()


def main():
    if not os.path.exists(XLSX):
        sys.exit("لم يتم العثور على ملف الإكسل: " + XLSX)
    if os.path.exists(DB):
        os.remove(DB)

    con = sqlite3.connect(DB)
    con.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE students (
            seating_no INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            name_norm  TEXT NOT NULL,
            total      REAL,
            status     TEXT
        );
    """)

    z = zipfile.ZipFile(XLSX)
    strings = shared_strings(z)
    it = rows(z, strings)
    next(it)  # سطر العناوين

    def batch():
        n = 0
        for r in it:
            r += [""] * (4 - len(r))
            seat, name, total, status = r[0], (r[1] or "").strip(), r[2], r[3]
            if not seat or not seat.strip().isdigit():
                continue
            try:
                total = float(total)
            except (TypeError, ValueError):
                total = None
            n += 1
            if n % 100000 == 0:
                print(f"  ... {n:,} صف", flush=True)
            yield (int(seat), name, normalize(name), total, status)

    print("جاري استيراد البيانات ...", flush=True)
    con.executemany("INSERT OR IGNORE INTO students VALUES (?,?,?,?,?)", batch())
    con.commit()

    print("جاري بناء فهرس البحث بالاسم ...", flush=True)
    con.executescript("""
        CREATE VIRTUAL TABLE names USING fts5(
            name_norm, content='students', content_rowid='seating_no',
            tokenize='unicode61 remove_diacritics 2');
        INSERT INTO names(rowid, name_norm) SELECT seating_no, name_norm FROM students;
        INSERT INTO names(names) VALUES('optimize');
        CREATE INDEX idx_total ON students(total);
    """)
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    con.execute("VACUUM")
    con.close()
    print(f"تم! {count:,} طالب في {DB}")


if __name__ == "__main__":
    main()
