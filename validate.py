"""
validate.py — Validierungs-Tool für PolitCheck-Daten.

Startet einen lokalen Webserver auf http://localhost:8765
Öffne die URL im Browser, dann kannst du:
  - Aussagen löschen / wiederherstellen / Score korrigieren
  - Falsche Widersprüche entfernen
  - Parteizugehörigkeit ergänzen oder korrigieren

Verwendung:
  py validate.py

Nach der Validierung:
  py generate_data.py   (exportiert bereinigten Stand)
"""

import json
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

DB_PATH = Path("data/politcheck.db")
PORT    = 8765

# ── DB ────────────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate():
    with get_conn() as conn:
        for sql in [
            "ALTER TABLE aussagen ADD COLUMN geloescht INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception:
                pass


# ── HTML (eingebettet) ────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>PolitCheck – Validierung</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}

header{background:#1e293b;border-bottom:1px solid #334155;padding:.9rem 2rem;
  display:flex;align-items:center;gap:1.8rem;position:sticky;top:0;z-index:10}
header h1{font-size:1rem;font-weight:700;color:#f8fafc;white-space:nowrap}
.tabs{display:flex;gap:.3rem}
.tab{padding:.4rem 1rem;border:1px solid #334155;border-radius:6px;cursor:pointer;
  font-size:.82rem;color:#94a3b8;background:transparent;transition:all .15s}
.tab.active{background:#6366f1;color:#fff;border-color:#6366f1}
.tab:hover:not(.active){color:#e2e8f0;border-color:#475569}
#header-info{font-size:.78rem;color:#64748b;margin-left:auto}

.main{padding:1.2rem 2rem;max-width:1400px;margin:0 auto}

.filters{display:flex;gap:.6rem;margin-bottom:1rem;flex-wrap:wrap;align-items:center}
.filters input,.filters select{background:#1e293b;border:1px solid #334155;
  color:#e2e8f0;padding:.38rem .75rem;border-radius:6px;font-size:.83rem}
.filters input:focus,.filters select:focus{outline:none;border-color:#6366f1}
.count{font-size:.78rem;color:#64748b}

/* KARTEN */
.card-list{display:flex;flex-direction:column;gap:.5rem}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;
  padding:.85rem 1.1rem;display:flex;gap:.9rem;align-items:flex-start}
.card.deleted{opacity:.38;border-color:rgba(239,68,68,.3)}
.card-body{flex:1;min-width:0}
.card-text{font-size:.88rem;line-height:1.55;font-style:italic;
  color:#cbd5e1;margin-bottom:.45rem}
.card-meta{display:flex;gap:.6rem;flex-wrap:wrap;font-size:.74rem;
  color:#64748b;align-items:center}
.meta-name{font-weight:600;color:#94a3b8}
.badge{padding:.12rem .45rem;border-radius:4px;font-size:.69rem;font-weight:600}
.badge-score{background:rgba(239,68,68,.15);color:#f87171}
.badge-cat{background:rgba(99,102,241,.15);color:#818cf8}
.badge-del{background:rgba(239,68,68,.18);color:#f87171}

.card-actions{display:flex;flex-direction:column;gap:.35rem;flex-shrink:0}
button{padding:.32rem .7rem;border-radius:6px;border:none;cursor:pointer;
  font-size:.77rem;font-weight:600;transition:all .15s;white-space:nowrap}
.btn-del{background:rgba(239,68,68,.15);color:#f87171}
.btn-del:hover{background:rgba(239,68,68,.3)}
.btn-restore{background:rgba(34,197,94,.13);color:#4ade80}
.btn-restore:hover{background:rgba(34,197,94,.28)}
.btn-save{background:rgba(99,102,241,.18);color:#818cf8}
.btn-save:hover{background:rgba(99,102,241,.32)}

.score-row{display:flex;align-items:center;gap:.35rem}
.score-row label{font-size:.7rem;color:#64748b}
.score-row input{width:46px;text-align:center;background:#0f172a;
  border:1px solid #334155;color:#e2e8f0;border-radius:5px;padding:.22rem;
  font-size:.8rem}

/* WIDERSPRÜCHE */
.wsp-block{background:#1e293b;border:1px solid #334155;border-radius:10px;
  padding:1rem 1.2rem;margin-bottom:.7rem}
.wsp-header{font-size:.88rem;font-weight:700;color:#f8fafc;margin-bottom:.75rem;
  display:flex;align-items:center;gap:.5rem}
.wsp-partei{font-weight:400;color:#64748b}
.wsp-item{border-left:2px solid #ef4444;padding:.55rem .85rem;margin-bottom:.5rem;
  background:#0f172a;border-radius:0 6px 6px 0;display:flex;gap:.8rem;align-items:flex-start}
.wsp-item:last-child{margin-bottom:0}
.wsp-body{flex:1;font-size:.82rem;line-height:1.5;color:#cbd5e1}
.wsp-erkl{font-size:.75rem;color:#94a3b8;margin-top:.3rem}
.wsp-dates{font-size:.7rem;color:#64748b;margin-top:.25rem}

/* PARTEIEN */
.ptable{width:100%;border-collapse:collapse;font-size:.84rem}
.ptable th{text-align:left;padding:.45rem .75rem;color:#64748b;font-weight:600;
  font-size:.71rem;text-transform:uppercase;letter-spacing:.05em;
  border-bottom:1px solid #334155}
.ptable td{padding:.45rem .75rem;border-bottom:1px solid #1e293b22}
.ptable tr:hover td{background:#1e293b44}
.partei-input{background:#1e293b;border:1px solid #334155;color:#e2e8f0;
  padding:.28rem .6rem;border-radius:6px;font-size:.82rem;width:200px}
.partei-input:focus{outline:none;border-color:#6366f1}
.missing{color:#f87171;font-style:italic}

.hidden{display:none!important}

.toast{position:fixed;bottom:1.3rem;right:1.5rem;background:#1e293b;
  border:1px solid #334155;border-radius:8px;padding:.6rem 1rem;
  font-size:.81rem;color:#4ade80;box-shadow:0 4px 24px #0009;z-index:999;
  transition:opacity .3s}
.toast.err{color:#f87171}
</style>
</head>
<body>
<header>
  <h1>PolitCheck – Validierung</h1>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('aussagen')">Aussagen</button>
    <button class="tab" onclick="switchTab('widersprueche')">Widersprüche</button>
    <button class="tab" onclick="switchTab('parteien')">Parteien</button>
  </div>
  <span id="header-info"></span>
</header>

<div class="main">

  <!-- TAB: AUSSAGEN -->
  <div id="tab-aussagen">
    <div class="filters">
      <input id="f-name"   placeholder="Politiker…"   oninput="renderAussagen()">
      <input id="f-partei" placeholder="Partei…"      oninput="renderAussagen()">
      <select id="f-score" onchange="renderAussagen()">
        <option value="">Alle Scores</option>
        <option value="8">Score ≥ 8</option>
        <option value="6">Score ≥ 6</option>
        <option value="5">Score ≥ 5</option>
        <option value="4">Score ≥ 4</option>
      </select>
      <select id="f-deleted" onchange="renderAussagen()">
        <option value="0">Nur aktive</option>
        <option value="1">Nur gelöschte</option>
        <option value="">Alle</option>
      </select>
      <span id="aussagen-count" class="count"></span>
    </div>
    <div id="aussagen-list" class="card-list"></div>
  </div>

  <!-- TAB: WIDERSPRÜCHE -->
  <div id="tab-widersprueche" class="hidden">
    <div class="filters">
      <input id="wf-name" placeholder="Politiker…" oninput="renderWsp()">
      <span id="wsp-count" class="count"></span>
    </div>
    <div id="wsp-list"></div>
  </div>

  <!-- TAB: PARTEIEN -->
  <div id="tab-parteien" class="hidden">
    <div class="filters">
      <input id="pf-name" placeholder="Politiker…" oninput="renderParteien()">
      <select id="pf-filter" onchange="renderParteien()">
        <option value="">Alle</option>
        <option value="missing">Ohne Partei</option>
      </select>
      <span id="parteien-count" class="count"></span>
    </div>
    <table class="ptable">
      <thead>
        <tr>
          <th>Politiker</th><th>Aktuelle Partei</th>
          <th>Neue Partei</th><th>Reden</th><th></th>
        </tr>
      </thead>
      <tbody id="parteien-body"></tbody>
    </table>
  </div>

</div><!-- .main -->

<script>
let AUSSAGEN = [], WIDERSPRUECHE = [], POLITIKER = [];

// ── UTILS ────────────────────────────────────────────────────────────────────
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function toast(msg, err=false){
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(()=>{ el.style.opacity='0'; setTimeout(()=>el.remove(),300); }, 2200);
}

async function api(method, path, body){
  const r = await fetch(path,{
    method,
    headers:{'Content-Type':'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

// ── TABS ─────────────────────────────────────────────────────────────────────
function switchTab(name){
  const names = ['aussagen','widersprueche','parteien'];
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active', names[i]===name));
  names.forEach(n=>document.getElementById('tab-'+n).classList.toggle('hidden', n!==name));
}

// ── AUSSAGEN ─────────────────────────────────────────────────────────────────
function renderAussagen(){
  const q      = document.getElementById('f-name').value.toLowerCase();
  const partei = document.getElementById('f-partei').value.toLowerCase();
  const minSc  = parseInt(document.getElementById('f-score').value)||0;
  const delF   = document.getElementById('f-deleted').value;

  const list = AUSSAGEN.filter(a=>{
    if(q      && !a.politiker.toLowerCase().includes(q))          return false;
    if(partei && !(a.partei||'').toLowerCase().includes(partei))  return false;
    if(minSc  && (a.polarisierungsgrad||0)<minSc)                 return false;
    if(delF==='0' && a.geloescht) return false;
    if(delF==='1' && !a.geloescht) return false;
    return true;
  });

  document.getElementById('aussagen-count').textContent = list.length + ' Aussagen';
  const container = document.getElementById('aussagen-list');
  container.innerHTML = '';

  list.forEach(a=>{
    const div = document.createElement('div');
    div.className = 'card'+(a.geloescht?' deleted':'');
    div.innerHTML = `
      <div class="card-body">
        <div class="card-text">"${esc(a.aussage)}"</div>
        <div class="card-meta">
          <span class="meta-name">${esc(a.politiker)}</span>
          <span>${esc(a.partei||'')}</span>
          <span>${esc(a.datum||'')}</span>
          <span class="badge badge-cat">${esc(a.kategorie||'')}</span>
          <span class="badge badge-score">${a.polarisierungsgrad||'?'}/10</span>
          ${a.geloescht?'<span class="badge badge-del">gelöscht</span>':''}
        </div>
      </div>
      <div class="card-actions">
        <div class="score-row">
          <label>Score</label>
          <input type="number" min="1" max="10" value="${a.polarisierungsgrad||5}"
                 data-id="${a.id}" class="score-inp">
          <button class="btn-save" data-id="${a.id}" onclick="saveScore(this)">✓</button>
        </div>
        ${a.geloescht
          ? `<button class="btn-restore" data-id="${a.id}" onclick="restoreAussage(this)">Wiederherstellen</button>`
          : `<button class="btn-del"     data-id="${a.id}" onclick="deleteAussage(this)">Löschen</button>`}
      </div>`;
    container.appendChild(div);
  });
}

async function deleteAussage(btn){
  const id = +btn.dataset.id;
  await api('POST',`/api/aussagen/${id}/delete`);
  AUSSAGEN.find(a=>a.id===id).geloescht = 1;
  renderAussagen(); toast('Aussage gelöscht');
}
async function restoreAussage(btn){
  const id = +btn.dataset.id;
  await api('POST',`/api/aussagen/${id}/restore`);
  AUSSAGEN.find(a=>a.id===id).geloescht = 0;
  renderAussagen(); toast('Aussage wiederhergestellt');
}
async function saveScore(btn){
  const id  = +btn.dataset.id;
  const inp = document.querySelector(`.score-inp[data-id="${id}"]`);
  const val = parseInt(inp.value);
  if(isNaN(val)||val<1||val>10){ toast('Score muss 1–10 sein',true); return; }
  await api('PATCH',`/api/aussagen/${id}`,{polarisierungsgrad:val});
  AUSSAGEN.find(a=>a.id===id).polarisierungsgrad = val;
  renderAussagen(); toast('Score gespeichert');
}

// ── WIDERSPRÜCHE ─────────────────────────────────────────────────────────────
function renderWsp(){
  const q = document.getElementById('wf-name').value.toLowerCase();
  const list = WIDERSPRUECHE.filter(p=>
    p.widersprueche.length>0 && (!q||p.politiker.toLowerCase().includes(q))
  );
  const total = list.reduce((s,p)=>s+p.widersprueche.length,0);
  document.getElementById('wsp-count').textContent = total+' Widersprüche';

  const container = document.getElementById('wsp-list');
  container.innerHTML='';
  list.forEach(p=>{
    const block = document.createElement('div');
    block.className='wsp-block';
    block.innerHTML=`<div class="wsp-header">${esc(p.politiker)}<span class="wsp-partei">${esc(p.partei||'')}</span></div>`;

    p.widersprueche.forEach((w,idx)=>{
      const item = document.createElement('div');
      item.className='wsp-item';
      item.innerHTML=`
        <div class="wsp-body">
          <div><strong>A:</strong> ${esc(w.aussage1||'')}</div>
          <div style="margin-top:.3rem"><strong>B:</strong> ${esc(w.aussage2||'')}</div>
          ${w.erklaerung?`<div class="wsp-erkl">${esc(w.erklaerung)}</div>`:''}
          <div class="wsp-dates">${esc(w.datum1||'')} → ${esc(w.datum2||'')}</div>
        </div>
        <button class="btn-del"
          data-pol="${esc(p.politiker)}" data-idx="${idx}"
          onclick="deleteWsp(this)">Löschen</button>`;
      block.appendChild(item);
    });
    container.appendChild(block);
  });
}

async function deleteWsp(btn){
  const politiker = btn.dataset.pol;
  const index     = +btn.dataset.idx;
  await api('POST','/api/widersprueche/delete',{politiker,index});
  const p = WIDERSPRUECHE.find(x=>x.politiker===politiker);
  if(p) p.widersprueche.splice(index,1);
  renderWsp(); toast('Widerspruch entfernt');
}

// ── PARTEIEN ─────────────────────────────────────────────────────────────────
function renderParteien(){
  const q      = document.getElementById('pf-name').value.toLowerCase();
  const filter = document.getElementById('pf-filter').value;
  const list   = POLITIKER.filter(p=>{
    if(q && !p.politiker.toLowerCase().includes(q)) return false;
    if(filter==='missing' && p.partei && p.partei!=='?' && p.partei!=='') return false;
    return true;
  });
  document.getElementById('parteien-count').textContent = list.length+' Politiker';

  const tbody = document.getElementById('parteien-body');
  tbody.innerHTML='';
  list.forEach(p=>{
    const missing = !p.partei||p.partei==='?'||p.partei==='';
    const tr = document.createElement('tr');
    tr.innerHTML=`
      <td>${esc(p.politiker)}</td>
      <td class="${missing?'missing':''}">${esc(p.partei||'–')}</td>
      <td><input class="partei-input" placeholder="z.B. CDU/CSU"
            value="${esc(p.partei||'')}"
            data-pol="${esc(p.politiker)}"></td>
      <td>${p.anzahl_reden}</td>
      <td><button class="btn-save" data-pol="${esc(p.politiker)}"
            onclick="savePartei(this)">Speichern</button></td>`;
    tbody.appendChild(tr);
  });
}

async function savePartei(btn){
  const pol   = btn.dataset.pol;
  const input = document.querySelector(`.partei-input[data-pol="${pol}"]`);
  const partei = input ? input.value.trim() : '';
  await api('PATCH','/api/politiker/'+encodeURIComponent(pol),{partei});
  const p = POLITIKER.find(x=>x.politiker===pol);
  if(p) p.partei=partei;
  renderParteien(); toast('Partei gespeichert');
}

// ── INIT ─────────────────────────────────────────────────────────────────────
async function init(){
  try{
    [AUSSAGEN, WIDERSPRUECHE, POLITIKER] = await Promise.all([
      api('GET','/api/aussagen'),
      api('GET','/api/widersprueche'),
      api('GET','/api/politiker'),
    ]);
    const totalWsp = WIDERSPRUECHE.reduce((s,p)=>s+p.widersprueche.length,0);
    document.getElementById('header-info').textContent =
      `${AUSSAGEN.length} Aussagen · ${totalWsp} Widersprüche · ${POLITIKER.length} Politiker`;
    renderAussagen(); renderWsp(); renderParteien();
  }catch(e){ toast('Ladefehler: '+e.message,true); }
}
init();
</script>
</body>
</html>
"""


# ── HTTP HANDLER ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # kein Access-Log

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._html(HTML)

        elif path == "/api/aussagen":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, politiker, partei, datum, aussage, kategorie, "
                    "polarisierungsgrad, COALESCE(geloescht,0) AS geloescht "
                    "FROM aussagen ORDER BY polarisierungsgrad DESC"
                ).fetchall()
            self._json([dict(r) for r in rows])

        elif path == "/api/widersprueche":
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT politiker, partei, widersprueche FROM politikerprofile "
                    "WHERE widersprueche IS NOT NULL AND widersprueche != '[]'"
                ).fetchall()
            result = []
            for r in rows:
                wsps = json.loads(r["widersprueche"] or "[]")
                if wsps:
                    result.append({
                        "politiker":     r["politiker"],
                        "partei":        r["partei"],
                        "widersprueche": wsps,
                    })
            self._json(result)

        elif path == "/api/politiker":
            with get_conn() as conn:
                rows = conn.execute("""
                    SELECT politiker, MAX(partei) AS partei, COUNT(*) AS anzahl_reden
                    FROM reden
                    GROUP BY politiker
                    ORDER BY anzahl_reden DESC
                """).fetchall()
            self._json([dict(r) for r in rows])

        else:
            self.send_response(404); self.end_headers()

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path.endswith("/delete") and "/api/aussagen/" in path:
            aid = int(path.split("/")[3])
            with get_conn() as conn:
                conn.execute("UPDATE aussagen SET geloescht=1 WHERE id=?", (aid,))
                conn.commit()
            self._json({"ok": True})

        elif path.endswith("/restore") and "/api/aussagen/" in path:
            aid = int(path.split("/")[3])
            with get_conn() as conn:
                conn.execute("UPDATE aussagen SET geloescht=0 WHERE id=?", (aid,))
                conn.commit()
            self._json({"ok": True})

        elif path == "/api/widersprueche/delete":
            politiker = body["politiker"]
            index     = int(body["index"])
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT widersprueche FROM politikerprofile WHERE politiker=?",
                    (politiker,)
                ).fetchone()
                if row:
                    wsps = json.loads(row["widersprueche"] or "[]")
                    if 0 <= index < len(wsps):
                        wsps.pop(index)
                    conn.execute(
                        "UPDATE politikerprofile SET widersprueche=? WHERE politiker=?",
                        (json.dumps(wsps, ensure_ascii=False), politiker),
                    )
                    conn.commit()
            self._json({"ok": True})

        else:
            self.send_response(404); self.end_headers()

    # ── PATCH ────────────────────────────────────────────────────────────────
    def do_PATCH(self):
        path = urlparse(self.path).path
        body = self._body()

        if "/api/aussagen/" in path:
            aid  = int(path.split("/")[3])
            grad = body.get("polarisierungsgrad")
            if grad is not None:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE aussagen SET polarisierungsgrad=? WHERE id=?",
                        (int(grad), aid),
                    )
                    conn.commit()
            self._json({"ok": True})

        elif path.startswith("/api/politiker/"):
            politiker = unquote(path.split("/api/politiker/")[1])
            partei    = body.get("partei", "")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE reden SET partei=? WHERE politiker=?",
                    (partei, politiker),
                )
                conn.execute(
                    "UPDATE politikerprofile SET partei=? WHERE politiker=?",
                    (partei, politiker),
                )
                conn.commit()
            self._json({"ok": True})

        else:
            self.send_response(404); self.end_headers()


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        print(f"Datenbank nicht gefunden: {DB_PATH}")
        print("Fuehre zuerst 'py main.py extract' aus.")
        return

    migrate()

    url = f"http://localhost:{PORT}"
    print(f"PolitCheck Validierung laeuft auf {url}")
    print("Strg+C zum Beenden.")
    print()
    print("Nach der Validierung:")
    print("  py generate_data.py   (exportiert bereinigten Stand)")

    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    HTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
