/* واجهة البحث في نتيجة الثانوية العامة 2026.
   لا تعرف شيئاً عن مصدر البيانات — يُمرَّر لها عبر initApp(searchFn).
   searchFn(q) -> Promise<{count, limit, results:[{seating_no,name,total,status}]}> */

const MAX_DEGREE = 320;
const AR = n => String(n).replace(/\d/g, d => "٠١٢٣٤٥٦٧٨٩"[d]);

const form = document.getElementById('form');
const qEl = document.getElementById('q');
const statusEl = document.getElementById('status');
const out = document.getElementById('results');
const overlay = document.getElementById('overlay');
const clearBtn = document.getElementById('clear');

let SEARCH = null, seq = 0, current = null, lastFocus = null, results = [];
let lastQ = null;                 // آخر نص تم البحث عنه فعلاً
const DEBOUNCE = 450;             // ملّي ثانية بعد آخر حرف
const MIN_CHARS = 2;              // أقل عدد حروف للبحث بالاسم

const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const isFail = r => /راسب|دور ثان|غياب|محروم/.test(r.status || '');
const pctOf = r => r.total == null ? null : r.total / MAX_DEGREE * 100;

/* توحيد شكل الحروف العربية — نفس منطق build_db.py */
function normalize(s){
  return s.replace(/[ً-ْـ]/g, '')
          .replace(/[أإآٱ]/g, 'ا')
          .replace(/ة/g, 'ه').replace(/ى/g, 'ي')
          .replace(/ؤ/g, 'و').replace(/ئ/g, 'ي')
          .replace(/\s+/g, ' ').trim();
}

/* ---------------- قائمة النتائج ---------------- */
function card(r, i){
  const pct = pctOf(r);
  return `<div class="card${isFail(r) ? ' fail' : ''}" tabindex="0" role="button" data-i="${i}">
    <div class="info">
      <div class="nm">${esc(r.name)}</div>
      <div class="meta">
        <span class="seat">رقم الجلوس: ${esc(r.seating_no)}</span>
        <span class="tag">${esc(r.status || '—')}</span>
      </div>
    </div>
    <div class="score">
      <b>${r.total ?? '—'}</b>
      <i>${pct == null ? '' : pct.toFixed(1) + '%'}</i>
    </div>
    <div class="bar" style="width:${pct == null ? 0 : pct.toFixed(1)}%"></div>
  </div>`;
}

const SKELETON = '<div class="sk"><div class="l"><i></i><i></i></div><div class="r"></div></div>'.repeat(3);

function emptyState(q){
  return `<div class="empty">
    <div class="ic">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/>
      <path d="M20 20l-3.6-3.6"/></svg>
    </div>
    <p>لا توجد نتائج مطابقة لـ <b>"${esc(q)}"</b></p>
    <p style="margin-top:6px;font-size:.85rem">
      جرّب كتابة الاسم بشكل مختلف، أو ابحث برقم الجلوس</p>
  </div>`;
}

async function run(force){
  const q = qEl.value.trim();
  clearBtn.classList.toggle('on', !!q);
  if(!q){ lastQ = ''; results = []; out.innerHTML = ''; statusEl.textContent = ''; return; }
  if(!force && q === lastQ) return;   // نفس النص — لا داعي لإعادة البحث
  lastQ = q;
  results = [];

  const my = ++seq;
  statusEl.innerHTML = '<span class="dot"></span> جاري البحث...';
  out.innerHTML = SKELETON;

  try{
    const data = await SEARCH(q);
    if(my !== seq) return;
    if(!data.count){
      statusEl.textContent = '';
      out.innerHTML = emptyState(q);
      return;
    }
    results = data.results;
    statusEl.innerHTML = '<span class="dot"></span> ' + (data.count >= data.limit
      ? `أول ${data.count} نتيجة — اكتب الاسم بالكامل لنتائج أدق`
      : `${data.count} نتيجة`);
    out.innerHTML = results.map(card).join('');
  }catch(e){
    console.error(e);
    if(my !== seq) return;
    statusEl.textContent = '';
    out.innerHTML = '<div class="empty"><p>تعذّر إتمام البحث. حاول مرة أخرى.</p></div>';
  }
}

/* ---------------- شاشة التفاصيل ---------------- */
const CIRC = 2 * Math.PI * 80;

