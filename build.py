#!/usr/bin/env python3
import base64, os, re, json, html, hashlib, subprocess, tempfile

# Config por variables de entorno (con defaults para la Mac). El homelab las sobreescribe.
VAULT     = os.environ.get("ESCALADA_VAULT", "/Users/fferr/Documents/Obsidian/obsidian")
NOTE_NAME = os.environ.get("ESCALADA_NOTE", "Depto Escalada - Observaciones.md")
OUT       = os.environ.get("ESCALADA_OUT", "/Users/fferr/Downloads/Depto Escalada - Observaciones.html")

# Índice de todos los archivos del vault (para encontrar la nota e imágenes sin importar la carpeta)
_vault_index = {}
for _root, _dirs, _files in os.walk(VAULT):
    _dirs[:] = [d for d in _dirs if d != ".git"]
    for _f in _files:
        _vault_index.setdefault(_f.lower(), os.path.join(_root, _f))

def find_in_vault(filename):
    return _vault_index.get(filename.lower())

MD = find_in_vault(NOTE_NAME)
if not MD:
    raise SystemExit(f"No se encontró la nota '{NOTE_NAME}' en el vault.")
BIN_ID    = os.environ.get("ESCALADA_BIN_ID", "6a3e9ca0f5f4af5e2934e4e2")
# Access Key restringida (solo read+update de este bin). Segura para exponer públicamente.
ACCESS_KEY = os.environ.get("ESCALADA_ACCESS_KEY", "$2a$10$dbJGoj6KKdBebpjozyJcOunJtEoPatqvDQYriPXlQODG0ecN9J1M2")

# ---------- image embedding (resize to max 1600px, q70) ----------
_cache = {}
def resolve(name):
    """Find an image file anywhere in the vault by name, trying common extensions."""
    if os.path.splitext(name)[1]:  # has extension
        hit = find_in_vault(name)
        if hit:
            return hit
    base = os.path.splitext(name)[0]
    for ext in (".jpg", ".jpeg", ".JPG", ".JPEG", ".png", ".PNG", ".heic", ".HEIC"):
        hit = find_in_vault(base + ext)
        if hit:
            return hit
    for ext in ("",):  # fallback al comportamiento anterior
        p = os.path.join(VAULT, base + ext)
        if os.path.exists(p):
            return p
    return None

import shutil
_HAS_SIPS = shutil.which("sips") is not None

