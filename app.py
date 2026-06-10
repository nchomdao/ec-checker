# EC Checker — Web version for Render.com
# Upload defect PDF -> tap labels per photo -> export stamped PDF
from flask import Flask, request, send_file, jsonify, session
import fitz, io, os, base64, uuid, time

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'ec-checker-secret')

FONT_PATH = os.path.join(os.path.dirname(__file__), 'Sarabun.ttf')

# Label style — matched to DF 5.2 sample
PASS_COLOR    = (0.11, 0.98, 0.02)
FAIL_COLOR    = (1.0,  0.0,  0.0)
TEXT_COLOR    = (0.0,  0.0,  0.0)
FONT_SIZE     = 12.0
MARGIN_BOTTOM = 8.0
BOX_HEIGHT    = 15.8
PAD_X         = 6.0

# in-memory store: {session_id: {'pdf': bytes, 'ts': time}}
STORE = {}
MAX_AGE = 3600 * 4  # 4 hours

def cleanup():
    now = time.time()
    dead = [k for k, v in STORE.items() if now - v['ts'] > MAX_AGE]
    for k in dead:
        del STORE[k]

def get_big_imgs(page):
    blocks = page.get_text('dict', flags=fitz.TEXT_PRESERVE_IMAGES)['blocks']
    return sorted(
        [b for b in blocks if b.get('type') == 1
         and (b['bbox'][2] - b['bbox'][0]) > 100
         and (b['bbox'][3] - b['bbox'][1]) > 100],
        key=lambda b: (round(b['bbox'][1] / 10), b['bbox'][0])
    )

