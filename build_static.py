#!/usr/bin/env python3
"""يبني نسخة ثابتة (static) صالحة للنشر على GitHub Pages.

يقرأ results.db ثم:
  1. يبني قاعدة مضغوطة (أرقام بدل النصوص المكررة + فهرس FTS5 بدون محتوى)
  2. يقسّمها إلى أجزاء أصغر من حدّ GitHub (100 ميجا للملف)
  3. يكتب config.json الخاص بـ sql.js-httpvfs
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "results.db")
SITE = os.path.join(HERE, "docs")           # GitHub Pages يقدر يخدم مجلد docs مباشرة
DBDIR = os.path.join(SITE, "db")
TMP = os.path.join(HERE, "_static.db")

PAGE_SIZE = 4096
CHUNK = 8 * 1024 * 1024                     # 8 ميجا لكل جزء (أقل من حدّ GitHub بكثير)
VENDOR_SRC = os.path.join(HERE, "vendor")   # مرفوعة مع المشروع


def build_db():
    for p in (TMP, TMP + "-journal"):
        if os.path.exists(p):
            os.remove(p)

    src = sqlite3.connect(SRC)
    statuses = [r[0] for r in src.execute(
        "SELECT DISTINCT status FROM students ORDER BY status")]
    codes = {s: i for i, s in enumerate(statuses)}
    print("الحالات:", [s.strip() for s in statuses])

    out = sqlite3.connect(TMP)
    out.executescript(f"""
        PRAGMA page_size = {PAGE_SIZE};
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
    """)
    out.execute("CREATE TABLE s(id INTEGER PRIMARY KEY, n TEXT, t INTEGER, c INTEGER)")
    # فهرس بدون محتوى: يخزّن الفهرس فقط، أصغر بكثير
    out.execute("CREATE VIRTUAL TABLE ix USING fts5(n, content='', "
                "tokenize='unicode61 remove_diacritics 2')")

    print("جاري النسخ ...", flush=True)
    rows = src.execute("SELECT seating_no, name, name_norm, total, status FROM students")
    n = 0

    def gen():
        nonlocal n
        while True:
            batch = rows.fetchmany(20000)
            if not batch:
                return
            recs, idx = [], []
            for seat, name, norm, total, status in batch:
                # الدرجة بنصف درجة → عدد صحيح (نضربها في 2)
                t = None if total is None else int(round(total * 2))
                recs.append((seat, name, t, codes[status]))
                idx.append((seat, norm))
            n += len(batch)
            print(f"  ... {n:,}", flush=True)
            yield recs, idx

    for recs, idx in gen():
        out.executemany("INSERT INTO s VALUES (?,?,?,?)", recs)
        out.executemany("INSERT INTO ix(rowid, n) VALUES (?,?)", idx)
    out.commit()

    print("جاري ضغط الفهرس ...", flush=True)
    out.execute("INSERT INTO ix(ix) VALUES('optimize')")
    out.commit()
    out.execute("VACUUM")
    out.close()
    src.close()
    return statuses, n


def split_and_config(statuses, count):
    os.makedirs(DBDIR, exist_ok=True)
    for f in os.listdir(DBDIR):
        os.remove(os.path.join(DBDIR, f))

    size = os.path.getsize(TMP)
    assert CHUNK % PAGE_SIZE == 0, "حجم الجزء يجب أن يكون مضاعفاً لحجم الصفحة"

    with open(TMP, "rb") as fh:
        i = 0
        while True:
            buf = fh.read(CHUNK)
            if not buf:
                break
            # آخر جزء لازم يتكمّل لحجم الجزء الكامل حتى لا تختل الحسابات
            if len(buf) < CHUNK:
                buf += b"\0" * (CHUNK - len(buf))
            with open(os.path.join(DBDIR, f"r.sqlite3.{i:03d}"), "wb") as o:
                o.write(buf)
            i += 1

    json.dump({
        "serverMode": "chunked",
        "requestChunkSize": PAGE_SIZE,
        "databaseLengthBytes": size,
        "urlPrefix": "r.sqlite3.",
        "suffixLength": 3,
        "serverChunkSize": CHUNK,
    }, open(os.path.join(DBDIR, "config.json"), "w"))

    json.dump({"statuses": [s.strip() for s in statuses], "count": count},
              open(os.path.join(SITE, "meta.json"), "w"), ensure_ascii=False)

    print(f"قاعدة البيانات: {size/1e6:.1f} ميجا في {i} أجزاء")
    return size, i


BACKEND = r"""<script src="vendor/index.js"></script>
<script src="app.js"></script>
<script id="backend">
/* مصدر البيانات: قاعدة SQLite ثابتة تُقرأ من المتصفح عبر HTTP Range */
(async () => {
  const st = document.getElementById('status');
  const inp = document.getElementById('q');
  const LIMIT = 100, WINDOW = 300, MAXBYTES = 25 * 1024 * 1024;
  const STATUS = __STATUSES__;
  const base = location.href.split('#')[0];
  const U = p => new URL(p, base).toString();

  inp.disabled = true;
  st.textContent = 'جاري تحميل قاعدة البيانات...';

  let worker;
  try{
    worker = await createDbWorker(
      [{ from: 'jsonconfig', configUrl: U('db/config.json') }],
      U('vendor/sqlite.worker.js'), U('vendor/sql-wasm.wasm'), MAXBYTES);
  }catch(e){
    console.error(e);
    st.textContent = 'تعذّر تحميل قاعدة البيانات. حدّث الصفحة.';
    return;
  }
  inp.disabled = false;
  st.textContent = '';
  inp.focus();

  const rowsOf = res => !res.length ? [] : res[0].values.map(v => ({
    seating_no: v[0],
    name: v[1],
    total: v[2] == null ? null : v[2] / 2,   // خزّنّاها مضروبة في 2
    status: STATUS[v[3]]
  }));

  /* نصفّر العدّاد قبل كل بحث ليكون السقف لكل عملية بحث لا للجلسة كلها */
  const q = (sql, params) => { worker.worker.bytesRead = 0;
                               return worker.db.exec(sql, params); };
  const none = { count: 0, limit: LIMIT, results: [] };

  initApp(async term => {
    term = term.trim();
    if(!term) return none;
    let rows;

    if(/^\d+$/.test(term)){
      rows = rowsOf(await q('SELECT id,n,t,c FROM s WHERE id=?', [Number(term)]));
    }else{
      const words = normalize(term).split(' ').filter(Boolean);
      if(!words.length) return none;
      // كل الكلمات مطلوبة، والأخيرة تقبل بداية الكلمة (حرف واحد لا يكفي)
      const expr = words.map((w, i) => {
        const t = '"' + w.replace(/"/g, '') + '"';
        return (i === words.length - 1 && w.length >= 2) ? t + '*' : t;
      }).join(' AND ');

      const hits = await q('SELECT rowid FROM ix WHERE ix MATCH ? LIMIT ?',
                           [expr, WINDOW]);
      const ids = hits.length ? hits[0].values.map(v => v[0]) : [];
      if(!ids.length) return none;
      rows = rowsOf(await q(`SELECT id,n,t,c FROM s WHERE id IN (${ids.join(',')})`));
    }

    rows.sort((a, b) => (b.total ?? -1) - (a.total ?? -1));
    const results = rows.slice(0, LIMIT);
    return { count: results.length, limit: LIMIT, results };
  });
})();
</script>"""


def page(statuses):
    src = open(os.path.join(HERE, "index.html")).read()
    head = src[:src.index('<script src="app.js">')]
    body = BACKEND.replace("__STATUSES__",
                           json.dumps([s.strip() for s in statuses], ensure_ascii=False))
    open(os.path.join(SITE, "index.html"), "w").write(head + body + "\n</body>\n</html>\n")
    shutil.copy(os.path.join(HERE, "app.js"), SITE)
    shutil.copy(os.path.join(HERE, "style.css"), SITE)
    shutil.copytree(os.path.join(HERE, "fonts"), os.path.join(SITE, "fonts"),
                    dirs_exist_ok=True)
    # يمنع فهرسة بيانات الطلاب في محركات البحث (البحث داخل الموقع يظل يعمل)
    open(os.path.join(SITE, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")
    print("تم بناء index.html و app.js")


def vendor():
    dst = os.path.join(SITE, "vendor")
    os.makedirs(dst, exist_ok=True)
    if not os.path.isdir(VENDOR_SRC):
        sys.exit("ملفات sql.js-httpvfs غير موجودة في " + VENDOR_SRC)
    for f in ("index.js", "sqlite.worker.js", "sql-wasm.wasm"):
        shutil.copy(os.path.join(VENDOR_SRC, f), dst)
    print("تم نسخ ملفات sql.js-httpvfs")


if __name__ == "__main__":
    if not os.path.exists(SRC):
        sys.exit("شغّل build_db.py أولاً")
    os.makedirs(SITE, exist_ok=True)
    st, cnt = build_db()
    split_and_config(st, cnt)
    page(st)
    vendor()
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    os.remove(TMP)
    print("تم بناء المجلد:", SITE)