function openDetail(r, from){
  if(!r) return;
  current = r; lastFocus = from || null;
  const fail = isFail(r), pct = pctOf(r);
  const color = fail ? 'var(--bad)' : 'var(--ok)';

  dName.textContent  = r.name;
  dSeat.textContent  = 'رقم الجلوس: ' + r.seating_no;
  dTotal.textContent = r.total ?? '—';
  dPct.textContent   = pct == null ? '' : 'النسبة ' + pct.toFixed(2) + '%';
  dPct.style.color   = color;
  dArc.style.stroke  = color;
  dArc.style.strokeDashoffset = CIRC * (1 - (pct ?? 0) / 100);
  dTag.textContent   = r.status || '—';
  dTag.style.color   = color;
  dTag.style.background = `color-mix(in srgb, ${color} 16%, transparent)`;

  rSeat.textContent   = r.seating_no;
  rTotal.textContent  = (r.total ?? '—') + ' / ' + MAX_DEGREE;
  rPct.textContent    = pct == null ? '—' : pct.toFixed(2) + '%';
  rStatus.textContent = r.status || '—';

  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  document.getElementById('close').focus();
}

function closeDetail(){
  overlay.classList.remove('open');
  document.body.style.overflow = '';
  if(lastFocus) lastFocus.focus();
}

/* ---------------- تحميل كصورة PNG ---------------- */
const FONT = 'Cairo, "Segoe UI", Tahoma, "Geeza Pro", system-ui, sans-serif';

function roundRect(c, x, y, w, h, r){
  c.beginPath();
  if(c.roundRect) c.roundRect(x, y, w, h, r);
  else{
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);         c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }
}

/* يقلّل حجم الخط ثم يقسم الاسم على سطرين إن لزم */
function nameLines(c, name, maxW){
  for(const size of [52, 46, 40, 35]){
    c.font = `700 ${size}px ${FONT}`;
    if(c.measureText(name).width <= maxW) return { size, lines: [name] };
  }
  c.font = `700 35px ${FONT}`;
  const words = name.split(' '), lines = [''];
  for(const w of words){
    const test = lines.at(-1) ? lines.at(-1) + ' ' + w : w;
    if(c.measureText(test).width <= maxW || !lines.at(-1)) lines[lines.length - 1] = test;
    else lines.push(w);
  }
  return { size: 35, lines: lines.slice(0, 3) };
}

function draw(r){
  const W = 1000, H = 1300, S = 2;
  const cv = document.createElement('canvas');
  cv.width = W * S; cv.height = H * S;
  const c = cv.getContext('2d');
  c.scale(S, S);
  c.textAlign = 'center';
  c.textBaseline = 'middle';
  c.direction = 'rtl';

  const fail = isFail(r), pct = pctOf(r) ?? 0;
  const accent = fail ? '#d93025' : '#0f9d58';

  const bg = c.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, '#eef3fb'); bg.addColorStop(1, '#dde7f7');
  c.fillStyle = bg; c.fillRect(0, 0, W, H);

  c.save();
  c.shadowColor = 'rgba(12,28,56,.18)'; c.shadowBlur = 40; c.shadowOffsetY = 14;
  c.fillStyle = '#fff'; roundRect(c, 60, 60, 880, 1180, 40); c.fill();
  c.restore();

  c.save();
  roundRect(c, 60, 60, 880, 1180, 40); c.clip();
  const hg = c.createLinearGradient(60, 60, 940, 270);
  hg.addColorStop(0, '#1b6ef3'); hg.addColorStop(1, '#0b47a8');
  c.fillStyle = hg; c.fillRect(60, 60, 880, 210);
  c.restore();

  c.fillStyle = '#fff';
  c.font = `700 42px ${FONT}`;
  c.fillText('نتيجة الثانوية العامة ٢٠٢٦', W / 2, 140);
  c.fillStyle = 'rgba(255,255,255,.85)';
  c.font = `400 26px ${FONT}`;
  c.fillText('النظام الحديث — جمهورية مصر العربية', W / 2, 200);

  const { size, lines } = nameLines(c, r.name, 760);
  c.fillStyle = '#16202e';
  c.font = `700 ${size}px ${FONT}`;
  let y = 355 - (lines.length - 1) * size * 0.65;
  for(const ln of lines){ c.fillText(ln, W / 2, y); y += size * 1.3; }

  c.font = `600 26px ${FONT}`;
  const seatTxt = 'رقم الجلوس: ' + AR(r.seating_no);
  const sw = c.measureText(seatTxt).width + 56;
  c.fillStyle = '#eef2f9';
  roundRect(c, (W - sw) / 2, 425, sw, 56, 28); c.fill();
  c.fillStyle = '#5b6a80';
  c.fillText(seatTxt, W / 2, 454);

  const cx = W / 2, cy = 700, rad = 140;
  c.lineWidth = 26; c.lineCap = 'round';
  c.strokeStyle = '#e8eef7';
  c.beginPath(); c.arc(cx, cy, rad, 0, Math.PI * 2); c.stroke();
  if(pct > 0){
    c.strokeStyle = accent;
    c.beginPath();
    c.arc(cx, cy, rad, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (pct / 100));
    c.stroke();
  }
  c.fillStyle = '#16202e';
  c.font = `800 78px ${FONT}`;
  c.fillText(r.total == null ? '—' : AR(r.total), cx, cy - 12);
  c.fillStyle = '#68758a';
  c.font = `400 26px ${FONT}`;
  c.fillText('من ٣٢٠', cx, cy + 52);

  c.fillStyle = accent;
  c.font = `700 34px ${FONT}`;
  c.fillText('النسبة ' + AR(pct.toFixed(2)) + '٪', cx, 900);

  c.font = `700 30px ${FONT}`;
  const st = (r.status || '—').trim();
  const tw = c.measureText(st).width + 72;
  c.fillStyle = fail ? '#fdeceb' : '#e7f5ee';
  roundRect(c, (W - tw) / 2, 950, tw, 64, 32); c.fill();
  c.fillStyle = accent;
  c.fillText(st, cx, 983);

  c.strokeStyle = '#e3e8f0'; c.lineWidth = 2; c.lineCap = 'butt';
  c.beginPath(); c.moveTo(140, 1075); c.lineTo(860, 1075); c.stroke();

  c.fillStyle = '#8b98ab';
  c.font = `400 23px ${FONT}`;
  c.fillText('تم الاستخراج في ' + new Date().toLocaleDateString('ar-EG'), cx, 1125);
  c.font = `400 20px ${FONT}`;
  c.fillText('هذه نسخة غير رسمية — النتيجة المعتمدة من وزارة التربية والتعليم', cx, 1168);

  return cv;
}