def _resize_jpeg(src, dst, max_px=1600, quality=70):
    """Resize/recompress to JPEG. Usa sips (macOS) o Pillow (Linux/homelab)."""
    if _HAS_SIPS:
        subprocess.run(["sips", "-Z", str(max_px), "-s", "format", "jpeg",
                        "-s", "formatOptions", str(quality), src, "--out", dst],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    from PIL import Image  # pip install pillow (en el homelab)
    im = Image.open(src)
    im = im.convert("RGB")
    im.thumbnail((max_px, max_px))
    im.save(dst, "JPEG", quality=quality)

def img_data_uri(name):
    if name in _cache:
        return _cache[name]
    src = resolve(name)
    if not src:
        print("  !! NO ENCONTRADA:", name)
        _cache[name] = ""
        return ""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
    _resize_jpeg(src, tmp)
    with open(tmp, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    os.remove(tmp)
    uri = "data:image/jpeg;base64," + b64
    _cache[name] = uri
    return uri

# ---------- markdown parsing ----------
EMBED_RE = re.compile(r'!\[\[([^\]\|]+?)(?:\|[^\]]*)?\]\]')

def extract_images(text):
    return EMBED_RE.findall(text)

def clean_text(text):
    text = EMBED_RE.sub("", text)
    return re.sub(r'\s+', ' ', text).strip()

def stable_id(text):
    return "x" + hashlib.md5(text.encode("utf-8")).hexdigest()[:10]

blocks = []
item_ids = []
with open(MD, encoding="utf-8") as f:
    for raw in f:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        # heading
        m = re.match(r'^(#{1,6})\s*(.*)$', line)
        if m:
            level, label = len(m.group(1)), m.group(2).strip()
            if not label:
                continue  # skip empty headings (e.g. lone "#")
            blocks.append({"t": "section" if level <= 2 else "subsection", "label": label})
            continue
        # checkbox item, possibly indented (tabs or spaces)
        m = re.match(r'^([ \t]*)-\s*\[( |x|X)\]\s*(.*)$', line)
        if m:
            indent, mark, rest = m.group(1), m.group(2), m.group(3)
            is_sub = len(indent) > 0
            imgs = extract_images(rest)
            txt = clean_text(rest)
            bid = stable_id(txt or "item-" + str(len(item_ids)))
            item_ids.append(bid)
            blocks.append({"t": "item", "id": bid, "text": txt, "imgs": imgs, "sub": is_sub})
            continue
        # other lines ignored

# ---------- build HTML ----------
rows = []
for b in blocks:
    if b["t"] == "section":
        rows.append(f'<h2 class="section">{html.escape(b["label"])}</h2>')
    elif b["t"] == "subsection":
        rows.append(f'<h3 class="subsection">{html.escape(b["label"])}</h3>')
    else:
        sub = " sub" if b.get("sub") else ""
        imgs_html = ""
        if b["imgs"]:
            thumbs = "".join(
                f'<img class="thumb" loading="lazy" src="{img_data_uri(n)}" alt="{html.escape(n)}" onclick="zoom(this.src)">'
                for n in b["imgs"] if img_data_uri(n)
            )
            if thumbs:
                imgs_html = f'<div class="imgs">{thumbs}</div>'
        txt = html.escape(b["text"]) or "<em>(sin descripción)</em>"
        rows.append(
            f'<div class="item{sub}" data-id="{b["id"]}">'
            f'<label class="row"><input type="checkbox" data-id="{b["id"]}">'
            f'<span class="txt">{txt}</span></label>'
            f'<div class="by" data-for="{b["id"]}"></div>'
            f'{imgs_html}</div>'
        )

body = "\n".join(rows)
ids_json = json.dumps(item_ids)

html_doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATL Escalada - Depto 1104 - Observaciones</title>
<style>
  :root {{
    --bg:#f5f5f4; --card:#fff; --ink:#1c1917; --muted:#78716c;
    --line:#e7e5e4; --accent:#16a34a; --accent-bg:#dcfce7;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:20px 16px 80px; }}
  header h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  .sub-hdr {{ color:var(--muted); font-size:.85rem; margin-bottom:16px; }}
  .progress-box {{ position:sticky; top:0; z-index:10; background:var(--bg); padding:10px 0; border-bottom:1px solid var(--line); }}
  .bar {{ height:10px; background:var(--line); border-radius:99px; overflow:hidden; }}
  .bar > i {{ display:block; height:100%; width:0; background:var(--accent); transition:width .3s; }}
  .bar-label {{ display:flex; justify-content:space-between; font-size:.8rem; color:var(--muted); margin-top:6px; }}
  .status {{ font-size:.75rem; color:var(--muted); }}
  .status.ok {{ color:var(--accent); }}
  .status.err {{ color:#dc2626; }}
  h2.section {{ font-size:1.15rem; margin:26px 0 6px; padding-bottom:4px; border-bottom:2px solid var(--ink); }}
  h3.subsection {{ font-size:.95rem; margin:16px 0 4px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
  .item {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:8px 0; }}
  .item.sub {{ margin-left:22px; }}
  .item.done {{ background:var(--accent-bg); border-color:#bbf7d0; }}
  .row {{ display:flex; gap:10px; align-items:flex-start; cursor:pointer; }}
  .row input {{ width:20px; height:20px; margin-top:1px; flex:0 0 auto; accent-color:var(--accent); cursor:pointer; }}
  .txt {{ font-size:.95rem; }}
  .item.done .txt {{ text-decoration:line-through; color:var(--muted); }}
  .by {{ font-size:.72rem; color:var(--accent); margin:4px 0 0 30px; min-height:0; }}
  .by:empty {{ margin:0; }}
  /* estado bloqueado: sin nombre cargado */
  body.locked .row input {{ cursor:not-allowed; opacity:.45; }}
  body.locked .name-prompt input {{ border-color:#f59e0b; background:#fffbeb; }}
  .hint {{ font-size:.78rem; color:#b45309; margin-top:4px; }}
  #toast {{ position:fixed; left:50%; bottom:24px; transform:translateX(-50%) translateY(20px);
    background:#1c1917; color:#fff; padding:11px 16px; border-radius:10px; font-size:.85rem;
    box-shadow:0 6px 24px rgba(0,0,0,.25); opacity:0; pointer-events:none; transition:.25s; max-width:90vw; z-index:200; }}
  #toast.show {{ opacity:1; transform:translateX(-50%) translateY(0); }}
  .imgs {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 0 30px; }}
  .thumb {{ width:120px; height:120px; object-fit:cover; border-radius:8px; border:1px solid var(--line); cursor:zoom-in; }}
  #lb {{ position:fixed; inset:0; background:rgba(0,0,0,.85); display:none; align-items:center; justify-content:center; z-index:100; cursor:zoom-out; }}
  #lb img {{ max-width:95vw; max-height:95vh; border-radius:6px; }}
  .name-prompt {{ font-size:.8rem; color:var(--muted); margin-top:6px; display:flex; align-items:center; gap:8px; }}
  .name-prompt input {{ font-size:.8rem; padding:3px 8px; border:1px solid var(--line); border-radius:6px;
    outline:none; min-width:160px; }}
  .name-prompt input:focus {{ border-color:var(--accent); }}
  #refreshBtn {{ margin-left:auto; font-size:.78rem; padding:5px 12px; white-space:nowrap;
    border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink); cursor:pointer; }}
  #refreshBtn:hover {{ border-color:var(--accent); color:var(--accent); }}
  @media print {{ #refreshBtn {{ display:none; }} }}
  @media print {{
    .progress-box, .name-prompt {{ position:static; }}
    .thumb {{ width:200px; height:auto; }}
    body {{ background:#fff; }}
    .item {{ break-inside:avoid; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>ATL Escalada — Depto 1104 — Observaciones</h1>
    <div class="sub-hdr">Lista compartida · el avance se sincroniza entre todos los que abran este archivo</div>
  </header>
  <div class="progress-box">
    <div class="bar"><i id="barfill"></i></div>
    <div class="bar-label"><span id="count">0 / 0</span><span id="status" class="status">Conectando…</span></div>
    <div class="name-prompt"><span>Tu nombre: <input id="nameInput" type="text" placeholder="Escribí tu nombre…" maxlength="40" autocomplete="off"></span><button id="refreshBtn" title="Traer los últimos cambios">↻ Actualizar</button></div>
    <div class="hint" id="hint">Cargá tu nombre para poder marcar ítems.</div>
  </div>
  {body}
</div>
<div id="toast"></div>
<div id="lb" onclick="this.style.display='none'"><img id="lbimg" src=""></div>
<script>
const BIN_ID = "{BIN_ID}";
const KEY = "{ACCESS_KEY}";
const READ = "https://api.jsonbin.io/v3/b/" + BIN_ID + "/latest";
const WRITE = "https://api.jsonbin.io/v3/b/" + BIN_ID;
const RH = {{ "X-Access-Key": KEY }};
const WH = {{ "Content-Type":"application/json", "X-Access-Key": KEY }};
const ITEM_IDS = {ids_json};
let state = {{}};      // fuente de verdad OPTIMISTA: id -> {{ done, by, at }} (se muta al instante)
let dirty = {{}};      // ids con cambios locales sin confirmar en el servidor
let flushing = false;  // hay un guardado en curso (cola single-flight)
let writeEpoch = 0;    // se incrementa con cada escritura confirmada

function getName() {{
  const el = document.getElementById("nameInput");
  const v = (el && el.value.trim()) || localStorage.getItem("escalada_name") || "";
  return v || "Anónimo";
}}

function fmtDate(s) {{
  try {{ return new Date(s).toLocaleString("es-AR", {{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}}); }}
  catch(e) {{ return ""; }}
}}

function render() {{
  let done = 0;
  ITEM_IDS.forEach(id => {{
    const m = state[id];
    const v = !!m;
    const cb = document.querySelector('input[data-id="'+id+'"]');
    const wrap = document.querySelector('.item[data-id="'+id+'"]');
    const by = document.querySelector('.by[data-for="'+id+'"]');
    if (cb) cb.checked = v;
    if (wrap) wrap.classList.toggle("done", v);
    if (by) {{
      if (v && m && typeof m === "object" && m.by) by.textContent = "✓ " + m.by + (m.at ? " · " + fmtDate(m.at) : "");
      else if (v) by.textContent = "✓ resuelto";
      else by.textContent = "";
    }}
    if (v) done++;
  }});
  const total = ITEM_IDS.length;
  document.getElementById("count").textContent = done + " / " + total + " resueltos";
  document.getElementById("barfill").style.width = (total ? (done/total*100) : 0) + "%";
}}

function nameSet() {{
  const el = document.getElementById("nameInput");
  return !!(el && el.value.trim());
}}
function updateLock() {{
  const locked = !nameSet();
  document.body.classList.toggle("locked", locked);
  document.getElementById("hint").style.display = locked ? "block" : "none";
}}
let toastTimer = null;
function toast(msg) {{
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3500);
}}

function setStatus(msg, cls) {{
  const el = document.getElementById("status");
  el.textContent = msg; el.className = "status " + (cls||"");
}}

async function pull() {{
  // no sincronizar mientras hay cambios locales sin guardar (evita pisar/flicker)
  if (flushing || Object.keys(dirty).length) return;
  const epoch = writeEpoch;
  try {{
    const r = await fetch(READ, {{ headers: RH, cache: "no-store" }});
    if (!r.ok) throw new Error(r.status);
    const data = (await r.json()).record || {{}};
    if (flushing || Object.keys(dirty).length || epoch !== writeEpoch) return; // estado cambió durante el pull
    state = (data && data.checks) || {{}};
    render();
    let extra = "";
    if (data.updatedBy && data.updatedAt) {{
      extra = " · últ.: " + data.updatedBy + " (" + new Date(data.updatedAt).toLocaleString("es-AR") + ")";
    }}
    setStatus("Sincronizado" + extra, "ok");
  }} catch(e) {{ console.error("pull error", e); setStatus("Sin conexión: " + (e.message||e), "err"); }}
}}

// cambio local: muta state AL INSTANTE (UI inmediata), marca dirty y dispara guardado
function queueChange(id, checked) {{
  if (checked) state[id] = {{ done:true, by:getName(), at:new Date().toISOString() }};
  else delete state[id];
  dirty[id] = true;
  render();   // instantáneo, lee de state
  flush();
}}

// cola single-flight: nunca corren dos escrituras a la vez; agrupa TODO lo dirty en cada vuelta.
async function flush() {{
  if (flushing) return;
  if (Object.keys(dirty).length === 0) return;
  flushing = true;
  setStatus("Guardando…");
  try {{
    while (Object.keys(dirty).length > 0) {{
      const ids = Object.keys(dirty);
      // versión por id usando la referencia actual de state (null = borrado)
      const snap = {{}};
      ids.forEach(id => snap[id] = (id in state) ? state[id] : null);
      // leer servidor para incorporar cambios de otros usuarios
      let cur = {{}};
      try {{ const r = await fetch(READ, {{headers:RH, cache:"no-store"}}); if (r.ok) cur = (await r.json()).record || {{}}; }} catch(e) {{}}
      const checks = cur.checks || {{}};
      // aplicar NUESTROS cambios encima
      ids.forEach(id => {{ if (snap[id]) checks[id] = snap[id]; else delete checks[id]; }});
      const payload = {{ v:1, title:"Depto Escalada - Observaciones", checks: checks,
        updatedAt: new Date().toISOString(), updatedBy: getName() }};
      const r = await fetch(WRITE, {{ method:"PUT", headers: WH, body: JSON.stringify(payload) }});
      if (!r.ok) throw new Error("HTTP " + r.status + " " + (await r.text()).slice(0,120));
      writeEpoch++;
      // confirmar: limpiar dirty de los ids que NO se volvieron a tocar desde el snapshot
      ids.forEach(id => {{
        const curVal = (id in state) ? state[id] : null;
        if (curVal === snap[id]) delete dirty[id];
      }});
      // incorporar cambios de otros usuarios para ids que no estamos editando
      Object.keys(checks).forEach(id => {{ if (!dirty[id]) state[id] = checks[id]; }});
      Object.keys(state).forEach(id => {{ if (!(id in checks) && !dirty[id]) delete state[id]; }});
      render();
    }}
    setStatus("Guardado", "ok");
  }} catch(e) {{
    console.error("flush error", e);
    setStatus("Error al guardar (reintentando): " + (e.message||e), "err");
    setTimeout(() => {{ flushing = false; flush(); }}, 3000); // dirty intacto => reintenta
    return;
  }}
  flushing = false;
}}

function zoom(src) {{
  document.getElementById("lbimg").src = src;
  document.getElementById("lb").style.display = "flex";
}}

document.querySelectorAll('input[type=checkbox]').forEach(cb => {{
  // bloqueo: si no hay nombre, evita el toggle y avisa
  cb.addEventListener("click", (e) => {{
    if (!nameSet()) {{
      e.preventDefault();
      toast("Cargá tu nombre arriba para poder marcar ítems.");
      document.getElementById("nameInput").focus();
    }}
  }});
  cb.addEventListener("change", () => {{
    queueChange(cb.dataset.id, cb.checked);
  }});
}});

// init name field from storage, persist y actualiza bloqueo
(function() {{
  const el = document.getElementById("nameInput");
  el.value = localStorage.getItem("escalada_name") || "";
  el.addEventListener("input", () => {{ localStorage.setItem("escalada_name", el.value.trim()); updateLock(); }});
}})();
updateLock();
pull();
// Sincronización FRUGAL (la cuota de JSONBin no se renueva): sin polling continuo.
// Solo se sincroniza al cargar, al volver a la pestaña / enfocar la ventana, o con "Actualizar".
let lastSync = Date.now();
function maybePull() {{
  if (document.visibilityState !== "visible") return;
  if (flushing || Object.keys(dirty).length) return;
  if (Date.now() - lastSync < 3000) return; // debounce: evita pulls duplicados
  lastSync = Date.now();
  pull();
}}
document.addEventListener("visibilitychange", maybePull);
window.addEventListener("focus", maybePull);
document.getElementById("refreshBtn").addEventListener("click", () => {{ lastSync = 0; maybePull(); }});
</script>
</body>
</html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html_doc)
print("Escrito:", OUT)
print("Tamaño:", round(os.path.getsize(OUT)/1024/1024, 2), "MB")
print("Items:", len(item_ids))
print("Imagenes embebidas:", len([k for k,v in _cache.items() if v]))