UI = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>EC Checker</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
:root{--bg:#f0ede8;--surface:#fff;--ink:#1a1a1a;--muted:#777;--border:#ddd;
--pass:#17803d;--fail:#c0392b;--accent:#1a4f8a;--pass-l:#e6f7ec;--fail-l:#fdecea;}
body{font-family:'Sarabun','Helvetica Neue',sans-serif;background:var(--bg);padding-bottom:90px;}
.hdr{background:var(--ink);color:#fff;padding:12px 16px;position:sticky;top:0;z-index:99;display:flex;justify-content:space-between;align-items:center;}
.hdr-l h1{font-size:16px;font-weight:800;}
.hdr-l p{font-size:11px;color:#aaa;margin-top:2px;max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.stats{display:flex;gap:13px;}
.stat{text-align:center;}
.stat b{display:block;font-size:21px;font-weight:900;line-height:1;}
.g{color:#4ddd7a;}.r{color:#ff6b5b;}.y{color:#bbb;}
.stat span{font-size:9px;color:#aaa;text-transform:uppercase;letter-spacing:.07em;}
.upload{margin:22px 14px;border:2.5px dashed var(--border);border-radius:14px;background:var(--surface);padding:42px 20px;text-align:center;cursor:pointer;}
.upload.drag{border-color:var(--accent);background:#eef5fd;}
.upload input{display:none;}
.upload .ico{font-size:42px;}
.upload h2{font-size:16px;font-weight:700;margin-top:8px;}
.upload p{font-size:13px;color:var(--muted);margin-top:4px;}
.prog{margin:0 14px 14px;height:6px;background:var(--border);border-radius:99px;overflow:hidden;display:none;}
.prog-fill{height:100%;background:var(--accent);transition:width .3s;width:0%;}
.toolbar{display:none;gap:8px;flex-wrap:wrap;padding:12px 12px 8px;align-items:center;}
.toolbar.on{display:flex;}
.btn{padding:9px 15px;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;transition:transform .1s;}
.btn:active{transform:scale(.95);}
.btn-pa{background:var(--pass);color:#fff;}
.btn-fa{background:var(--fail);color:#fff;}
.btn-cl{background:var(--border);color:var(--ink);}
.btn-ex{background:var(--accent);color:#fff;padding:10px 18px;font-size:14px;}
.btn-new{background:#fff;border:1.5px solid var(--border);color:var(--muted);}
.filters{display:none;gap:6px;padding:0 12px 12px;overflow-x:auto;-webkit-overflow-scrolling:touch;}
.filters.on{display:flex;}
.tab{padding:6px 14px;border-radius:99px;border:1.5px solid var(--border);background:var(--surface);font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;color:var(--muted);white-space:nowrap;flex-shrink:0;}
.tab.on{background:var(--ink);border-color:var(--ink);color:#fff;}
.pages{padding:0 10px;}
.page-block{background:var(--surface);border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.07);margin-bottom:14px;}
.page-hdr{padding:7px 12px;background:#f5f3f0;border-bottom:1px solid var(--border);font-size:11px;font-weight:700;color:var(--muted);letter-spacing:.04em;}
.img-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);}
.cell{background:var(--surface);display:flex;flex-direction:column;}
.cell.pass{outline:3px solid var(--pass);outline-offset:-2px;position:relative;z-index:1;}
.cell.fail{outline:3px solid var(--fail);outline-offset:-2px;position:relative;z-index:1;}
.cell.hidden{display:none!important;}
.img-wrap{position:relative;width:100%;padding-top:76%;overflow:hidden;background:#e8e5e0;cursor:pointer;}
.img-wrap img{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;}
.lbl{position:absolute;bottom:5%;left:50%;transform:translateX(-50%);padding:3px 10px;border-radius:5px;font-size:12px;font-weight:900;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,.4);opacity:0;transition:opacity .15s;pointer-events:none;}
.cell.pass .lbl{background:#1cdb03;color:#000;opacity:1;}
.cell.fail .lbl{background:red;color:#000;opacity:1;}
.num{position:absolute;top:5px;left:6px;background:rgba(0,0,0,.55);color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;pointer-events:none;}
.actions{display:flex;gap:4px;padding:5px 5px 6px;}
.abtn{flex:1;padding:8px 2px;border:none;border-radius:7px;font-size:11px;font-weight:800;cursor:pointer;font-family:inherit;border:1.5px solid transparent;transition:all .1s;}
.abtn:active{transform:scale(.92);}
.abtn.p{background:var(--pass-l);color:var(--pass);border-color:var(--pass);}
.abtn.f{background:var(--fail-l);color:var(--fail);border-color:var(--fail);}
.abtn.p.on{background:var(--pass);color:#fff;}
.abtn.f.on{background:var(--fail);color:#fff;}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:200;align-items:center;justify-content:center;}
.modal.on{display:flex;}
.modal-box{background:var(--surface);border-radius:16px;padding:28px 24px;width:290px;text-align:center;}
.modal-box h3{font-size:18px;margin-bottom:6px;}
.modal-box p{font-size:13px;color:var(--muted);margin-bottom:16px;}
.mbar{height:8px;background:var(--border);border-radius:99px;overflow:hidden;margin-bottom:8px;}
.mfill{height:100%;background:var(--accent);width:0%;transition:width .3s;}
.toast{position:fixed;bottom:88px;left:50%;transform:translateX(-50%) translateY(14px);background:var(--ink);color:#fff;padding:10px 20px;border-radius:99px;font-size:13px;font-weight:600;opacity:0;transition:all .3s;z-index:999;white-space:nowrap;pointer-events:none;}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0);}

/* annotation button on cell */
.ann-btn{position:absolute;top:5px;right:6px;background:rgba(255,255,255,.92);border:1.5px solid #c0392b;color:#c0392b;font-size:11px;font-weight:800;padding:3px 8px;border-radius:6px;cursor:pointer;font-family:inherit;z-index:2;}
.ann-btn.has{background:#c0392b;color:#fff;}

/* circle preview on thumbnail */
.circ-preview{position:absolute;border:2.5px solid red;border-radius:50%;pointer-events:none;}
.note-preview{position:absolute;color:red;font-size:10px;font-weight:900;text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 3px #fff;pointer-events:none;white-space:nowrap;transform:translateX(-50%);}

/* annotation editor modal */
.ann-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:300;align-items:center;justify-content:center;flex-direction:column;padding:14px;}
.ann-modal.on{display:flex;}
.ann-box{background:var(--surface);border-radius:14px;overflow:hidden;width:100%;max-width:420px;}
.ann-hdr{padding:10px 14px;background:var(--ink);color:#fff;font-size:13px;font-weight:700;display:flex;justify-content:space-between;align-items:center;}
.ann-close{background:none;border:none;color:#fff;font-size:20px;cursor:pointer;padding:0 4px;}
.ann-img-wrap{position:relative;width:100%;background:#000;touch-action:none;}
.ann-img-wrap img{width:100%;display:block;user-select:none;-webkit-user-drag:none;}
.ann-circle{position:absolute;border:3px solid red;border-radius:50%;pointer-events:none;box-shadow:0 0 0 1px rgba(255,255,255,.5);}
.ann-hint{font-size:11px;color:var(--muted);text-align:center;padding:6px;}
.ann-controls{padding:10px 14px 14px;display:flex;flex-direction:column;gap:10px;}
.ann-size{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:700;color:var(--muted);}
.ann-size input[type=range]{flex:1;}
.ann-note{width:100%;padding:10px;border:1.5px solid var(--border);border-radius:8px;font-family:inherit;font-size:14px;}
.ann-actions{display:flex;gap:8px;}
.ann-actions .btn{flex:1;}
.btn-save{background:var(--accent);color:#fff;}
.btn-del{background:#fff;border:1.5px solid var(--fail);color:var(--fail);}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-l">
    <h1>EC Checker</h1>
    <p id="fname">เลือก PDF เพื่อเริ่มตรวจ</p>
  </div>
  <div class="stats">
    <div class="stat"><b class="g" id="sP">0</b><span>ผ่าน</span></div>
    <div class="stat"><b class="r" id="sF">0</b><span>ไม่ผ่าน</span></div>
    <div class="stat"><b class="y" id="sN">0</b><span>รอ</span></div>
  </div>
</div>

<div class="upload" id="upZone" onclick="document.getElementById('pdfIn').click()">
  <input type="file" id="pdfIn" accept="application/pdf">
  <div class="ico">📄</div>
  <h2>เลือก PDF Defect Report</h2>
  <p>แตะเพื่อเลือกไฟล์จากมือถือ</p>
</div>

<div class="prog" id="prog"><div class="prog-fill" id="progFill"></div></div>

<div class="toolbar" id="toolbar">
  <button class="btn btn-pa" onclick="markAll('pass')">✅ ผ่านทั้งหมด</button>
  <button class="btn btn-fa" onclick="markAll('fail')">❌ ไม่ผ่านทั้งหมด</button>
  <button class="btn btn-cl" onclick="markAll(null)">ล้าง</button>
  <button class="btn btn-ex" onclick="doExport()">📥 Export PDF</button>
  <button class="btn btn-new" onclick="location.reload()">📄 ไฟล์ใหม่</button>
</div>

<div class="filters" id="filters">
  <button class="tab on" onclick="setFilter('all',this)">ทั้งหมด</button>
  <button class="tab" onclick="setFilter('pending',this)">⏳ รอ</button>
  <button class="tab" onclick="setFilter('pass',this)">✅ ผ่าน</button>
  <button class="tab" onclick="setFilter('fail',this)">❌ ไม่ผ่าน</button>
</div>

<div class="pages" id="pages"></div>

<div class="modal" id="modal">
  <div class="modal-box">
    <h3 id="mTitle">⏳ กำลังโหลด</h3>
    <p id="mMsg">ประมวลผล...</p>
    <div class="mbar"><div class="mfill" id="mFill"></div></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<!-- annotation editor -->
<div class="ann-modal" id="annModal">
  <div class="ann-box">
    <div class="ann-hdr">
      <span>🔴 วงแดง + คำอธิบาย</span>
      <button class="ann-close" onclick="closeAnn()">×</button>
    </div>
    <div class="ann-img-wrap" id="annWrap">
      <img id="annImg" draggable="false">
      <div class="ann-circle" id="annCircle" style="display:none"></div>
    </div>
    <div class="ann-hint">แตะบนรูปเพื่อวางวงกลม · ลากเพื่อย้าย</div>
    <div class="ann-controls">
      <div class="ann-size">
        ขนาดวง <input type="range" id="annR" min="5" max="35" value="14" oninput="drawCircle()">
      </div>
      <input type="text" class="ann-note" id="annNote" placeholder="คำอธิบาย (ไม่ใส่ก็ได้) เช่น มี defect ใหม่">
      <div class="ann-actions">
        <button class="btn btn-del" onclick="deleteAnn()">🗑 ลบวง</button>
        <button class="btn btn-save" onclick="saveAnn()">✓ บันทึก</button>
      </div>
    </div>
  </div>
</div>

<script>
let PAGES = [];
let state = {};
let annots = {};   // {"pi_ii": {cx,cy,r,note}}
let filter = 'all';
let fileName = '';
let annTarget = null; // current "pi_ii" being edited
const $ = id => document.getElementById(id);

const upZone = $('upZone');
upZone.addEventListener('dragover', e=>{e.preventDefault();upZone.classList.add('drag');});
upZone.addEventListener('dragleave', ()=>upZone.classList.remove('drag'));
upZone.addEventListener('drop', e=>{e.preventDefault();upZone.classList.remove('drag');if(e.dataTransfer.files[0])loadPDF(e.dataTransfer.files[0]);});
$('pdfIn').addEventListener('change', e=>{if(e.target.files[0])loadPDF(e.target.files[0]);});

async function loadPDF(file){
  fileName = file.name;
  $('fname').textContent = file.name;
  upZone.style.display = 'none';
  $('prog').style.display = 'block';
  $('progFill').style.width = '15%';

  const fd = new FormData();
  fd.append('pdf', file);

  try {
    const res = await fetch('parse', {method:'POST', body:fd});
    $('progFill').style.width = '70%';
    if(!res.ok) throw new Error('server error ' + res.status);
    const data = await res.json();
    PAGES = data.pages;
    state = {};
    PAGES.forEach((pg,pi)=>{state[pi]={};pg.images.forEach((_,ii)=>state[pi][ii]=null);});
    $('progFill').style.width = '100%';
    setTimeout(()=>{$('prog').style.display='none';},300);
    build();
    $('toolbar').classList.add('on');
    $('filters').classList.add('on');
    updateStats();
    const total = PAGES.reduce((a,p)=>a+p.images.length,0);
    $('fname').textContent = `${file.name} · ${total} รูป`;
    toast(`โหลดสำเร็จ ${total} รูป`);
  } catch(e) {
    toast('❌ โหลดไม่สำเร็จ: '+e.message);
    $('prog').style.display='none';
    upZone.style.display='';
  }
}

function build(){
  const wrap = $('pages');
  wrap.innerHTML = '';
  PAGES.forEach((pg,pi)=>{
    const block = document.createElement('div');
    block.className = 'page-block';
    block.id = 'pg'+pi;
    let g = '<div class="img-grid">';
    pg.images.forEach((img,ii)=>{
      g += `<div class="cell" id="c${pi}_${ii}">
        <div class="img-wrap" onclick="tap(${pi},${ii})">
          <img src="data:image/jpeg;base64,${img.b64}" loading="lazy">
          <div class="num">รูปที่ ${img.num}</div>
          <div class="lbl"></div>
          <button class="ann-btn" onclick="openAnn(${pi},${ii},event)">🔴</button>
          <div class="circ-preview" style="display:none"></div>
          <div class="note-preview" style="display:none"></div>
        </div>
        <div class="actions">
          <button class="abtn p" onclick="mark(${pi},${ii},'pass',event)">✅ แก้ไขเรียบร้อย</button>
          <button class="abtn f" onclick="mark(${pi},${ii},'fail',event)">❌ ยังไม่เรียบร้อย</button>
        </div>
      </div>`;
    });
    g += '</div>';
    block.innerHTML = `<div class="page-hdr">หน้า ${pg.pageNum}</div>${g}`;
    wrap.appendChild(block);
  });
}

function tap(pi,ii){
  const cur = state[pi][ii];
  mark(pi,ii,cur===null?'pass':cur==='pass'?'fail':null,null);
}

function mark(pi,ii,s,e){
  if(e)e.stopPropagation();
  if(state[pi][ii]===s)s=null;
  state[pi][ii]=s;
  refresh(pi,ii);
  updateStats();
  applyFilter();
}

function refresh(pi,ii){
  const cell = $(`c${pi}_${ii}`);
  if(!cell)return;
  const s = state[pi][ii];
  const hid = cell.classList.contains('hidden');
  cell.className = 'cell'+(s?' '+s:'')+(hid?' hidden':'');
  cell.querySelector('.lbl').textContent = s==='pass'?'แก้ไขเรียบร้อย':s==='fail'?'แก้ไขยังไม่เรียบร้อย':'';
  cell.querySelector('.abtn.p').classList.toggle('on',s==='pass');
  cell.querySelector('.abtn.f').classList.toggle('on',s==='fail');
  // annotation preview
  const key = `${pi}_${ii}`;
  const ann = annots[key];
  const annBtn = cell.querySelector('.ann-btn');
  const circ = cell.querySelector('.circ-preview');
  const notePrev = cell.querySelector('.note-preview');
  annBtn.classList.toggle('has', !!ann);
  if(ann){
    const wrap = cell.querySelector('.img-wrap');
    const W = wrap.clientWidth, H = wrap.clientHeight;
    const r = ann.r * W;
    circ.style.display = '';
    circ.style.left   = (ann.cx*W - r)+'px';
    circ.style.top    = (ann.cy*H - r)+'px';
    circ.style.width  = (r*2)+'px';
    circ.style.height = (r*2)+'px';
    if(ann.note){
      notePrev.style.display = '';
      notePrev.textContent = ann.note;
      notePrev.style.left = (ann.cx*W)+'px';
      notePrev.style.top  = Math.max(2, ann.cy*H - r - 14)+'px';
    } else notePrev.style.display = 'none';
  } else {
    circ.style.display = 'none';
    notePrev.style.display = 'none';
  }
}

// ── annotation editor ──
let annDrag = false;

function openAnn(pi, ii, e){
  if(e) e.stopPropagation();
  annTarget = `${pi}_${ii}`;
  const img = PAGES[pi].images[ii];
  $('annImg').src = 'data:image/jpeg;base64,' + img.b64;
  const ann = annots[annTarget];
  if(ann){
    $('annR').value = Math.round(ann.r * 100);
    $('annNote').value = ann.note || '';
    setTimeout(drawCircle, 100);
  } else {
    $('annR').value = 14;
    $('annNote').value = '';
    $('annCircle').style.display = 'none';
    annots[annTarget] = null; // placeholder until tapped
  }
  $('annModal').classList.add('on');
}

function annPos(ev){
  const wrap = $('annWrap');
  const rect = wrap.getBoundingClientRect();
  const t = ev.touches ? ev.touches[0] : ev;
  let x = (t.clientX - rect.left) / rect.width;
  let y = (t.clientY - rect.top) / rect.height;
  return [Math.max(0,Math.min(1,x)), Math.max(0,Math.min(1,y))];
}

function placeCircle(ev){
  ev.preventDefault();
  const [cx, cy] = annPos(ev);
  if(!annots[annTarget]) annots[annTarget] = {cx, cy, r: $('annR').value/100, note: $('annNote').value};
  else { annots[annTarget].cx = cx; annots[annTarget].cy = cy; }
  drawCircle();
}

function drawCircle(){
  const ann = annots[annTarget];
  if(!ann) return;
  ann.r = $('annR').value / 100;
  const wrap = $('annWrap');
  const W = wrap.clientWidth, H = wrap.clientHeight;
  const r = ann.r * W;
  const c = $('annCircle');
  c.style.display = '';
  c.style.left   = (ann.cx*W - r)+'px';
  c.style.top    = (ann.cy*H - r)+'px';
  c.style.width  = (r*2)+'px';
  c.style.height = (r*2)+'px';
}

$('annWrap').addEventListener('mousedown', e=>{ annDrag=true; placeCircle(e); });
$('annWrap').addEventListener('mousemove', e=>{ if(annDrag) placeCircle(e); });
window.addEventListener('mouseup', ()=>annDrag=false);
$('annWrap').addEventListener('touchstart', e=>{ annDrag=true; placeCircle(e); }, {passive:false});
$('annWrap').addEventListener('touchmove', e=>{ if(annDrag) placeCircle(e); }, {passive:false});
window.addEventListener('touchend', ()=>annDrag=false);

function saveAnn(){
  const ann = annots[annTarget];
  if(!ann){ closeAnn(); return; }
  ann.note = $('annNote').value.trim();
  const [pi, ii] = annTarget.split('_').map(Number);
  closeAnn();
  refresh(pi, ii);
  toast('🔴 บันทึกวงแดงแล้ว');
}

function deleteAnn(){
  const [pi, ii] = annTarget.split('_').map(Number);
  delete annots[annTarget];
  closeAnn();
  refresh(pi, ii);
  toast('ลบวงแดงแล้ว');
}

function closeAnn(){
  if(annots[annTarget] === null) delete annots[annTarget];
  $('annModal').classList.remove('on');
  annTarget = null;
}

function markAll(s){
  PAGES.forEach((_,pi)=>Object.keys(state[pi]).forEach(ii=>{state[pi][ii]=s;refresh(pi,+ii);}));
  updateStats();applyFilter();
  toast(s==='pass'?'✅ ผ่านทั้งหมด':s==='fail'?'❌ ไม่ผ่านทั้งหมด':'ล้างทั้งหมด');
}

function setFilter(f,btn){
  filter=f;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  btn.classList.add('on');
  applyFilter();
}

function applyFilter(){
  PAGES.forEach((pg,pi)=>{
    let any=false;
    pg.images.forEach((_,ii)=>{
      const s=state[pi][ii];
      const show=filter==='all'||(filter==='pending'&&s===null)||filter===s;
      const cell=$(`c${pi}_${ii}`);
      if(cell){cell.classList.toggle('hidden',!show);if(show)any=true;}
    });
    const blk=$('pg'+pi);
    if(blk)blk.style.display=any?'':'none';
  });
}

function updateStats(){
  let p=0,f=0,n=0;
  PAGES.forEach((_,pi)=>Object.values(state[pi]).forEach(s=>{if(s==='pass')p++;else if(s==='fail')f++;else n++;}));
  $('sP').textContent=p;$('sF').textContent=f;$('sN').textContent=n;
}

async function doExport(){
  $('modal').classList.add('on');
  $('mTitle').textContent='📥 กำลัง Export';
  $('mMsg').textContent='ประทับ label ลง PDF...';
  $('mFill').style.width='25%';
  try{
    const cleanAnnots = {};
    Object.entries(annots).forEach(([k,v])=>{ if(v) cleanAnnots[k]=v; });
    const res = await fetch('stamp', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({state, annots: cleanAnnots})
    });
    $('mFill').style.width='85%';
    if(!res.ok) throw new Error('server error '+res.status);
    const blob = await res.blob();
    $('mFill').style.width='100%';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const base = fileName.replace(/\.pdf$/i,'');
    a.href=url; a.download=base+'_EC.pdf'; a.click();
    setTimeout(()=>{$('modal').classList.remove('on');$('mFill').style.width='0%';},400);
    toast('✅ ดาวน์โหลดสำเร็จ!');
  }catch(e){
    $('modal').classList.remove('on');
    toast('❌ Export ไม่สำเร็จ: '+e.message);
  }
}

function toast(msg){
  const t=$('toast');
  t.textContent=msg;
  t.classList.add('on');
  clearTimeout(t._t);
  t._t=setTimeout(()=>t.classList.remove('on'),3000);
}
</script>
</body>
</html>"""

@app.route('/')
def index():
    return UI

@app.route('/parse', methods=['POST'])
def parse():
    cleanup()
    f = request.files.get('pdf')
    if not f:
        return jsonify({'error': 'no file'}), 400

    pdf_bytes = f.read()
    if len(pdf_bytes) > 60 * 1024 * 1024:
        return jsonify({'error': 'file too large'}), 400

    sid = session.get('sid') or str(uuid.uuid4())
    session['sid'] = sid
    STORE[sid] = {'pdf': pdf_bytes, 'ts': time.time()}

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    scale = 2.0
    pages_out = []
    img_num = 1

    for pi in range(len(doc)):
        page = doc[pi]
        big_imgs = get_big_imgs(page)
        if not big_imgs:
            pages_out.append({'pageNum': pi + 1, 'images': []})
            continue

        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)

        images = []
        for b in big_imgs:
            x0, y0, x1, y1 = b['bbox']
            clip = fitz.Rect(x0, y0, x1, y1)
            crop_pix = page.get_pixmap(matrix=mat, clip=clip)
            img_bytes = crop_pix.tobytes('jpeg', jpg_quality=75)
            b64 = base64.b64encode(img_bytes).decode()
            images.append({'b64': b64, 'num': img_num})
            img_num += 1

        pages_out.append({'pageNum': pi + 1, 'images': images})

    doc.close()
    return jsonify({'pages': pages_out})

@app.route('/stamp', methods=['POST'])
def stamp():
    sid = session.get('sid')
    if not sid or sid not in STORE:
        return 'session expired — โหลด PDF ใหม่', 400

    data = request.json
    state = data['state']

    doc = fitz.open(stream=STORE[sid]['pdf'], filetype='pdf')
    font = fitz.Font(fontfile=FONT_PATH)

    annots = data.get('annots', {})  # {"pi_ii": {"cx":0-1,"cy":0-1,"r":0-1,"note":"..."}}

    for pi_str, img_states in state.items():
        pi = int(pi_str)
        if pi >= len(doc):
            continue
        page = doc[pi]
        big_imgs = get_big_imgs(page)

        for ii_str, status in img_states.items():
            ii = int(ii_str)
            if ii >= len(big_imgs):
                continue

            x0, y0, x1, y1 = big_imgs[ii]['bbox']
            img_w = x1 - x0
            img_h = y1 - y0
            img_cx = (x0 + x1) / 2

            # ── status label ──
            if status:
                label = "แก้ไขเรียบร้อย" if status == 'pass' else "แก้ไขยังไม่เรียบร้อย"
                text_w = font.text_length(label, fontsize=FONT_SIZE)
                box_w = text_w + PAD_X * 2
                bx0 = img_cx - box_w / 2
                bx1 = bx0 + box_w
                by1 = y1 - MARGIN_BOTTOM
                by0 = by1 - BOX_HEIGHT
                color = PASS_COLOR if status == 'pass' else FAIL_COLOR

                page.draw_rect(fitz.Rect(bx0, by0, bx1, by1), color=(0, 0, 0), fill=color, width=0.8)
                tw = fitz.TextWriter(page.rect)
                tw.append((bx0 + PAD_X, by0 + BOX_HEIGHT - PAD_X + 1), label, font=font, fontsize=FONT_SIZE)
                tw.write_text(page, color=TEXT_COLOR)

            # ── red circle + note annotation ──
            ann = annots.get(f"{pi}_{ii}")
            if ann:
                cx = x0 + float(ann['cx']) * img_w
                cy = y0 + float(ann['cy']) * img_h
                r  = max(6.0, float(ann.get('r', 0.12)) * img_w)
                # red circle outline
                page.draw_circle((cx, cy), r, color=(1, 0, 0), width=2.0)

                note = (ann.get('note') or '').strip()
                if note:
                    note_size = 11.0
                    note_w = font.text_length(note, fontsize=note_size)
                    # place note above circle; clamp inside image bounds
                    nx = cx - note_w / 2
                    nx = max(x0 + 2, min(nx, x1 - note_w - 2))
                    ny = cy - r - 5
                    if ny - note_size < y0 + 2:  # too high -> below circle
                        ny = cy + r + note_size + 3
                    # white halo for readability
                    tw2 = fitz.TextWriter(page.rect)
                    tw2.append((nx, ny), note, font=font, fontsize=note_size)
                    for dx, dy in [(-0.7,0),(0.7,0),(0,-0.7),(0,0.7)]:
                        twh = fitz.TextWriter(page.rect)
                        twh.append((nx+dx, ny+dy), note, font=font, fontsize=note_size)
                        twh.write_text(page, color=(1, 1, 1))
                    tw2.write_text(page, color=(1, 0, 0))

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name='defect_EC.pdf')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port)
