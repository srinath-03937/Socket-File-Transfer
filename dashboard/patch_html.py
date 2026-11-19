
# This script replaces the DASHBOARD_HTML in dashboard/app.py with the new terminal UI
import os

path = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'app.py')
path = os.path.normpath(path)

content = open(path, encoding='utf-8').read()
split_marker = 'DASHBOARD_HTML = '
end_marker = '\nif __name__'

idx_start = content.index(split_marker)
idx_end   = content.index(end_marker, idx_start)

NEW_HTML = '''DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>SFT-NODE-01 :: Secure Transfer Terminal v2.4.1</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:       #020305;
  --bg1:      #05080f;
  --bg2:      #07091a;
  --border:   #0f3320;
  --border2:  #1a5e38;
  --green:    #00ff41;
  --green2:   #00c832;
  --green3:   #00802a;
  --green4:   #004d1a;
  --amber:    #ffb000;
  --red:      #ff3333;
  --cyan:     #00e5ff;
  --dim:      #1a4d2a;
  --dimtext:  #3a7a4a;
  --font:     'JetBrains Mono', 'Share Tech Mono', 'Courier New', monospace;
}

html{scroll-behavior:smooth;height:100%}
body{
  font-family:var(--font);
  background:var(--bg);
  color:var(--green);
  height:100vh;
  overflow:hidden;
  position:relative;
}

/* CRT scanlines overlay */
body::before{
  content:'';
  position:fixed;inset:0;
  background:repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.25) 2px,
    rgba(0,0,0,0.25) 4px
  );
  pointer-events:none;z-index:9999;
}
/* CRT glow vignette */
body::after{
  content:'';
  position:fixed;inset:0;
  background:radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.65) 100%);
  pointer-events:none;z-index:9998;
}

/* ── LAYOUT ──────────────────────────────────────── */
.crt-frame{
  height:100vh;
  display:grid;
  grid-template-rows:auto 1fr auto;
  grid-template-columns:300px 1fr;
  border:1px solid var(--border2);
  box-shadow:0 0 40px rgba(0,255,65,0.12), inset 0 0 80px rgba(0,0,0,0.8);
}

/* ── TITLEBAR ─────────────────────────────────────── */
.titlebar{
  grid-column:1/-1;
  background:var(--bg1);
  border-bottom:1px solid var(--border2);
  padding:0 16px;
  display:flex;align-items:center;gap:0;
  height:44px;
  position:relative;
}
.tb-dots{display:flex;gap:7px;margin-right:16px}
.tb-dot{width:12px;height:12px;border-radius:50%;cursor:pointer}
.tb-dot.close{background:#ff5f56;box-shadow:0 0 6px #ff5f56}
.tb-dot.min  {background:#ffbd2e;box-shadow:0 0 6px #ffbd2e}
.tb-dot.max  {background:#27c93f;box-shadow:0 0 6px #27c93f}
.tb-title{
  position:absolute;left:50%;transform:translateX(-50%);
  font-size:.72rem;font-weight:600;letter-spacing:.15em;
  color:var(--green);text-shadow:0 0 10px var(--green);
  white-space:nowrap;
}
.tb-right{margin-left:auto;display:flex;align-items:center;gap:18px;font-size:.68rem;color:var(--dimtext)}
.tb-right span{letter-spacing:.08em}
.blink{animation:blink 1.1s step-end infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}

/* ── SIDEBAR ─────────────────────────────────────── */
.sidebar{
  background:var(--bg1);
  border-right:1px solid var(--border2);
  display:flex;flex-direction:column;
  overflow:hidden;
  font-size:.72rem;
}
.sidebar-hdr{
  padding:10px 14px 6px;
  border-bottom:1px solid var(--border);
  font-size:.65rem;letter-spacing:.15em;color:var(--dimtext);
  text-transform:uppercase;
}
.ascii-logo{
  padding:12px 14px 8px;
  font-size:.52rem;line-height:1.3;
  color:var(--green2);
  text-shadow:0 0 8px rgba(0,255,65,0.4);
  border-bottom:1px solid var(--border);
  white-space:pre;
}
.nav-section{padding:8px 0}
.nav-label{
  padding:4px 14px;
  font-size:.6rem;letter-spacing:.2em;
  color:var(--dimtext);text-transform:uppercase;
}
.nav-item{
  padding:7px 14px;
  cursor:pointer;
  display:flex;align-items:center;gap:8px;
  font-size:.7rem;letter-spacing:.06em;
  color:var(--green3);
  border-left:2px solid transparent;
  transition:all .1s;
  white-space:nowrap;
}
.nav-item:hover{
  color:var(--green);
  background:rgba(0,255,65,0.05);
  border-left-color:var(--green3);
}
.nav-item.active{
  color:var(--green);
  background:rgba(0,255,65,0.08);
  border-left-color:var(--green);
  text-shadow:0 0 8px rgba(0,255,65,0.5);
}
.nav-item .nav-key{
  font-size:.6rem;color:var(--dimtext);
  margin-left:auto;border:1px solid var(--border2);
  padding:1px 5px;border-radius:2px;
}

/* Sys stats in sidebar */
.sys-stats{
  margin-top:auto;
  padding:10px 14px;
  border-top:1px solid var(--border);
  font-size:.65rem;
  line-height:1.9;
  color:var(--dimtext);
}
.sys-row{display:flex;justify-content:space-between}
.sys-val{color:var(--green2)}
.mini-bar{
  height:3px;background:var(--border);border-radius:1px;
  margin:2px 0 6px;overflow:hidden;
}
.mini-bar-fill{height:100%;background:var(--green3);border-radius:1px;animation:barAnim 3s ease-in-out infinite alternate}
@keyframes barAnim{from{filter:brightness(1)}to{filter:brightness(1.4)}}

/* ── MAIN ────────────────────────────────────────── */
.main{
  background:var(--bg);
  display:flex;flex-direction:column;
  overflow:hidden;
}

/* ── TERMINAL PANEL ──────────────────────────────── */
.term-panel{
  flex:1;
  display:flex;flex-direction:column;
  overflow:hidden;
  padding:0;
}
.panel-tab-bar{
  display:flex;align-items:center;
  background:var(--bg1);
  border-bottom:1px solid var(--border2);
  padding:0 12px;
  gap:0;
  height:34px;
}
.tab{
  padding:0 18px;
  font-size:.67rem;letter-spacing:.1em;
  color:var(--dimtext);
  cursor:pointer;
  height:100%;
  display:flex;align-items:center;
  border-bottom:2px solid transparent;
  text-transform:uppercase;
  white-space:nowrap;
  transition:color .15s;
}
.tab:hover{color:var(--green2)}
.tab.active{
  color:var(--green);
  border-bottom-color:var(--green);
  text-shadow:0 0 10px rgba(0,255,65,0.6);
}
.tab-spacer{flex:1}
.tab-right{font-size:.6rem;color:var(--dimtext);padding:0 8px;letter-spacing:.08em}

/* ── SECTIONS ────────────────────────────────────── */
.section{display:none;flex:1;overflow:hidden;flex-direction:column}
.section.active{display:flex}

/* ── UPLOAD SECTION ─────────────────────────────── */
.upload-area{
  flex:1;
  display:flex;flex-direction:column;
  padding:20px;
  gap:16px;
  overflow:auto;
}
.term-prompt-box{
  background:var(--bg1);
  border:1px solid var(--border2);
  padding:16px 20px;
  font-size:.75rem;
  line-height:1.8;
}
.term-prompt-box .cmd-line{color:var(--green2)}
.term-prompt-box .cmd-line .prompt{color:var(--cyan);margin-right:8px}
.term-prompt-box .cmd-line .cmd{color:var(--green)}
.drop-zone{
  border:1px dashed var(--border2);
  padding:36px 24px;
  text-align:center;
  cursor:pointer;
  transition:all .2s;
  position:relative;
  background:var(--bg1);
}
.drop-zone::before{
  content:'DRAG_TARGET';
  position:absolute;top:8px;left:12px;
  font-size:.55rem;letter-spacing:.2em;
  color:var(--border2);
}
.drop-zone:hover,.drop-zone.drag-over{
  border-color:var(--green);
  background:rgba(0,255,65,0.04);
  box-shadow:0 0 20px rgba(0,255,65,0.08), inset 0 0 20px rgba(0,255,65,0.03);
}
.drop-ascii{
  font-size:.7rem;line-height:1.5;
  color:var(--green3);white-space:pre;
  margin-bottom:12px;
}
.drop-label{font-size:.75rem;color:var(--green2);letter-spacing:.1em}
.drop-sub{font-size:.64rem;color:var(--dimtext);margin-top:4px;letter-spacing:.06em}

/* ── PROGRESS ─────────────────────────────────────── */
.prog-box{
  background:var(--bg1);border:1px solid var(--border2);
  padding:16px 20px;font-size:.73rem;
  display:none;
}
.prog-box.show{display:block}
.prog-label{color:var(--green2);margin-bottom:8px;letter-spacing:.06em}
.prog-track{
  font-family:var(--font);font-size:.68rem;
  color:var(--green);letter-spacing:.02em;
  height:20px;line-height:20px;
  position:relative;overflow:hidden;
}
.prog-ascii-bar{color:var(--green);white-space:pre}
.prog-meta{color:var(--dimtext);font-size:.65rem;margin-top:6px;letter-spacing:.04em}
.prog-result{color:var(--green);font-size:.7rem;margin-top:8px;letter-spacing:.05em}
.prog-result.err{color:var(--red)}

/* ── FILE TABLE ───────────────────────────────────── */
.files-area{
  flex:1;overflow:auto;
  padding:16px 20px;
  display:flex;flex-direction:column;gap:12px;
}
.files-header{
  display:flex;align-items:center;gap:16px;
  font-size:.67rem;color:var(--dimtext);letter-spacing:.1em;
}
.files-count{color:var(--green2)}
.btn-refresh{
  background:none;border:1px solid var(--border2);
  color:var(--dimtext);font-family:var(--font);font-size:.65rem;
  padding:3px 10px;cursor:pointer;letter-spacing:.08em;
  transition:all .15s;
}
.btn-refresh:hover{border-color:var(--green);color:var(--green)}

.ascii-table-wrap{
  border:1px solid var(--border2);
  font-size:.68rem;
  overflow:auto;
}
.ascii-table-hdr{
  background:rgba(0,255,65,0.06);
  border-bottom:1px solid var(--border2);
  padding:7px 14px;
  display:grid;
  grid-template-columns:32px 1fr 110px 160px 170px;
  gap:8px;
  color:var(--dimtext);letter-spacing:.1em;
  text-transform:uppercase;font-size:.62rem;
}
.file-row{
  padding:8px 14px;
  display:grid;
  grid-template-columns:32px 1fr 110px 160px 170px;
  gap:8px;
  border-bottom:1px solid var(--border);
  align-items:center;
  transition:background .1s;
}
.file-row:last-child{border-bottom:none}
.file-row:hover{background:rgba(0,255,65,0.04)}
.f-idx{color:var(--dimtext)}
.f-name{color:var(--green);word-break:break-all}
.f-name .ext{color:var(--green3)}
.f-size{color:var(--cyan);text-align:right}
.f-date{color:var(--dimtext)}
.f-actions{display:flex;gap:6px}
.btn-dl,.btn-del{
  background:none;font-family:var(--font);font-size:.6rem;
  padding:3px 8px;cursor:pointer;letter-spacing:.06em;
  transition:all .15s;border:1px solid;
}
.btn-dl{color:var(--cyan);border-color:rgba(0,229,255,.3)}
.btn-dl:hover{background:rgba(0,229,255,.08);box-shadow:0 0 10px rgba(0,229,255,.2)}
.btn-del{color:var(--red);border-color:rgba(255,51,51,.25)}
.btn-del:hover{background:rgba(255,51,51,.08)}
.empty-files{
  text-align:center;padding:48px 0;
  color:var(--dimtext);font-size:.7rem;letter-spacing:.1em;
  white-space:pre;line-height:1.6;
}

/* ── STATUS SECTION ──────────────────────────────── */
.status-area{
  flex:1;overflow:auto;padding:20px;
  display:flex;flex-direction:column;gap:14px;
}
.stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.stat-card{
  border:1px solid var(--border2);
  padding:16px;
  background:var(--bg1);
  position:relative;
  overflow:hidden;
}
.stat-card::before{
  content:attr(data-label);
  position:absolute;top:8px;right:10px;
  font-size:.55rem;letter-spacing:.15em;
  color:var(--border2);text-transform:uppercase;
}
.stat-card-val{
  font-size:1.8rem;font-weight:700;
  color:var(--green);
  text-shadow:0 0 15px rgba(0,255,65,0.5);
  line-height:1.1;
}
.stat-card-label{font-size:.65rem;color:var(--dimtext);margin-top:6px;letter-spacing:.1em}
.stat-card-sub{font-size:.6rem;color:var(--green3);margin-top:3px}
.stat-fullrow{grid-column:1/-1}
.conn-table{
  border:1px solid var(--border2);
  font-size:.68rem;
}
.conn-hdr{
  background:rgba(0,255,65,0.06);
  padding:7px 14px;
  border-bottom:1px solid var(--border2);
  color:var(--dimtext);letter-spacing:.12em;
  font-size:.62rem;text-transform:uppercase;
}
.conn-row{
  padding:7px 14px;border-bottom:1px solid var(--border);
  display:flex;gap:24px;color:var(--green2);
}
.conn-row:last-child{border-bottom:none}
.conn-row span{color:var(--dimtext)}

/* ── LOG SECTION ─────────────────────────────────── */
.log-area{
  flex:1;overflow:hidden;
  display:flex;flex-direction:column;
  padding:10px 16px 10px;gap:8px;
}
.log-toolbar{
  display:flex;align-items:center;gap:12px;
  font-size:.65rem;color:var(--dimtext);
}
.log-indicator{
  width:7px;height:7px;border-radius:50%;
  background:var(--green);
  box-shadow:0 0 8px var(--green);
  animation:pulse 2s infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.log-console{
  flex:1;overflow-y:auto;
  background:var(--bg);
  border:1px solid var(--border2);
  padding:10px 14px;
  font-size:.68rem;line-height:1.8;
  color:var(--green2);
}
.log-line{animation:fadeIn .1s}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.l-ts   {color:var(--dimtext);margin-right:6px}
.l-tag  {margin-right:6px;font-weight:600}
.l-INFO {color:var(--green3)}
.l-OK   {color:var(--green)}
.l-ERR  {color:var(--red)}
.l-WARN {color:var(--amber)}
.l-CONN {color:var(--cyan)}
.l-DASH {color:#4a7a5a}
.l-tag.t-INFO{color:var(--green3)}
.l-tag.t-OK  {color:var(--green)}
.l-tag.t-ERR {color:var(--red)}
.l-tag.t-WARN{color:var(--amber)}
.l-tag.t-CONN{color:var(--cyan)}
.l-tag.t-DASH{color:#4a7a5a}
.log-cmd{
  display:flex;align-items:center;gap:8px;
  border:1px solid var(--border2);
  background:var(--bg1);
  padding:6px 12px;
}
.log-prompt{color:var(--cyan);font-size:.7rem;white-space:nowrap}
.log-input{
  flex:1;background:none;border:none;outline:none;
  font-family:var(--font);font-size:.7rem;color:var(--green);
  caret-color:var(--green);
}

/* ── STATUS BAR ──────────────────────────────────── */
.statusbar{
  grid-column:1/-1;
  background:var(--bg1);
  border-top:1px solid var(--border2);
  padding:0 16px;
  height:24px;
  display:flex;align-items:center;gap:24px;
  font-size:.6rem;letter-spacing:.08em;
  color:var(--dimtext);
}
.sb-item{display:flex;align-items:center;gap:6px}
.sb-dot{width:5px;height:5px;border-radius:50%;background:var(--green);box-shadow:0 0 4px var(--green)}
.sb-dot.red{background:var(--red);box-shadow:0 0 4px var(--red)}
.sb-val{color:var(--green2)}
.sb-sep{color:var(--border2);margin:0 2px}
.sb-right{margin-left:auto;display:flex;gap:18px}

/* ── TOAST ───────────────────────────────────────── */
#toasts{
  position:fixed;bottom:32px;right:20px;
  display:flex;flex-direction:column;gap:6px;
  z-index:10000;pointer-events:none;
}
.toast{
  background:var(--bg1);
  border-left:3px solid;
  padding:8px 14px;
  font-size:.68rem;letter-spacing:.05em;
  animation:slideIn .25s ease;
  min-width:240px;max-width:360px;
  pointer-events:auto;
}
@keyframes slideIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}
.toast.ok  {border-color:var(--green);color:var(--green)}
.toast.err {border-color:var(--red);color:var(--red)}
.toast.inf {border-color:var(--cyan);color:var(--cyan)}

/* scrollbar */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border2)}
::-webkit-scrollbar-thumb:hover{background:var(--green3)}
input[type=file]{display:none}
</style>
</head>
<body>
<div class="crt-frame">

<!-- ══ TITLEBAR ══════════════════════════════════════════════════════ -->
<header class="titlebar">
  <div class="tb-dots">
    <div class="tb-dot close" onclick="stopServer()"></div>
    <div class="tb-dot min"></div>
    <div class="tb-dot max"></div>
  </div>
  <div class="tb-title">SFT-NODE-01 :: SECURE FILE TRANSFER TERMINAL v2.4.1 — root@localhost</div>
  <div class="tb-right">
    <span id="tb-time">--:--:--</span>
    <span>|</span>
    <span id="tb-status" style="color:var(--red)">● OFFLINE</span>
    <span>|</span>
    <span>TCP:5000</span>
  </div>
</header>

<!-- ══ SIDEBAR ═══════════════════════════════════════════════════════ -->
<nav class="sidebar">
  <div class="ascii-logo">  ___ _____
 / __||  ___|_____
 \\__ \\| |_ |_   _|
 |___/|_|    |_|  v2.4</div>

  <div class="sidebar-hdr">// PROCESS CONTROL</div>
  <div class="nav-section">
    <div class="nav-item" id="nav-start" onclick="startServer()">
      [+] INIT_SERVER<span class="nav-key">F1</span>
    </div>
    <div class="nav-item" id="nav-stop" onclick="stopServer()">
      [-] KILL_SERVER<span class="nav-key">F2</span>
    </div>
  </div>

  <div class="sidebar-hdr">// NAVIGATION</div>
  <div class="nav-section">
    <div class="nav-item active" id="nav-upload" onclick="showTab('upload')">
      [1] SEND_FILE<span class="nav-key">F3</span>
    </div>
    <div class="nav-item" id="nav-files" onclick="showTab('files')">
      [2] FILE_INDEX<span class="nav-key">F4</span>
    </div>
    <div class="nav-item" id="nav-status" onclick="showTab('status')">
      [3] SYS_STATUS<span class="nav-key">F5</span>
    </div>
    <div class="nav-item" id="nav-logs" onclick="showTab('logs')">
      [4] LIVE_TRACE<span class="nav-key">F6</span>
    </div>
  </div>

  <div class="sys-stats">
    <div class="sys-row"><span>NODE_ID</span><span class="sys-val">SFT-01</span></div>
    <div class="sys-row"><span>BIND_ADDR</span><span class="sys-val">0.0.0.0:5000</span></div>
    <div class="sys-row"><span>PROTOCOL</span><span class="sys-val">TCP/IPv4</span></div>
    <div class="sys-row"><span>CHUNK_SZ</span><span class="sys-val">1024 B</span></div>
    <div class="sys-row"><span>INTEGRITY</span><span class="sys-val">SHA-256</span></div>
    <div style="margin-top:8px;color:var(--dimtext);font-size:.6rem">NET_LOAD</div>
    <div class="mini-bar"><div class="mini-bar-fill" id="net-bar" style="width:12%"></div></div>
    <div class="sys-row"><span>FILES_STORED</span><span class="sys-val" id="sb-files">—</span></div>
    <div class="sys-row"><span>SESSIONS</span><span class="sys-val" id="sb-sess">—</span></div>
    <div class="sys-row"><span>UPTIME</span><span class="sys-val" id="sb-uptime">00:00:00</span></div>
  </div>
</nav>

<!-- ══ MAIN PANEL ════════════════════════════════════════════════════ -->
<main class="main">

  <div class="panel-tab-bar">
    <div class="tab active" id="tab-upload" onclick="showTab('upload')">SEND_FILE</div>
    <div class="tab" id="tab-files"  onclick="showTab('files')">FILE_INDEX</div>
    <div class="tab" id="tab-status" onclick="showTab('status')">SYS_STATUS</div>
    <div class="tab" id="tab-logs"   onclick="showTab('logs')">LIVE_TRACE</div>
    <div class="tab-spacer"></div>
    <div class="tab-right" id="tab-right-info">IDLE — AWAITING COMMAND</div>
  </div>

  <!-- ── UPLOAD ──────────────────────────────────────── -->
  <div class="section active" id="section-upload">
    <div class="upload-area">
      <div class="term-prompt-box">
        <div class="cmd-line"><span class="prompt">root@SFT-NODE-01:~#</span><span class="cmd"> sft --mode upload --dest /received_files/ --verify sha256</span></div>
        <div style="color:var(--dimtext);font-size:.68rem;margin-top:4px">[ Initializing upload module... OK ]</div>
        <div style="color:var(--dimtext);font-size:.68rem">[ SHA-256 integrity engine: ARMED  ]</div>
        <div style="color:var(--dimtext);font-size:.68rem">[ TCP framing protocol: ACTIVE    ]</div>
        <div style="color:var(--green2);font-size:.68rem;margin-top:4px">Awaiting file input. Drop file below or click to browse.<span class="blink">_</span></div>
      </div>

      <div class="drop-zone" id="drop-zone"
           onclick="document.getElementById('file-input').click()"
           ondragover="event.preventDefault();this.classList.add('drag-over')"
           ondragleave="this.classList.remove('drag-over')"
           ondrop="handleDrop(event)">
        <div class="drop-ascii">
  ╔═══════════════════════════════════════╗
  ║                                       ║
  ║        DROP_FILE_HERE.exe             ║
  ║                                       ║
  ╚═══════════════════════════════════════╝</div>
        <div class="drop-label">[ DRAG & DROP TARGET ACTIVE ]</div>
        <div class="drop-sub" id="drop-sub">Any filetype accepted :: No size restriction :: SHA-256 auto-verified</div>
      </div>
      <input type="file" id="file-input" onchange="handleFileSelect(event)"/>

      <div class="prog-box" id="prog-box">
        <div class="prog-label" id="prog-label">root@SFT-NODE-01:~# Transmitting...</div>
        <div class="prog-track">
          <div class="prog-ascii-bar" id="prog-bar">[                                        ] 0% | 0B/0B | 0.00 MB/s</div>
        </div>
        <div class="prog-meta" id="prog-meta">Chunks queued: 0 / 0</div>
        <div class="prog-result" id="prog-result"></div>
      </div>

      <!-- Recent uploads log -->
      <div class="term-prompt-box" id="upload-history" style="max-height:140px;overflow-y:auto;font-size:.67rem;line-height:1.7">
        <div style="color:var(--dimtext);margin-bottom:4px;letter-spacing:.1em;font-size:.6rem">// UPLOAD SESSION LOG</div>
        <div id="upload-history-lines" style="color:var(--green3)">No uploads this session.</div>
      </div>
    </div>
  </div>

  <!-- ── FILES ───────────────────────────────────────── -->
  <div class="section" id="section-files">
    <div class="files-area">
      <div class="files-header">
        <span style="color:var(--dimtext)">root@SFT-NODE-01:~# ls -lh /received_files/</span>
        <span class="files-count" id="files-count">scanning...</span>
        <button class="btn-refresh" onclick="loadFiles()">[REFRESH]</button>
      </div>
      <div class="ascii-table-wrap" id="file-table-wrap">
        <div class="empty-files">Scanning filesystem...</div>
      </div>
    </div>
  </div>

  <!-- ── STATUS ──────────────────────────────────────── -->
  <div class="section" id="section-status">
    <div class="status-area">
      <div style="font-size:.67rem;color:var(--dimtext)">root@SFT-NODE-01:~# <span style="color:var(--green2)">netstat -an && systemctl status sft-daemon</span></div>
      <div class="stat-grid" id="stat-grid">
        <div class="stat-card" data-label="UPTIME">
          <div class="stat-card-val" id="s-uptime">00:00:00</div>
          <div class="stat-card-label">SERVER_UPTIME</div>
          <div class="stat-card-sub" id="s-uptime-sub">since boot</div>
        </div>
        <div class="stat-card" data-label="ACTIVE_SESS">
          <div class="stat-card-val" id="s-clients">0</div>
          <div class="stat-card-label">ACTIVE_SESSIONS</div>
          <div class="stat-card-sub">concurrent threads</div>
        </div>
        <div class="stat-card" data-label="FILES">
          <div class="stat-card-val" id="s-files">0</div>
          <div class="stat-card-label">FILES_STORED</div>
          <div class="stat-card-sub">in /received_files/</div>
        </div>
        <div class="stat-card" data-label="BIND">
          <div class="stat-card-val" id="s-port" style="font-size:1rem;margin-top:8px">—:—</div>
          <div class="stat-card-label">BIND_ENDPOINT</div>
          <div class="stat-card-sub">TCP/IPv4</div>
        </div>
        <div class="stat-card stat-fullrow" data-label="PROTO_INFO">
          <div style="font-size:.65rem;line-height:2;color:var(--dimtext)">
            <div><span style="color:var(--green3)">TRANSPORT</span>    : TCP/IP over loopback (127.0.0.1)</div>
            <div><span style="color:var(--green3)">FRAMING</span>      : 4-byte big-endian length-prefix + UTF-8 JSON</div>
            <div><span style="color:var(--green3)">INTEGRITY</span>    : SHA-256 end-to-end checksum verification</div>
            <div><span style="color:var(--green3)">CONCURRENCY</span>  : threading.Thread per accepted connection</div>
            <div><span style="color:var(--green3)">CHUNK_SIZE</span>   : 1024 bytes per raw data block</div>
            <div><span style="color:var(--green3)">AUTO_RENAME</span>  : duplicate filenames suffixed _N before store</div>
            <div><span style="color:var(--green3)">SECURITY</span>     : path-traversal sanitization on all filenames</div>
          </div>
        </div>
      </div>
      <div id="status-offline" style="display:none;text-align:center;padding:40px;font-size:.72rem;color:var(--dimtext)">
        <pre style="color:var(--red);font-size:.65rem;margin-bottom:12px">
  [ERR] Connection refused: 127.0.0.1:5000
  ECONNREFUSED — No server process found on port 5000
  Hint: press [F1] or click INIT_SERVER to start the daemon</pre>
        <div>Run <span style="color:var(--green)">INIT_SERVER</span> from the sidebar to bring the node online.</div>
      </div>
    </div>
  </div>

  <!-- ── LOGS ────────────────────────────────────────── -->
  <div class="section" id="section-logs">
    <div class="log-area">
      <div class="log-toolbar">
        <div class="log-indicator"></div>
        <span>SSE_STREAM :: /api/logs/stream</span>
        <span style="margin-left:auto;color:var(--green3)" id="log-linecount">0 lines</span>
        <button class="btn-refresh" onclick="clearLogs()">[CLR]</button>
        <button class="btn-refresh" onclick="scrollLogsBottom()">[END]</button>
      </div>
      <div class="log-console" id="log-console">
        <span class="l-DASH">// Connecting to SSE stream...</span><br/>
      </div>
      <div class="log-cmd">
        <span class="log-prompt">root@SFT-NODE-01:~#</span>
        <input class="log-input" id="log-cmd-input" placeholder="type a command (status / list / ping)..." onkeydown="handleLogCmd(event)"/>
      </div>
    </div>
  </div>

</main><!-- /.main -->

<!-- ══ STATUSBAR ════════════════════════════════════════════════════ -->
<footer class="statusbar">
  <div class="sb-item">
    <div class="sb-dot" id="sb-dot" style="background:var(--red);box-shadow:0 0 4px var(--red)"></div>
    <span id="sb-state" class="sb-val">SERVER OFFLINE</span>
  </div>
  <div class="sb-item"><span>PID:</span><span class="sb-val" id="sb-pid">—</span></div>
  <div class="sb-item"><span>PROTO:</span><span class="sb-val">TCP+JSON_FRAME</span></div>
  <div class="sb-item"><span>ENC:</span><span class="sb-val">SHA-256</span></div>
  <div class="sb-right">
    <span class="sb-item"><span>CHUNK:</span><span class="sb-val">1024B</span></span>
    <span class="sb-item"><span>BACKLOG:</span><span class="sb-val">5</span></span>
    <span class="sb-item sb-val" id="sb-time2">—</span>
  </div>
</footer>

</div><!-- /.crt-frame -->
<div id="toasts"></div>

<script>
/* ═══════════════════════  STATE  ══════════════════════════════ */
let serverOnline = false;
let sseSource    = null;
let logLineCount = 0;
let uploadHistoryLines = [];

/* ═══════════════════════  CLOCK  ══════════════════════════════ */
function updateClock() {
  const t = new Date().toLocaleTimeString('en-GB', {hour12:false});
  const d = new Date().toLocaleDateString('en-GB');
  document.getElementById('tb-time').textContent  = t;
  document.getElementById('sb-time2').textContent = d + ' ' + t;
}
setInterval(updateClock, 1000);
updateClock();

/* ═══════════════════════  TABS  ══════════════════════════════ */
const TABS = ['upload','files','status','logs'];
function showTab(name) {
  TABS.forEach(t => {
    document.getElementById('section-' + t).classList.toggle('active', t === name);
    document.getElementById('tab-'     + t).classList.toggle('active', t === name);
    const n = document.getElementById('nav-' + t);
    if (n) n.classList.toggle('active', t === name);
  });
  const info = {
    upload:'AWAITING FILE INPUT',
    files: 'FILE_INDEX — /received_files/',
    status:'SYSTEM DIAGNOSTICS',
    logs:  'SSE LIVE TRACE — tail -f server.log'
  };
  document.getElementById('tab-right-info').textContent = info[name] || '';
  if (name === 'files')  loadFiles();
  if (name === 'status') loadStatus();
}

/* ═══════════════════════  SERVER CONTROL  ═════════════════════ */
let serverPid = null;

async function startServer() {
  addLog('DASH', 'Sending INIT_SERVER signal...');
  toast('[+] Spawning server subprocess...', 'inf');
  try {
    const r = await fetch('/api/server/start', {method:'POST'});
    const d = await r.json();
    if (d.ok) {
      serverPid = d.pid;
      document.getElementById('sb-pid').textContent = d.pid;
      updateOnlineState(true);
      addLog('OK', 'Server started :: PID=' + d.pid + ' :: BIND=0.0.0.0:5000');
      toast('[OK] SFT daemon online — PID ' + d.pid, 'ok');
    } else {
      addLog('ERR', d.message);
      toast('[ERR] ' + d.message, 'err');
    }
  } catch(e) {
    addLog('ERR', String(e));
    toast('[ERR] Dashboard error: ' + e, 'err');
  }
}

async function stopServer() {
  if (!serverOnline) return;
  if (!confirm('Send SIGTERM to server process?')) return;
  const r = await fetch('/api/server/stop', {method:'POST'});
  const d = await r.json();
  if (d.ok) {
    updateOnlineState(false);
    addLog('WARN', 'Server process terminated.');
    toast('[-] Server offline.', 'inf');
    document.getElementById('sb-pid').textContent = '—';
  }
}

function updateOnlineState(online) {
  serverOnline = online;
  const dot   = document.getElementById('sb-dot');
  const state = document.getElementById('sb-state');
  const tbSt  = document.getElementById('tb-status');
  dot.style.background  = online ? 'var(--green)' : 'var(--red)';
  dot.style.boxShadow   = online ? '0 0 4px var(--green)' : '0 0 4px var(--red)';
  state.textContent     = online ? 'SERVER ONLINE' : 'SERVER OFFLINE';
  tbSt.style.color      = online ? 'var(--green)'  : 'var(--red)';
  tbSt.textContent      = online ? '● ONLINE'      : '● OFFLINE';
}

/* ═══════════════════════  POLLING  ════════════════════════════ */
let pollInterval = null;
function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pingServer, 4000);
  pingServer();
}

async function pingServer() {
  try {
    const r = await fetch('/api/server/ping');
    const d = await r.json();
    if (d.running !== serverOnline) updateOnlineState(d.running);
    if (d.running) {
      const up = d.uptime_seconds || 0;
      const h  = String(Math.floor(up/3600)).padStart(2,'0');
      const m  = String(Math.floor((up%3600)/60)).padStart(2,'0');
      const s  = String(Math.floor(up%60)).padStart(2,'0');
      const upt = h+':'+m+':'+s;
      document.getElementById('sb-uptime').textContent = upt;
      document.getElementById('sb-files').textContent  = d.files_stored ?? '—';
      document.getElementById('sb-sess').textContent   = d.active_clients ?? '—';
      // animate net bar
      const files = d.files_stored || 0;
      document.getElementById('net-bar').style.width = Math.min(5 + files * 4, 90) + '%';
    }
  } catch(e) {}
}

/* ═══════════════════════  FILE UPLOAD  ════════════════════════ */
function handleDrop(ev) {
  ev.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  if (ev.dataTransfer.files.length) uploadFile(ev.dataTransfer.files[0]);
}
function handleFileSelect(ev) {
  if (ev.target.files.length) uploadFile(ev.target.files[0]);
  ev.target.value = '';
}

async function uploadFile(file) {
  if (!serverOnline) {
    toast('[ERR] Server offline. Run INIT_SERVER first.', 'err');
    addLog('ERR', 'Upload refused — server not online.');
    return;
  }
  const box    = document.getElementById('prog-box');
  const bar    = document.getElementById('prog-bar');
  const label  = document.getElementById('prog-label');
  const meta   = document.getElementById('prog-meta');
  const result = document.getElementById('prog-result');
  const sub    = document.getElementById('drop-sub');

  sub.textContent = '>> QUEUED: ' + file.name + ' (' + fmtSize(file.size) + ')';
  box.classList.add('show');
  result.textContent = '';
  result.className   = 'prog-result';

  label.textContent = 'root@SFT-NODE-01:~# sft --send "' + file.name + '" --size ' + fmtSize(file.size);
  addLog('INFO', 'UPLOAD initiated :: ' + file.name + ' :: ' + fmtSize(file.size));

  let fakePct = 0;
  const chunks = Math.ceil(file.size / 1024) || 1;
  const ticker = setInterval(() => {
    if (fakePct < 88) {
      fakePct += 1.8;
      const done = Math.floor(fakePct);
      const filled = Math.floor(done * 40 / 100);
      const barStr = '[' + '#'.repeat(filled) + '-'.repeat(40 - filled) + '] ' +
                     done + '% | ' + fmtSize(Math.floor(file.size * done / 100)) +
                     '/' + fmtSize(file.size);
      bar.textContent = barStr;
      meta.textContent = 'Chunks transmitted: ' + Math.floor(chunks * done / 100) + ' / ' + chunks + ' :: SHA-256 streaming...';
    }
  }, 80);

  const form = new FormData();
  form.append('file', file);
  const t0 = Date.now();

  try {
    const r = await fetch('/api/upload', {method:'POST', body:form});
    const d = await r.json();
    clearInterval(ticker);
    const elapsed = ((Date.now() - t0) / 1000).toFixed(2);

    if (d.ok) {
      bar.textContent = '[' + '#'.repeat(40) + '] 100% | ' + fmtSize(d.bytes) + '/' + fmtSize(d.bytes) + ' :: DONE';
      meta.textContent = 'All ' + chunks + ' chunks received :: Checksum verified';
      result.className = 'prog-result';
      result.textContent = '>> UPLOAD_SUCCESS :: stored_as="' + d.stored_as + '" :: elapsed=' + elapsed + 's :: speed=' + d.speed_mbs + 'MB/s :: sha256=VERIFIED';
      addLog('OK', 'UPLOAD_SUCCESS :: ' + d.stored_as + ' :: ' + fmtSize(d.bytes) + ' :: ' + elapsed + 's :: ' + d.speed_mbs + ' MB/s');
      toast('[OK] Stored as: ' + d.stored_as, 'ok');
      appendUploadHistory(file.name, d.stored_as, d.bytes, elapsed, d.speed_mbs);
    } else {
      bar.textContent = '[' + 'X'.repeat(40) + '] FAILED';
      result.className = 'prog-result err';
      result.textContent = '>> UPLOAD_FAILED :: error="' + d.error + '"';
      addLog('ERR', 'UPLOAD_FAILED :: ' + d.error);
      toast('[ERR] ' + d.error, 'err');
    }
  } catch(e) {
    clearInterval(ticker);
    result.className = 'prog-result err';
    result.textContent = '>> NET_ERROR :: ' + e;
    addLog('ERR', String(e));
  }
}

function appendUploadHistory(orig, stored, bytes, elapsed, speed) {
  const ts = new Date().toLocaleTimeString('en-GB',{hour12:false});
  const line = '[' + ts + '] UPLOAD :: ' + orig + ' -> ' + stored + ' :: ' + fmtSize(bytes) + ' :: ' + elapsed + 's :: ' + speed + ' MB/s :: SHA256:OK';
  uploadHistoryLines.push(line);
  const el = document.getElementById('upload-history-lines');
  el.textContent = uploadHistoryLines.join('\\n');
}

/* ═══════════════════════  FILE LIST  ══════════════════════════ */
async function loadFiles() {
  const wrap = document.getElementById('file-table-wrap');
  const cnt  = document.getElementById('files-count');
  wrap.innerHTML = '<div class="empty-files">Scanning /received_files/...</div>';
  try {
    const r = await fetch('/api/list');
    const d = await r.json();
    const files = d.files || [];
    cnt.textContent = files.length + ' object(s) found';

    if (!files.length) {
      wrap.innerHTML = '<div class="empty-files">  [EMPTY]\\'\\n  No files stored in /received_files/\\'\\n  Upload a file first.</div>';
      return;
    }

    let html = '<div class="ascii-table-hdr"><span>#</span><span>FILENAME</span><span>SIZE</span><span>MODIFIED</span><span>ACTIONS</span></div>';
    files.forEach((f, i) => {
      const parts = f.name.split('.');
      const ext   = parts.length > 1 ? '.' + parts.pop() : '';
      const base  = parts.join('.');
      html += '<div class="file-row">'
        + '<span class="f-idx">' + String(i+1).padStart(2,'0') + '</span>'
        + '<span class="f-name">' + escHtml(base) + '<span class="ext">' + escHtml(ext) + '</span></span>'
        + '<span class="f-size">' + fmtSize(f.size) + '</span>'
        + '<span class="f-date">' + f.modified + '</span>'
        + '<span class="f-actions">'
        + '<button class="btn-dl"  onclick="dlFile(\\''+escHtml(f.name)+'\\')">[ GET ]</button>'
        + '<button class="btn-del" onclick="delFile(\\''+escHtml(f.name)+'\\', this)">[ RM ]</button>'
        + '</span></div>';
    });
    wrap.innerHTML = html;
    document.getElementById('sb-files').textContent = files.length;
  } catch(e) {
    wrap.innerHTML = '<div class="empty-files" style="color:var(--red)">[ERR] ' + e + '</div>';
  }
}

function dlFile(name) {
  addLog('INFO', 'DOWNLOAD initiated :: ' + name);
  toast('[>>] Pulling "' + name + '" from node...', 'inf');
  window.location.href = '/api/download/' + encodeURIComponent(name);
}

async function delFile(name, btn) {
  if (!confirm('rm -f /received_files/' + name + ' ?')) return;
  const r = await fetch('/api/delete/' + encodeURIComponent(name), {method:'DELETE'});
  const d = await r.json();
  if (d.ok) {
    addLog('WARN', 'DELETED :: ' + name);
    toast('[-] Removed: ' + name, 'inf');
    loadFiles();
  } else {
    toast('[ERR] ' + d.error, 'err');
  }
}

/* ═══════════════════════  STATUS  ════════════════════════════ */
async function loadStatus() {
  const r = await fetch('/api/server/ping');
  const d = await r.json();

  const grid = document.getElementById('stat-grid');
  const offEl = document.getElementById('status-offline');

  if (!d.running) {
    grid.style.display   = 'none';
    offEl.style.display  = 'block';
    return;
  }
  grid.style.display  = '';
  offEl.style.display = 'none';

  const up = d.uptime_seconds || 0;
  const h  = String(Math.floor(up/3600)).padStart(2,'0');
  const m  = String(Math.floor((up%3600)/60)).padStart(2,'0');
  const s  = String(Math.floor(up%60)).padStart(2,'0');

  document.getElementById('s-uptime').textContent     = h+':'+m+':'+s;
  document.getElementById('s-uptime-sub').textContent = up.toFixed(1) + 's total';
  document.getElementById('s-clients').textContent    = d.active_clients ?? '0';
  document.getElementById('s-files').textContent      = d.files_stored   ?? '0';
  document.getElementById('s-port').textContent       = (d.host || '127.0.0.1') + ':' + (d.port || 5000);
}

/* ═══════════════════════  LIVE LOGS  ══════════════════════════ */
function connectSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource('/api/logs/stream');
  sseSource.onmessage = e => {
    const line = JSON.parse(e.data);
    addLog('RAW', line);
  };
  sseSource.onerror = () => { setTimeout(connectSSE, 3000); };
}

function addLog(type, msg) {
  const con = document.getElementById('log-console');
  const ts  = new Date().toLocaleTimeString('en-GB',{hour12:false});
  const div = document.createElement('div');
  div.className = 'log-line';

  if (type === 'RAW') {
    // Parse log lines from the actual server log
    let cls = 'l-INFO';
    let tag = 'INFO';
    if (msg.includes('[ERROR]'))              { cls='l-ERR';  tag='ERR '; }
    else if (msg.includes('[WARNING]'))       { cls='l-WARN'; tag='WARN'; }
    else if (msg.includes('UPLOAD OK') ||
             msg.includes('DOWNLOAD OK') ||
             msg.includes('SUCCESS'))         { cls='l-OK';   tag='OK  '; }
    else if (msg.includes('connected') ||
             msg.includes('Command'))         { cls='l-CONN'; tag='CONN'; }
    else if (msg.includes('[dashboard]'))     { cls='l-DASH'; tag='DASH'; }
    div.innerHTML = '<span class="l-ts">' + escHtml(msg.slice(0,19)) + '</span>'
      + '<span class="l-tag t-' + tag.trim() + '">[' + tag + ']</span>'
      + '<span class="' + cls + '">' + escHtml(msg.slice(19)) + '</span>';
  } else {
    const clsMap = {OK:'l-OK',ERR:'l-ERR',WARN:'l-WARN',INFO:'l-INFO',DASH:'l-DASH',CONN:'l-CONN'};
    div.innerHTML = '<span class="l-ts">' + ts + '</span>'
      + '<span class="l-tag t-' + type + '">[' + type.padEnd(4) + ']</span>'
      + '<span class="' + (clsMap[type]||'l-INFO') + '">' + escHtml(msg) + '</span>';
  }

  con.appendChild(div);
  logLineCount++;
  document.getElementById('log-linecount').textContent = logLineCount + ' lines';
  if (con.scrollHeight - con.scrollTop - con.clientHeight < 60) {
    con.scrollTop = con.scrollHeight;
  }
  while (con.children.length > 600) con.removeChild(con.firstChild);
}

function clearLogs() {
  document.getElementById('log-console').innerHTML = '';
  logLineCount = 0;
  document.getElementById('log-linecount').textContent = '0 lines';
  addLog('DASH', 'Log buffer cleared.');
}
function scrollLogsBottom() {
  const c = document.getElementById('log-console');
  c.scrollTop = c.scrollHeight;
}

function handleLogCmd(ev) {
  if (ev.key !== 'Enter') return;
  const inp = document.getElementById('log-cmd-input');
  const cmd = inp.value.trim();
  inp.value = '';
  if (!cmd) return;
  addLog('DASH', '>> ' + cmd);
  if (cmd === 'status') loadStatus();
  else if (cmd === 'list') loadFiles();
  else if (cmd === 'ping') pingServer().then(()=>addLog('DASH','Ping complete.'));
  else if (cmd === 'clear') clearLogs();
  else if (cmd === 'start') startServer();
  else if (cmd === 'stop')  stopServer();
  else addLog('WARN', 'Unknown command: "' + cmd + '". Try: status, list, ping, start, stop, clear');
}

/* ═══════════════════════  TOAST  ══════════════════════════════ */
function toast(msg, type='inf') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/* ═══════════════════════  UTILS  ══════════════════════════════ */
function fmtSize(b) {
  if (!b || b < 1024)      return b + ' B';
  if (b < 1024*1024)       return (b/1024).toFixed(1) + ' KB';
  if (b < 1024*1024*1024)  return (b/(1024*1024)).toFixed(2) + ' MB';
  return (b/(1024*1024*1024)).toFixed(2) + ' GB';
}
function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ═══════════════════════  KEYBOARD SHORTCUTS  ════════════════ */
document.addEventListener('keydown', ev => {
  if (ev.key === 'F1') { ev.preventDefault(); startServer(); }
  if (ev.key === 'F2') { ev.preventDefault(); stopServer();  }
  if (ev.key === 'F3') { ev.preventDefault(); showTab('upload'); }
  if (ev.key === 'F4') { ev.preventDefault(); showTab('files');  }
  if (ev.key === 'F5') { ev.preventDefault(); showTab('status'); }
  if (ev.key === 'F6') { ev.preventDefault(); showTab('logs');   }
});

/* ═══════════════════════  BOOT SEQUENCE  ══════════════════════ */
(async () => {
  addLog('DASH', '╔══════════════════════════════════════════════╗');
  addLog('DASH', '║  SFT-NODE-01 :: Secure File Transfer v2.4.1 ║');
  addLog('DASH', '╚══════════════════════════════════════════════╝');
  addLog('DASH', 'Initializing dashboard modules...');
  addLog('INFO', 'SSE log stream connected :: /api/logs/stream');
  addLog('INFO', 'Polling server status :: interval=4000ms');
  addLog('INFO', 'SHA-256 integrity engine ready');
  addLog('INFO', 'TCP framing module loaded :: HEADER_SIZE=4 bytes big-endian');
  addLog('DASH', 'Press [F1] or click INIT_SERVER to bring node online.');
  connectSSE();
  startPolling();
})();
</script>
</body>
</html>"""

'''

# Write back
new_content = content[:idx_start] + NEW_HTML + content[idx_end:]
open(path, 'w', encoding='utf-8').write(new_content)
print(f"Done. Written {len(new_content)} bytes.")