/* ---------------- رابط مباشر: #2001970 ---------------- */
async function fromHash(){
  const seat = location.hash.replace(/^#/, '').trim();
  if(!/^\d+$/.test(seat)) return;
  qEl.value = seat; lastQ = seat;
  const data = await SEARCH(seat);
  if(data.count){
    results = data.results;
    out.innerHTML = results.map(card).join('');
    statusEl.textContent = '١ نتيجة';
    openDetail(results[0]);
  }
}

/* ---------------- التشغيل ---------------- */
function initApp(searchFn){
  SEARCH = searchFn;

  let t;
  const cancel = () => clearTimeout(t);

  form.addEventListener('submit', e => {   // زر البحث/Enter يبحث فوراً
    e.preventDefault(); cancel(); qEl.blur(); run(true);
  });

  qEl.addEventListener('input', () => {
    cancel();
    const v = qEl.value.trim();
    clearBtn.classList.toggle('on', !!v);
    if(!v){ run(); return; }                       // مسح فوري
    // حرف واحد بالاسم يطابق عشرات الآلاف — انتظر حرفين على الأقل
    if(!/^\d+$/.test(v) && v.length < MIN_CHARS) return;
    t = setTimeout(() => run(), DEBOUNCE);
  });

  out.addEventListener('click', e => {
    const el = e.target.closest('.card');
    if(el) openDetail(results[+el.dataset.i], el);
  });
  out.addEventListener('keydown', e => {
    if(e.key !== 'Enter' && e.key !== ' ') return;
    const el = e.target.closest('.card');
    if(el){ e.preventDefault(); openDetail(results[+el.dataset.i], el); }
  });

  clearBtn.onclick = () => { qEl.value = ''; qEl.focus(); run(); };
  document.getElementById('close').onclick = closeDetail;
  overlay.addEventListener('click', e => { if(e.target === overlay) closeDetail(); });
  document.addEventListener('keydown', e => {
    if(e.key === 'Escape' && overlay.classList.contains('open')) closeDetail();
  });

  document.getElementById('pdf').onclick = () => window.print();
  document.getElementById('png').onclick = async () => {
    if(!current) return;
    if(document.fonts?.ready) await document.fonts.ready;
    draw(current).toBlob(b => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = `نتيجة-${current.seating_no}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }, 'image/png');
  };

  addEventListener('hashchange', fromHash);
  fromHash();
}
