import os

html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>THESOUND.EARTH</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='46' fill='%23060a12' stroke='%2338bdf8' stroke-width='6'/%3E%3Cpath d='M20 50 Q35 25 50 50 T80 50' fill='none' stroke='%2338bdf8' stroke-width='6' stroke-linecap='round'/%3E%3Ccircle cx='50' cy='50' r='8' fill='%2338bdf8'/%3E%3C/svg%3E" />
  <style>
    :root {
      --border: rgba(255, 255, 255, 0.10);
      --border-bright: rgba(255, 255, 255, 0.22);
      --text: #f4f4f5;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-subtle: rgba(56, 189, 248, 0.15);
      --card-bg: rgba(10, 14, 22, 0.88);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', sans-serif; }
    html, body { width: 100vw; height: 100vh; overflow: hidden; background: #020409; color: var(--text); }

    #globeViz {
      position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
      cursor: crosshair; transition: left 0.3s cubic-bezier(0.16, 1, 0.3, 1), width 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    body.panel-maximized #globeViz {
      left: 50vw; width: 50vw;
    }

    .watermark {
      position: fixed; top: 22px; left: 26px; z-index: 25;
      display: flex; align-items: center; gap: 10px; cursor: pointer;
      opacity: 0.85; transition: opacity 0.2s, left 0.3s cubic-bezier(0.16, 1, 0.3, 1); user-select: none;
    }
    .watermark:hover { opacity: 1; }
    body.panel-maximized .watermark { left: calc(50vw + 26px); }
    .wm-mark {
      width: 26px; height: 26px; border-radius: 50%;
      border: 1.5px solid rgba(255, 255, 255, 0.45);
      display: grid; place-items: center; font-size: 10.5px; font-weight: 700; color: #fff;
    }
    .wm-title { font-size: 15px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(255, 255, 255, 0.9); }

    .vis-switch {
      position: fixed; top: 22px; right: 26px; z-index: 25;
      display: flex; background: rgba(10, 12, 18, 0.82); backdrop-filter: blur(14px);
      border: 1px solid var(--border); border-radius: 10px; padding: 3px; gap: 3px;
    }
    .vis-switch button {
      border: none; border-radius: 7px; background: transparent; color: var(--muted);
      font-size: 11px; font-weight: 600; padding: 6px 12px; cursor: pointer; transition: 0.15s;
    }
    .vis-switch button:hover { color: var(--text); background: rgba(255, 255, 255, 0.05); }
    .vis-switch button.active { background: #23252d; color: var(--text); }
    .vis-switch button.catalog-trigger { color: #7dd3fc; border-left: 1px solid var(--border); border-radius: 0 7px 7px 0; }

    .ocean-card {
      position: fixed; top: 72px; right: 340px; z-index: 20; width: 300px;
      background: var(--card-bg); backdrop-filter: blur(18px);
      border: 1px solid var(--border); border-radius: 16px; padding: 14px 16px;
      display: none; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.55);
    }
    .ocean-card.open { display: block; }
    .oc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
    .oc-name { font-size: 14.5px; font-weight: 600; color: #ffffff; }
    .oc-sub { font-size: 11px; color: var(--accent); margin-top: 2px; }
    .oc-close { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; }
    .oc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 6px; }
    .oc-stat { background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px; padding: 6px 8px; }
    .oc-stat .lbl { font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .oc-stat .val { font-size: 12.5px; font-weight: 600; margin-top: 2px; font-family: ui-monospace, monospace; }
    .oc-note { font-size: 11px; color: #cbd5e1; margin-top: 8px; line-height: 1.4; }
    .oc-brief {
      font-size: 11px; color: #7dd3fc; margin-top: 8px; line-height: 1.45;
      border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 8px;
    }

    .live-boxes {
      position: fixed; top: 72px; right: 26px; z-index: 20; width: 300px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .viz-box {
      background: rgba(10, 14, 22, 0.78); backdrop-filter: blur(18px);
      border: 1px solid var(--border); border-radius: 14px; padding: 10px 12px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
    }
    .viz-head {
      display: flex; justify-content: space-between; align-items: center;
      font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--muted); margin-bottom: 6px;
    }
    .viz-head span:last-child { color: var(--accent); font-family: ui-monospace, monospace; text-transform: none; }
    .viz-box canvas { width: 100%; height: 82px; display: block; border-radius: 8px; background: rgba(4, 7, 13, 0.7); }

    /* Bottom Dock with Year Selector */
    .bottom-dock {
      position: fixed; left: 24px; right: 24px; bottom: 16px; z-index: 20;
      background: rgba(10, 12, 18, 0.76); backdrop-filter: blur(18px);
      border: 1px solid var(--border); border-radius: 18px; padding: 12px 18px;
      display: flex; flex-direction: column; gap: 8px;
      transition: left 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    body.panel-maximized .bottom-dock {
      left: calc(50vw + 24px);
    }

    /* Year Selector Bar (Requirement 3) */
    .tl-year-bar {
      display: flex; align-items: center; justify-content: space-between;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding-bottom: 6px;
    }
    .tl-year-lbl { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; }
    .tl-year-buttons { display: flex; gap: 4px; }
    .tl-year-btn {
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-radius: 6px;
      color: var(--muted); font-size: 10.5px; font-weight: 600; padding: 3px 8px; cursor: pointer; transition: 0.15s;
    }
    .tl-year-btn:hover { color: var(--text); background: rgba(255, 255, 255, 0.10); }
    .tl-year-btn.active { background: #0284c7; border-color: #38bdf8; color: #fff; }

    .timeline-wrap { display: flex; align-items: center; gap: 14px; }
    .tl-date { font-family: ui-monospace, monospace; font-size: 12px; color: var(--accent); min-width: 90px; }
    .tl-track { flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .tl-slider {
      -webkit-appearance: none; appearance: none; width: 100%; height: 4px;
      background: rgba(255, 255, 255, 0.16); border-radius: 999px; outline: none; cursor: pointer;
    }
    .tl-slider::-webkit-slider-thumb {
      -webkit-appearance: none; appearance: none; width: 14px; height: 14px; border-radius: 50%;
      background: #ffffff; border: 2px solid var(--accent); cursor: grab;
    }
    .tl-months { display: flex; justify-content: space-between; font-size: 10px; color: rgba(255, 255, 255, 0.42); user-select: none; }

    .transport-row { display: flex; align-items: center; justify-content: space-between; height: 30px; }
    .timer { font-family: ui-monospace, monospace; font-size: 13px; color: var(--text); width: 120px; }
    .timer span { color: var(--muted); }
    .track-name { font-size: 12px; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
    .controls { display: flex; align-items: center; gap: 16px; }
    .ctrl-btn { background: none; border: none; color: #e4e4e7; cursor: pointer; display: grid; place-items: center; padding: 4px; opacity: 0.85; }
    .ctrl-btn:hover { opacity: 1; color: var(--accent); }
    .ctrl-btn svg { width: 17px; height: 17px; }
    .right-tools { display: flex; align-items: center; gap: 12px; justify-content: flex-end; }
    .ab-toggle { display: flex; background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: 8px; padding: 2px; }
    .ab-toggle button { width: 26px; height: 22px; border: none; border-radius: 6px; background: transparent; color: var(--muted); font-size: 11px; font-weight: 600; cursor: pointer; }
    .ab-toggle button.active { background: #27272f; color: var(--text); }

    /* UNIFIED LEFT PANEL: SOUNDSCAPES + EVIDENCE (Requirement 6) */
    #leftPanel {
      position: fixed; top: 68px; left: 26px; z-index: 30;
      width: min(440px, calc(100vw - 32px)); max-height: calc(100vh - 120px);
      overflow-y: auto; background: var(--card-bg); backdrop-filter: blur(22px);
      border: 1px solid var(--border); border-radius: 16px; padding: 18px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.65); display: block;
      transition: width 0.3s cubic-bezier(0.16, 1, 0.3, 1), max-height 0.3s, border-radius 0.3s, top 0.3s, left 0.3s;
    }
    #leftPanel.closed { display: none; }
    #leftPanel.maximized {
      top: 0 !important; left: 0 !important; bottom: 0 !important;
      width: 50vw !important; min-width: 500px !important;
      max-height: 100vh !important; height: 100vh !important;
      border-radius: 0 !important; border-top: none !important; border-bottom: none !important;
      border-left: none !important; border-right: 1px solid var(--border) !important;
      z-index: 35 !important;
    }

    .panel-top-bar { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
    .panel-title { font-size: 15px; font-weight: 600; color: #ffffff; }
    .panel-sub { font-size: 11px; color: var(--accent); margin-top: 2px; }
    .panel-window-controls { display: flex; gap: 4px; align-items: center; }
    .p-win-btn {
      background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
      border-radius: 6px; color: var(--muted); width: 26px; height: 24px;
      display: grid; place-items: center; font-size: 11px; cursor: pointer; transition: 0.15s;
    }
    .p-win-btn:hover { background: rgba(255, 255, 255, 0.12); color: #fff; }

    /* Navigation tabs inside merged left panel */
    .panel-tabs {
      display: flex; gap: 4px; overflow-x: auto; margin-bottom: 14px;
      border-bottom: 1px solid var(--border); padding-bottom: 8px;
    }
    .panel-tab-btn {
      background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border); border-radius: 7px;
      color: var(--muted); font-size: 11px; font-weight: 600; padding: 5px 10px; cursor: pointer; white-space: nowrap; transition: 0.15s;
    }
    .panel-tab-btn:hover { color: #fff; background: rgba(255, 255, 255, 0.07); }
    .panel-tab-btn.active { background: #23252d; color: var(--text); border-color: var(--accent); }

    .panel-view { display: none; }
    .panel-view.active { display: block; }

    /* Minimized Floating Pill */
    #minimizedPill {
      position: fixed; top: 72px; left: 26px; z-index: 25;
      background: rgba(10, 14, 22, 0.88); backdrop-filter: blur(14px);
      border: 1px solid var(--border); border-radius: 20px; padding: 7px 14px;
      display: none; align-items: center; gap: 8px; cursor: pointer;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5); font-size: 11.5px; font-weight: 600; color: #38bdf8;
    }
    #minimizedPill:hover { border-color: var(--accent); }
    #minimizedPill.show { display: flex; }

    .rule-note {
      font-size: 11px; color: #94a3b8; background: rgba(255, 255, 255, 0.03);
      border: 1px dashed rgba(255, 255, 255, 0.12); border-radius: 8px;
      padding: 8px 10px; margin-bottom: 14px; line-height: 1.45;
    }
    .track-list { display: flex; flex-direction: column; gap: 10px; }
    .track-card {
      background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border);
      border-radius: 12px; padding: 12px 14px; transition: 0.18s; cursor: pointer;
    }
    .track-card:hover { border-color: rgba(56, 189, 248, 0.4); background: rgba(56, 189, 248, 0.04); }
    .track-card.active { border-color: var(--accent); background: rgba(56, 189, 248, 0.09); }
    .tc-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .tc-title { font-size: 13.5px; font-weight: 600; color: #fff; }
    .tc-badge {
      font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 6px;
      background: rgba(255,255,255,0.08); color: var(--muted); text-transform: uppercase;
    }
    .track-card.active .tc-badge { background: var(--accent); color: #020409; }
    .tc-meta { font-size: 11px; color: var(--muted); line-height: 1.4; font-family: ui-monospace, monospace; }
    .tc-section-badge {
      display: inline-block; font-size: 10.5px; font-weight: 600; color: #38bdf8;
      background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 6px; padding: 3px 8px; margin-top: 7px;
    }
    .tc-visual {
      margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);
      font-size: 11px; color: #cbd5e1; line-height: 1.4;
    }
    .tc-visual a { color: var(--accent); text-decoration: none; font-weight: 500; }
    .tc-visual a:hover { text-decoration: underline; }
    .tc-visual small { display: block; color: var(--muted); font-size: 10px; margin-top: 2px; }

    /* Evidence Tables inside Left Panel */
    .table-container {
      max-height: calc(100vh - 280px); min-height: 280px; overflow: auto;
      border: 1px solid var(--border); border-radius: 10px;
      background: rgba(4, 7, 13, 0.7); margin-top: 10px;
    }
    .audit-table { width: 100%; border-collapse: collapse; font-size: 11px; text-align: left; }
    .audit-table th {
      position: sticky; top: 0; background: #121824; color: var(--muted); font-weight: 600;
      text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; padding: 8px 10px;
      border-bottom: 1px solid var(--border); z-index: 2;
    }
    .audit-table td { padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); font-family: ui-monospace, monospace; }
    .audit-table tr.active-bar {
      background: rgba(56, 189, 248, 0.22) !important;
      border-left: 3px solid var(--accent);
      color: #ffffff; font-weight: 600;
    }
    .spec-table { width: 100%; border-collapse: collapse; font-size: 11.5px; margin-top: 8px; }
    .spec-table th { background: rgba(255,255,255,0.04); padding: 8px 10px; text-align: left; color: var(--muted); border-bottom: 1px solid var(--border); font-size: 10.5px; }
    .spec-table td { padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: top; line-height: 1.45; }
    .spec-table code { color: #7dd3fc; font-family: ui-monospace, monospace; font-size: 10.5px; }

    .limits-box {
      background: rgba(245, 158, 11, 0.06); border: 1px solid rgba(245, 158, 11, 0.25);
      border-radius: 12px; padding: 14px 16px; margin: 12px 0 16px 0; color: #fde68a; font-size: 12px; line-height: 1.55;
    }
    .limits-box strong { color: #fff; }
    .limits-list { list-style: square; margin-left: 18px; margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }

    /* SVS Catalog UX Fixes */
    #svsCatalog {
      position: fixed; z-index: 40; top: 68px; right: 26px;
      width: min(680px, calc(100vw - 32px)); max-height: calc(100vh - 120px);
      overflow-y: auto; padding: 18px; border: 1px solid var(--border); border-radius: 16px;
      background: rgba(8, 12, 20, 0.96); backdrop-filter: blur(20px);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.65); display: none;
    }
    #svsCatalog.open { display: block; }
    #svsCatalog h2 { font-size: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
    #svsCatalog input, #svsCatalog select { color: var(--text); background: #111a26; border: 1px solid var(--border); border-radius: 7px; padding: 8px; }
    #svsCatalog input[type=search] { width: 100%; }
    .svs-row { display: flex; gap: 8px; margin: 9px 0; }
    .svs-button { background: #122334; border: 1px solid #31516b; color: #e0f2fe; border-radius: 7px; padding: 7px 12px; cursor: pointer; font-size: 12px; font-weight: 500; transition: 0.15s; }
    .svs-button:hover:not(:disabled) { background: #1a324a; border-color: var(--accent); }
    .svs-button:disabled { opacity: .5; cursor: wait; }
    .svs-button.primary { background: #0284c7; border-color: #38bdf8; color: #fff; font-weight: 600; }
    .svs-button.primary:hover:not(:disabled) { background: #0369a1; }
    #svsPinnedSelection {
      display: none; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.28);
      border-radius: 12px; padding: 12px 14px; margin-bottom: 14px;
    }
    #svsPinnedSelection.open { display: block; }
    #svsPinnedSelection h3 { font-size: 13.5px; color: #7dd3fc; margin-bottom: 6px; }
    #svsPinnedSelection p { font-size: 11.5px; color: #cbd5e1; line-height: 1.45; margin-bottom: 6px; }
    #svsPinnedSelection video { width: 100%; max-height: 200px; border-radius: 8px; background: #000; margin: 6px 0; }
    #svsResults { display: grid; gap: 7px; margin: 10px 0; max-height: 240px; overflow-y: auto; }
    .svs-result { display: block; width: 100%; text-align: left; color: var(--text); background: rgba(255,255,255,.04); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; cursor: pointer; transition: 0.15s; }
    .svs-result:hover { background: rgba(56, 189, 248, 0.08); border-color: rgba(56, 189, 248, 0.35); }
    .svs-result small { display: block; color: var(--muted); margin-top: 4px; font-size: 11px; }
    #svsStatus { min-height: 20px; color: #7dd3fc; font-size: 12px; margin: 8px 0; }
    #svsProgress { width: 100%; height: 5px; accent-color: var(--accent); }
    #svsStickyBar {
      position: sticky; bottom: -18px; margin: 12px -18px -18px -18px; padding: 12px 18px;
      background: rgba(8, 12, 20, 0.98); border-top: 1px solid var(--border);
      backdrop-filter: blur(14px); display: flex; gap: 10px; align-items: center; justify-content: space-between; z-index: 5;
    }

    /* Mobile Responsive Full-screen */
    @media (max-width: 768px) {
      #svsCatalog {
        top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important;
        width: 100vw !important; max-height: 100vh !important; border-radius: 0 !important;
        padding: 16px !important; z-index: 50 !important;
      }
      #leftPanel {
        top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important;
        width: 100vw !important; max-height: 100vh !important; border-radius: 0 !important;
        padding: 16px !important; transform: none !important; z-index: 50 !important;
      }
    }
  </style>
</head>
<body>

  <div id="globeViz"></div>

  <div class="watermark" onclick="resetGlobe()" title="Reset Globe View">
    <div class="wm-mark">SE</div>
    <div class="wm-title">THESOUND.EARTH</div>
  </div>

  <div class="vis-switch">
    <button class="active" id="visOsc" onclick="setVisualMode('oscar')">OSCAR Flow</button>
    <button id="visSvs" onclick="setVisualMode('svs')">SVS 3912</button>
    <button id="btnToggleLeft" class="active" onclick="toggleLeftPanel()">Soundscapes &amp; Evidence</button>
    <button class="catalog-trigger" id="openSvsCatalog" type="button">NASA SVS</button>
  </div>

  <!-- Minimized Floating Pill -->
  <div id="minimizedPill" onclick="restoreLeftPanel()">
    <span>▶ Soundscapes &amp; Evidence</span>
  </div>

  <!-- UNIFIED LEFT PANEL (Requirement 6) -->
  <aside id="leftPanel" class="open" aria-label="Gulf Stream Soundscapes and Evidence">
    <div class="panel-top-bar">
      <div>
        <div class="panel-title">THESOUND.EARTH</div>
        <div class="panel-sub">Gulf Stream Sonification &amp; Evidence</div>
      </div>
      <div class="panel-window-controls">
        <button class="p-win-btn" id="btnMaxPanel" onclick="toggleMaximizePanel()" title="Maximize to 50% width / Restore">⛶</button>
        <button class="p-win-btn" onclick="minimizeLeftPanel()" title="Minimize to pill">–</button>
        <button class="p-win-btn" onclick="closeLeftPanel()" title="Close">✕</button>
      </div>
    </div>

    <!-- Panel Navigation Tabs -->
    <div class="panel-tabs">
      <button class="panel-tab-btn active" onclick="switchPanelView('viewTracks')">Tracks</button>
      <button class="panel-tab-btn" onclick="switchPanelView('viewAudit')">Data to Bar</button>
      <button class="panel-tab-btn" onclick="switchPanelView('viewRules')">Mapping Rules</button>
      <button class="panel-tab-btn" onclick="switchPanelView('viewLimits')">Honest Limits</button>
      <button class="panel-tab-btn" onclick="switchPanelView('viewSources')">Sources &amp; Credits</button>
    </div>

    <!-- Tab 1: Tracks List -->
    <div class="panel-view active" id="viewTracks">
      <div class="rule-note">
        Every note is computed from the data by rules we chose. FluidSynth pre-rendered audio.
      </div>
      <div class="track-list" id="trackListContainer"></div>
    </div>

    <!-- Tab 2: From Data to Bar Audit Table -->
    <div class="panel-view" id="viewAudit">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:11px; color:var(--muted);">Current playing bar is highlighted live.</span>
        <select id="auditTrackSelect" onchange="loadAuditForSelectedTrack()" style="background:#111a26; color:#f4f4f5; border:1px solid var(--border); border-radius:6px; padding:4px 8px; font-size:11px;">
          <option value="2025">2025 Full Year (Gm, 53 bars)</option>
          <option value="2025-01">2025-01 Month (Em, 31 bars)</option>
          <option value="2026-01">2026-01 Month (F#m, 16 bars)</option>
          <option value="2024">2024 Full Year (F#m, 53 bars)</option>
          <option value="2023">2023 Full Year (Abm, 53 bars)</option>
        </select>
      </div>

      <div class="table-container" id="auditTableContainer">
        <table class="audit-table">
          <thead>
            <tr>
              <th>Bar</th>
              <th>Dates</th>
              <th>Days</th>
              <th>p95 Spd</th>
              <th>Norm</th>
              <th>Sector</th>
              <th>Ageo Mag</th>
              <th>Held?</th>
              <th>Chord</th>
              <th>Drums</th>
              <th>Melody</th>
              <th>Vel</th>
            </tr>
          </thead>
          <tbody id="auditTableBody"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 3: How Data Becomes Sound Mapping Rules -->
    <div class="panel-view" id="viewRules">
      <div style="font-size:12px; font-weight:600; color:#fff; margin-bottom:4px;">How Data Becomes Sound</div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">Deterministic mapping from physical ocean parameters to acoustic structures</div>
      <table class="spec-table">
        <thead>
          <tr>
            <th>Physical Feature</th>
            <th>Scientific Parameter</th>
            <th>Acoustic Rule</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Period Mean Speed</strong></td>
            <td>Mean 95th-percentile surface speed over period</td>
            <td><strong>Key transposition</strong> <code>k = round(6 * (mean_speed - lo) / (hi - lo))</code> semitones above D. Clamped 0..6. Last bar resolves to tonic minor.</td>
          </tr>
          <tr>
            <td><strong>Ageostrophic Flow</strong></td>
            <td>Non-geostrophic wind-driven flow vector decomposed into 4 quadrants</td>
            <td><strong>Harmonic chord progression</strong>: North (i), East (VI), South (iv), West (VII). Peak section introduces III lift; Calm section introduces v.</td>
          </tr>
          <tr>
            <td><strong>Ageostrophic Magnitude</strong></td>
            <td>Current shear energy threshold (&lt; 0.013 m/s)</td>
            <td><strong>Harmonic Hold</strong>: When energy drops below threshold, previous chord is sustained to prevent artificial churn during slack water.</td>
          </tr>
          <tr>
            <td><strong>Block Speed (p95)</strong></td>
            <td>Current speed normalized over bounds [0, 1]</td>
            <td><strong>Dynamics &amp; Drums</strong>: Velocity scaling (0.65..1.05) and drum groove tier switching (Low &lt; 0.35, Mid 0.35..0.70, High &gt; 0.70).</td>
          </tr>
          <tr>
            <td><strong>Calendar Block</strong></td>
            <td>7-day aggregated blocks (yearly) or 1-day increments (monthly)</td>
            <td><strong>1 block = 1 musical bar</strong> at 72 BPM (4 beats per bar, 3.333s per block).</td>
          </tr>
          <tr>
            <td><strong>Period SHA-256 Hash</strong></td>
            <td>Digest of period label ("2025" or "2025-01")</td>
            <td><strong>Melodic Seed</strong>: Deterministic melody contour. Beats 1 and 3 remain strict chord tones.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Tab 4: Honest Limits -->
    <div class="panel-view" id="viewLimits">
      <div style="font-size:12px; font-weight:600; color:#fff; margin-bottom:4px;">Honest Limits &amp; Boundaries</div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">Explicit scientific boundaries and deliberate modeling choices</div>

      <div class="limits-box">
        <strong>"Every note is computed from the data by rules we chose."</strong>
        <ul class="limits-list">
          <li><strong>Data Encoding, Not Underwater Audio:</strong> This music sonifies numerical physical values derived from satellite data. It is not an audio recording of ocean waves, underwater hydrophones, or marine life.</li>
          <li><strong>Gulf Stream Bounding Box Only:</strong> The sonification pipeline is calibrated exclusively for the North Atlantic Gulf Stream region (lat 30°-40°N, lon 280°-300°E / 60°-80°W). Clicking outside this box reports that no soundscape is built yet.</li>
          <li><strong>2026 Temporal Coverage:</strong> Satellite ocean current data for 2026 ends on 16 Jan. Subsequent periods are awaiting satellite processing and calibration.</li>
          <li><strong>Excluded Earth Domains:</strong> Terrestrial vegetation, atmospheric CO2 concentrations, and meteorological wind speeds are not coupled into this sonification engine.</li>
        </ul>
      </div>
    </div>

    <!-- Tab 5: Sources & AI Credits -->
    <div class="panel-view" id="viewSources">
      <div style="font-size:12px; font-weight:600; color:#fff; margin-bottom:4px;">Data Sources &amp; AI Credits</div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">Provenance, data providers, and system attributions</div>
      <div style="font-size:11.5px; line-height:1.55; color:#cbd5e1; display:flex; flex-direction:column; gap:10px;">
        <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
          <strong style="color:#fff;">NASA PO.DAAC OSCAR Data</strong><br />
          Ocean Surface Current Analysis Real-time (OSCAR_L4_OC_FINAL_V2.0), 0.25° daily resolution. Derived from satellite altimetry and scatterometry.<br />
          DOI: <a href="https://doi.org/10.5067/OSCAR-25F20" target="_blank" rel="noopener" style="color:var(--accent);">10.5067/OSCAR-25F20</a>
        </div>
        <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
          <strong style="color:#fff;">NASA Goddard Scientific Visualization Studio (SVS)</strong><br />
          SVS 3912 ("Perpetual Ocean", ECCO2 surface current flow model by Horace Mitchell). NASA Earth Information Center (EIC) integration.
        </div>
        <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
          <strong style="color:#fff;">AI Use &amp; Audio Credits</strong><br />
          - Algorithmic sonification architecture and rule engine designed with Antigravity AI.<br />
          - Oceanographic context and briefings supported by Google Gemini API.<br />
          - Audio rendering powered by FluidSynth with the open-source FluidR3_GM SoundFont.
        </div>
      </div>
    </div>
  </aside>

  <!-- NASA SVS Search UX (STEP 3 & 5) -->
  <section id="svsCatalog" aria-labelledby="svsHeading">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
      <h2 id="svsHeading" style="margin:0;">NASA Earth Information Center (SVS)</h2>
      <button class="drawer-close" onclick="toggleSvsCatalog()">✕</button>
    </div>

    <!-- Pinned Selection at Top -->
    <div id="svsPinnedSelection">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <h3 id="pinnedTitle">Selected Visualization</h3>
        <span id="pinnedBadge" style="font-size:10px; color:var(--accent); font-family:ui-monospace, monospace;">ID —</span>
      </div>
      <div id="pinnedMedia"></div>
      <p id="pinnedDesc"></p>
      <div id="pinnedMeta" style="font-size:11px; color:var(--muted); font-family:ui-monospace, monospace;"></div>
    </div>

    <div class="svs-row">
      <input id="svsSearch" type="search" aria-label="Search NASA SVS visualizations" placeholder="Search ocean, currents, atmosphere..." />
      <button class="svs-button" id="svsSearchButton">Search</button>
    </div>
    <label style="font-size:12px; color:var(--muted);"><input type="checkbox" id="svsEicOnly" checked /> Prioritize Earth Information Center (EIC) visualizations</label>

    <div id="svsResults" aria-live="polite"></div>

    <div class="svs-row" style="justify-content:space-between;">
      <button class="svs-button" id="svsPrevious" disabled>Previous</button>
      <button class="svs-button" id="svsNext" disabled>Next</button>
    </div>

    <div id="svsStatus" role="status" aria-live="polite"></div>
    <progress id="svsProgress" max="1" value="0" aria-label="NASA frame processing progress"></progress>

    <!-- Sticky Play/Pair Bottom Bar -->
    <div id="svsStickyBar">
      <div style="display:flex; align-items:center; gap:8px;">
        <label style="font-size:11.5px; color:var(--muted);">Sample every
          <select id="svsSampleEvery" aria-label="Frame sampling frequency" style="padding:4px 6px; font-size:11px;">
            <option value="1">1 frame</option>
            <option value="4" selected>4 frames</option>
            <option value="10">10 frames</option>
            <option value="30">30 frames</option>
          </select>
        </label>
      </div>
      <div style="display:flex; gap:8px;">
        <button class="svs-button" id="svsPairButton" onclick="pairSelectedSvsWithSoundscape()">Pair with Visual</button>
        <button class="svs-button primary" id="svsGenerate" disabled>Generate Sound</button>
        <button class="svs-button" id="svsCancel" hidden>Cancel</button>
      </div>
    </div>
  </section>

  <div class="ocean-card" id="oceanCard">
    <div class="oc-header">
      <div>
        <div class="oc-name" id="ocName">Ocean Region</div>
        <div class="oc-sub" id="ocCoords">0.00°, 0.00°</div>
      </div>
      <button class="oc-close" onclick="document.getElementById('oceanCard').classList.remove('open')">✕</button>
    </div>
    <div class="oc-grid">
      <div class="oc-stat"><div class="lbl">Speed / Flux</div><div class="val" id="ocSpeed">—</div></div>
      <div class="oc-stat"><div class="lbl">Dir / Bearing</div><div class="val" id="ocAngle">—</div></div>
      <div class="oc-stat"><div class="lbl">u (East)</div><div class="val" id="ocU">—</div></div>
      <div class="oc-stat"><div class="lbl">v (North)</div><div class="val" id="ocV">—</div></div>
    </div>
    <div class="oc-note" id="ocNote"></div>
    <div class="oc-brief" id="ocBrief"></div>
  </div>

  <aside class="live-boxes open" id="liveBoxes">
    <div class="viz-box">
      <div class="viz-head"><span>Global Speed &amp; Local Flow</span><span id="lblFlow">Flow</span></div>
      <canvas id="cFlow" width="276" height="82"></canvas>
    </div>
    <div class="viz-box">
      <div class="viz-head"><span>Velocity (u / v / speed)</span><span id="lblVel">m/s</span></div>
      <canvas id="cVel" width="276" height="82"></canvas>
    </div>
    <div class="viz-box">
      <div class="viz-head"><span>Audio Spectrum</span><span id="lblAudio">Active</span></div>
      <canvas id="cAudio" width="276" height="82"></canvas>
    </div>
  </aside>

  <footer class="bottom-dock" id="bottomDock">
    <!-- Year Selector above Slider (Requirement 3) -->
    <div class="tl-year-bar">
      <span class="tl-year-lbl">DATASET YEAR</span>
      <div class="tl-year-buttons" id="yearBtnGroup">
        <button class="tl-year-btn" onclick="selectTimelineYear('2021')">2021</button>
        <button class="tl-year-btn" onclick="selectTimelineYear('2022')">2022</button>
        <button class="tl-year-btn" onclick="selectTimelineYear('2023')">2023</button>
        <button class="tl-year-btn" onclick="selectTimelineYear('2024')">2024</button>
        <button class="tl-year-btn active" onclick="selectTimelineYear('2025')">2025</button>
        <button class="tl-year-btn" onclick="selectTimelineYear('2026')">2026</button>
      </div>
    </div>

    <div class="timeline-wrap" id="timelineWrap" title="Drag or scroll mouse wheel to scrub through the year">
      <div class="tl-date" id="tlDate">2025-01-01</div>
      <div class="tl-track">
        <input type="range" min="0" max="364" value="0" class="tl-slider" id="yearSlider" />
        <div class="tl-months">
          <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span>
          <span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:8px; min-width:130px;">
        <span class="tl-date" id="tlHour" style="min-width:48px;">12:00</span>
        <input type="range" min="0" max="23" value="12" class="tl-slider" id="hourSlider" style="width:70px;" />
      </div>
    </div>

    <div class="transport-row">
      <div class="timer" id="timer">00:00 <span>/ 00:00</span></div>
      <div class="track-name" id="trackLabel">Click inside the Gulf Stream box (30-40°N, 60-80°W) on the globe</div>

      <div class="controls">
        <button class="ctrl-btn" onclick="seek(-3)"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/></svg></button>
        <button class="ctrl-btn" onclick="seek(3)"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg></button>
        <button class="ctrl-btn" onclick="restartAudio()"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg></button>
        <button class="ctrl-btn" id="playPauseBtn" onclick="togglePlay()"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></button>
        <button class="ctrl-btn" onclick="stopAudio()"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg></button>
        <button class="ctrl-btn" id="loopBtn" onclick="toggleLoop()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 2l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg></button>
      </div>

      <div class="right-tools">
        <button class="ctrl-btn" onclick="downloadFile('json')" title="Download Audit JSON"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>
        <button class="ctrl-btn" onclick="downloadFile('wav')" title="Download Audio"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></button>
        <div class="ab-toggle">
          <button class="active" id="btnA" onclick="switchMode('musical')">A</button>
          <button id="btnB" onclick="switchMode('diagnostic')">B</button>
        </div>
      </div>
    </div>
  </footer>

  <audio id="audioEl" crossorigin="anonymous"></audio>
  <video id="svsVideo" src="/svs_video" loop muted playsinline crossorigin="anonymous" style="display:none;"></video>

  <script type="module">
    import * as THREE from 'https://esm.sh/three@0.170.0';
    import { OrbitControls } from 'https://esm.sh/three@0.170.0/examples/jsm/controls/OrbitControls.js';

    let selectedDoy = 0, selectedHour = 12, currentVisualMode = 'oscar';
    let currentMode = 'musical', lastCoords = null;
    let gridSnapshot = [], availableDates = [];
    let liveU = 0.2, liveV = 0.1, liveSpeed = 0.22;

    let soundscapeTracks = [];
    let currentTrackId = '2025';
    let currentAuditData = [];
    let isPanelMaximized = false;

    // Daily Oscar Records (Requirement 3 & 4)
    let selectedYear = '2025';
    let dailyRecords = [];

    // SVS Catalog Variables
    let svsOffset = 0, svsCount = 0, selectedSvs = null, svsJob = null, svsPoll = null;

    const container = document.getElementById('globeViz');
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.set(0, 0.5, 2.7);

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 1.25;
    controls.maxDistance = 5.0;

    function getSunDir(doy, hourUtc) {
      const decl = -23.44 * Math.cos((2 * Math.PI / 365) * (doy + 10)) * (Math.PI / 180);
      const lon = (12 - hourUtc) * 15 * (Math.PI / 180);
      return new THREE.Vector3(Math.cos(decl) * Math.sin(lon), Math.sin(decl), Math.cos(decl) * Math.cos(lon)).normalize();
    }
    function getSeasonFactor(doy) { return -Math.cos((2 * Math.PI / 365) * (doy + 10)); }

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin('anonymous');
    const dayTex = loader.load('https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-blue-marble.jpg');
    const nightTex = loader.load('https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-night.jpg');

    const earthMat = new THREE.ShaderMaterial({
      uniforms: { dayTex: { value: dayTex }, nightTex: { value: nightTex }, sunDir: { value: getSunDir(0, 12) }, season: { value: getSeasonFactor(0) } },
      vertexShader: `varying vec2 vUv; varying vec3 vNorm; varying vec3 vViewDir; varying float vLat;
        void main(){ vUv=uv; vLat=position.y; vec4 wp=modelMatrix*vec4(position,1.0); vNorm=normalize(mat3(modelMatrix)*normal); vViewDir=normalize(cameraPosition-wp.xyz); gl_Position=projectionMatrix*viewMatrix*wp; }`,
      fragmentShader: `uniform sampler2D dayTex; uniform sampler2D nightTex; uniform vec3 sunDir; uniform float season; varying vec2 vUv; varying vec3 vNorm; varying vec3 vViewDir; varying float vLat;
        void main(){ vec3 N=normalize(vNorm); float sunDot=dot(N,normalize(sunDir)); float dayMix=smoothstep(-0.18,0.22,sunDot);
          vec3 dayCol=texture2D(dayTex,vUv).rgb; float isLand=smoothstep(0.02,0.14,dayCol.r+dayCol.g-dayCol.b*1.1);
          float snowMask=isLand*clamp(clamp(-season,0.0,1.0)*smoothstep(0.55,0.88,vLat)+clamp(season,0.0,1.0)*smoothstep(-0.55,-0.88,vLat),0.0,0.85);
          dayCol=mix(dayCol,vec3(0.88,0.93,0.98),snowMask); vec3 nightCol=texture2D(nightTex,vUv).rgb*1.25;
          float fresnel=pow(1.0-max(dot(N,normalize(vViewDir)),0.0),3.2);
          gl_FragColor=vec4(mix(nightCol,dayCol,dayMix)+vec3(0.28,0.62,1.0)*fresnel*(0.25+0.75*dayMix),1.0); }`
    });
    const earthMesh = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 64), earthMat);
    scene.add(earthMesh);

    // Gulf Stream 3D Bounding Box (30°-40°N, 60°-80°W)
    function latLonToVec3(lat, lon, r = 1.003) {
      const phi = (90 - lat) * (Math.PI / 180);
      const theta = (lon + 180) * (Math.PI / 180);
      return new THREE.Vector3(
        -r * Math.sin(phi) * Math.cos(theta),
        r * Math.cos(phi),
        r * Math.sin(phi) * Math.sin(theta)
      );
    }
    const gulfPts = [];
    for (let lon = -80; lon <= -60; lon += 1) gulfPts.push(latLonToVec3(30, lon));
    for (let lat = 30; lat <= 40; lat += 0.5) gulfPts.push(latLonToVec3(lat, -60));
    for (let lon = -60; lon >= -80; lon -= 1) gulfPts.push(latLonToVec3(40, lon));
    for (let lat = 40; lat >= 30; lat -= 0.5) gulfPts.push(latLonToVec3(lat, -80));
    const gulfBoxGeo = new THREE.BufferGeometry().setFromPoints(gulfPts);
    const gulfBoxMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.85 });
    const gulfBoxMesh = new THREE.LineLoop(gulfBoxGeo, gulfBoxMat);
    scene.add(gulfBoxMesh);

    const NUM_STREAMS = 2400, TOTAL_VERTS = NUM_STREAMS * 18;
    const lineGeo = new THREE.BufferGeometry();
    const posArr = new Float32Array(TOTAL_VERTS * 3), fadeArr = new Float32Array(TOTAL_VERTS), spdArr = new Float32Array(TOTAL_VERTS);
    lineGeo.setAttribute('position', new THREE.BufferAttribute(posArr, 3));
    lineGeo.setAttribute('aFade', new THREE.BufferAttribute(fadeArr, 1));
    lineGeo.setAttribute('aSpeed', new THREE.BufferAttribute(spdArr, 1));
    const lineMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `attribute float aFade; attribute float aSpeed; varying float vFade; varying float vSpeed; varying float vVisible;
        void main(){ vFade=aFade; vSpeed=aSpeed; vec3 wp=(modelMatrix*vec4(position,1.0)).xyz; vVisible=step(-0.05,dot(normalize(wp),normalize(cameraPosition))); gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `varying float vFade; varying float vSpeed; varying float vVisible;
        void main(){ if(vVisible<0.5) discard; gl_FragColor=vec4(mix(vec3(0.32,0.78,1.0),vec3(1.0),clamp(vSpeed*1.15,0.0,1.0)), vFade*(0.35+clamp(vSpeed*0.65,0.0,0.65))); }`
    });
    const streamMesh = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(streamMesh);

    const svsVideo = document.getElementById('svsVideo');
    const svsTex = new THREE.VideoTexture(svsVideo); svsTex.colorSpace = THREE.SRGBColorSpace;
    const svsMat = new THREE.MeshBasicMaterial({ map: svsTex });

    function setVisualMode(vis) {
      currentVisualMode = vis;
      document.getElementById('visOsc').classList.toggle('active', vis === 'oscar');
      document.getElementById('visSvs').classList.toggle('active', vis === 'svs');
      if (vis === 'svs') { earthMesh.material = svsMat; streamMesh.visible = false; svsVideo.play().catch(() => {}); }
      else { earthMesh.material = earthMat; streamMesh.visible = true; svsVideo.pause(); }
    }

    const worker = new Worker('/flow.worker.js');
    worker.onmessage = (e) => {
      const buf = e.data;
      for (let i = 0; i < TOTAL_VERTS; i++) {
        posArr[i*3] = buf[i*5]; posArr[i*3+1] = buf[i*5+1]; posArr[i*3+2] = buf[i*5+2];
        fadeArr[i] = buf[i*5+3]; spdArr[i] = buf[i*5+4];
      }
      lineGeo.attributes.position.needsUpdate = true;
      lineGeo.attributes.aFade.needsUpdate = true;
      lineGeo.attributes.aSpeed.needsUpdate = true;
    };

    function loadGridDay(dayIdx = 0) {
      fetch(`/api/grid?step=4&day_idx=${dayIdx}`).then(r => r.json()).then(d => {
        availableDates = d.dates || [];
        gridSnapshot = d.points || [];
        worker.postMessage({ type: 'init', points: gridSnapshot.filter(p => p.speed > 0.05) });
      }).catch(() => {});
    }
    loadGridDay(0);

    // ==========================================
    // REQUIREMENT 3 & 4: DRIVE TIMELINE & UV GRAPH FROM oscar_YEAR_daily.json
    // ==========================================
    const yearSlider = document.getElementById('yearSlider'), hourSlider = document.getElementById('hourSlider');
    const tlDate = document.getElementById('tlDate'), tlHour = document.getElementById('tlHour');

    async function loadYearDaily(year) {
      try {
        let res = await fetch(`/api/oscar_daily/${year}`);
        if (!res.ok) {
          res = await fetch(`/data/raw_oscar/oscar_${year}_daily.json`);
        }
        dailyRecords = await res.json();
        yearSlider.max = Math.max(0, dailyRecords.length - 1);
        if (selectedDoy > yearSlider.max) selectedDoy = 0;
        yearSlider.value = selectedDoy;
        syncGlobeTime();
        drawVelocityBoxFromDaily();
      } catch (err) {
        console.error('Failed to load daily dataset for year', year, err);
      }
    }

    function selectTimelineYear(year) {
      selectedYear = year;
      document.querySelectorAll('.tl-year-btn').forEach(btn => {
        btn.classList.toggle('active', btn.textContent.trim() === String(year));
      });
      loadYearDaily(year);
    }

    function syncGlobeTime() {
      if (dailyRecords && dailyRecords[selectedDoy]) {
        tlDate.textContent = dailyRecords[selectedDoy].date;
      }
      tlHour.textContent = `${String(selectedHour).padStart(2, '0')}:00`;
      earthMat.uniforms.sunDir.value.copy(getSunDir(selectedDoy, selectedHour));
      earthMat.uniforms.season.value = getSeasonFactor(selectedDoy);
    }

    function onTimelineChange() {
      syncGlobeTime();
      drawVelocityBoxFromDaily();
      loadGridDay(availableDates.length ? (selectedDoy % availableDates.length) : 0);
    }
    yearSlider.addEventListener('input', e => { selectedDoy = Number(e.target.value); onTimelineChange(); });
    hourSlider.addEventListener('input', e => { selectedHour = Number(e.target.value); syncGlobeTime(); });
    document.getElementById('timelineWrap').addEventListener('wheel', e => {
      e.preventDefault();
      selectedDoy = Math.max(0, Math.min(Number(yearSlider.max), selectedDoy + (e.deltaY > 0 ? 3 : -3)));
      yearSlider.value = selectedDoy; onTimelineChange();
    }, { passive: false });

    // Initial load for 2025 daily data
    loadYearDaily('2025');

    // ==========================================
    // REQUIREMENT 4: UV GRAPH PLOT FROM oscar_YEAR_daily.json
    // ==========================================
    function drawVelocityBoxFromDaily() {
      const ctx = document.getElementById('cVel').getContext('2d');
      ctx.clearRect(0, 0, 276, 82);
      ctx.strokeStyle = 'rgba(255,255,255,0.08)';
      ctx.beginPath(); ctx.moveTo(0, 41); ctx.lineTo(276, 41); ctx.stroke();
      if (!dailyRecords || !dailyRecords.length) return;

      const n = dailyRecords.length;
      const drawLine = (prop, col, scale = 23, offset = 41) => {
        ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.beginPath();
        for (let i = 0; i < n; i++) {
          const val = dailyRecords[i][prop] ?? 0;
          const x = n === 1 ? 138 : (i / (n - 1)) * 260 + 8;
          const y = offset - Math.max(-1.5, Math.min(1.5, val)) * scale;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.stroke();
      };

      drawLine('core_u', '#34d399');    // u (eastward) in emerald
      drawLine('core_v', '#fbbf24');    // v (northward) in amber
      drawLine('speed_p95', '#38bdf8');  // speed_p95 in sky blue

      // Active day cursor
      if (selectedDoy >= 0 && n > 1) {
        const ax = (selectedDoy / (n - 1)) * 260 + 8;
        ctx.strokeStyle = 'rgba(255,255,255,0.65)'; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(ax, 4); ctx.lineTo(ax, 78); ctx.stroke();
      }

      // Update Header & Ocean Card Stats from current day record
      const curr = dailyRecords[selectedDoy] || dailyRecords[0];
      if (curr) {
        const spd = (curr.speed_p95 || curr.speed_mean || 0).toFixed(3);
        const uVal = (curr.core_u || curr.u_mean || 0).toFixed(3);
        const vVal = (curr.core_v || curr.v_mean || 0).toFixed(3);
        document.getElementById('lblVel').textContent = `${spd} m/s`;
        liveU = parseFloat(uVal); liveV = parseFloat(vVal); liveSpeed = parseFloat(spd);
        if (document.getElementById('oceanCard').classList.contains('open')) {
          document.getElementById('ocSpeed').textContent = `${spd} m/s`;
          document.getElementById('ocU').textContent = `${uVal} m/s`;
          document.getElementById('ocV').textContent = `${vVal} m/s`;
          document.getElementById('ocAngle').textContent = `${(curr.core_angle_deg || 0).toFixed(1)}°`;
        }
      }
    }

    const ringMesh = new THREE.Mesh(new THREE.RingGeometry(0.015, 0.024, 32), new THREE.MeshBasicMaterial({ color: 0x38bdf8, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
    ringMesh.visible = false; scene.add(ringMesh);
    let targetCamPos = null;
    function zoomToPoint(hitVec) {
      targetCamPos = hitVec.clone().normalize().multiplyScalar(1.65);
      ringMesh.position.copy(hitVec.clone().normalize().multiplyScalar(1.006));
      ringMesh.lookAt(hitVec.clone().multiplyScalar(2)); ringMesh.visible = true;
    }

    const raycaster = new THREE.Raycaster(), mouse = new THREE.Vector2();
    let downPos = { x: 0, y: 0 };
    renderer.domElement.addEventListener('pointerdown', e => { downPos = { x: e.clientX, y: e.clientY }; });
    renderer.domElement.addEventListener('pointerup', e => {
      if (Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObject(earthMesh);
      if (!hits.length) return;
      const p = hits[0].point;
      const lat = Math.asin(p.y) * (180 / Math.PI);
      const lng = ((Math.atan2(p.z, -p.x) * (180 / Math.PI) - 180) + 540) % 360 - 180;
      zoomToPoint(p);
      handleGlobeClick(lat, lng);
    });

    const fCtx = document.getElementById('cFlow').getContext('2d');
    const flowPts = Array.from({ length: 65 }, () => ({ x: Math.random() * 276, y: Math.random() * 82 }));

    function speedToColor(spd) {
      const t = Math.min(1, spd / 1.4);
      if (t < 0.5) {
        const k = t * 2;
        return `rgb(${Math.round(45 - 15 * k)}, ${Math.round(25 + 140 * k)}, ${Math.round(95 + 65 * k)})`;
      }
      const k = (t - 0.5) * 2;
      return `rgb(${Math.round(30 + 220 * k)}, ${Math.round(165 + 65 * k)}, ${Math.round(160 - 125 * k)})`;
    }

    function drawFlowBox() {
      fCtx.fillStyle = '#060a12';
      fCtx.fillRect(0, 0, 276, 82);

      for (let i = 0; i < gridSnapshot.length; i += 2) {
        const p = gridSnapshot[i];
        const x = ((p.lng + 180) / 360) * 276;
        const y = ((90 - p.lat) / 180) * 82;
        fCtx.fillStyle = speedToColor(p.speed);
        fCtx.fillRect(x, y, 2.2, 2.2);
      }

      fCtx.strokeStyle = 'rgba(255, 255, 255, 0.75)';
      fCtx.lineWidth = 1.2;
      const vx = liveU * 4.0, vy = -liveV * 4.0;
      for (const pt of flowPts) {
        const ox = pt.x, oy = pt.y;
        pt.x = (pt.x + vx + 276) % 276;
        pt.y = (pt.y + vy + 82) % 82;
        if (Math.abs(pt.x - ox) < 20 && Math.abs(pt.y - oy) < 20) {
          fCtx.beginPath(); fCtx.moveTo(ox, oy); fCtx.lineTo(pt.x, pt.y); fCtx.stroke();
        }
      }

      if (lastCoords) {
        const tx = ((lastCoords.lng + 180) / 360) * 276;
        const ty = ((90 - lastCoords.lat) / 180) * 82;
        fCtx.fillStyle = '#38bdf8';
        fCtx.beginPath(); fCtx.arc(tx, ty, 3.8, 0, Math.PI * 2); fCtx.fill();
        fCtx.strokeStyle = '#ffffff'; fCtx.lineWidth = 1.2; fCtx.stroke();
      }
    }

    const audio = document.getElementById('audioEl');
    let audioCtx, analyser, freqBuf, timeBuf;
    function initWebAudio() {
      if (audioCtx) return;
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser(); analyser.fftSize = 128;
        const src = audioCtx.createMediaElementSource(audio);
        src.connect(analyser); analyser.connect(audioCtx.destination);
        freqBuf = new Uint8Array(analyser.frequencyBinCount);
        timeBuf = new Uint8Array(analyser.fftSize);
      } catch (e) {}
    }

    function drawAudioBox() {
      const ctx = document.getElementById('cAudio').getContext('2d');
      ctx.fillStyle = '#04070d'; ctx.fillRect(0, 0, 276, 82);
      if (!analyser || !freqBuf) return;
      analyser.getByteFrequencyData(freqBuf);
      analyser.getByteTimeDomainData(timeBuf);

      const bw = 276 / freqBuf.length;
      for (let i = 0; i < freqBuf.length; i++) {
        const h = (freqBuf[i] / 255) * 65;
        ctx.fillStyle = 'rgba(56, 189, 248, 0.38)';
        ctx.fillRect(i * bw, 82 - h, bw - 1, h);
      }
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 1.4; ctx.beginPath();
      for (let i = 0; i < timeBuf.length; i++) {
        const x = (i / timeBuf.length) * 276;
        const y = (timeBuf[i] / 255) * 82;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    function animate() {
      requestAnimationFrame(animate);
      if (targetCamPos) { camera.position.lerp(targetCamPos, 0.06); if (camera.position.distanceTo(targetCamPos) < 0.02) targetCamPos = null; }
      if (ringMesh.visible) { const s = 1 + 0.35 * Math.sin(performance.now() * 0.008); ringMesh.scale.set(s, s, 1); }
      drawFlowBox();
      drawAudioBox();
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    function updateGlobeViewport(isMax) {
      const w = isMax ? window.innerWidth * 0.5 : window.innerWidth;
      const h = window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }

    window.addEventListener('resize', () => {
      updateGlobeViewport(isPanelMaximized);
    });

    function identifyOcean(lat, lon) {
      if (lat >= 66.5) return { name: 'Arctic Ocean', note: 'Polar basin with sea-ice-modulated surface circulation.' };
      if (lat <= -60.0) return { name: 'Southern Ocean', note: 'Home to the Antarctic Circumpolar Current, Earth’s strongest unbroken flow.' };
      if (lat >= 5 && lat <= 26 && lon >= 50 && lon <= 78) return { name: 'Arabian Sea', note: 'Monsoon-reversing currents driven by seasonal Indian Ocean winds.' };
      if (lat >= 24 && lat <= 45 && lon >= -82 && lon <= -40) return { name: 'North Atlantic (Gulf Stream)', note: 'Fast western boundary current transporting warm tropical water northward.' };
      if (lat >= -60 && lat <= 30 && lon >= 20 && lon <= 120) return { name: 'Indian Ocean', note: 'Subtropical gyre and equatorial counter-current dynamics.' };
      if (lon > -70 && lon < 20) return { name: lat >= 0 ? 'North Atlantic Ocean' : 'South Atlantic Ocean', note: 'Basin-scale wind-driven gyre and meridional overturning flow.' };
      return { name: lat >= 0 ? 'North Pacific Ocean' : 'South Pacific Ocean', note: 'Largest oceanic basin with strong equatorial and Kuroshio/Humboldt currents.' };
    }

    function fmt(sec) { const s = Math.floor(sec || 0); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }

    function getSectionCaption(barIdx, totalBars) {
      if (totalBars === 53) {
        if (barIdx < 8) return 'Intro (Bars 1-8)';
        if (barIdx < 20) return 'Build (Bars 9-20)';
        if (barIdx < 36) return 'Peak (Bars 21-36)';
        if (barIdx < 48) return 'Calm (Bars 37-48)';
        return 'Outro (Bars 49-53)';
      }
      if (totalBars === 31) {
        if (barIdx < 4) return 'Intro (Bars 1-4)';
        if (barIdx < 12) return 'Build (Bars 5-12)';
        if (barIdx < 20) return 'Peak (Bars 13-20)';
        if (barIdx < 28) return 'Calm (Bars 21-28)';
        return 'Outro (Bars 29-31)';
      }
      if (totalBars === 16) {
        if (barIdx < 2) return 'Intro (Bars 1-2)';
        if (barIdx < 6) return 'Build (Bars 3-6)';
        if (barIdx < 11) return 'Peak (Bars 7-11)';
        if (barIdx < 14) return 'Calm (Bars 12-14)';
        return 'Outro (Bars 15-16)';
      }
      const ratio = (barIdx + 1) / (totalBars || 53);
      if (ratio <= 0.15) return 'Intro';
      if (ratio <= 0.38) return 'Build';
      if (ratio <= 0.68) return 'Peak';
      if (ratio <= 0.90) return 'Calm';
      return 'Outro';
    }

    // Time update listener: Updates timer, active section, and audit table row
    audio.addEventListener('timeupdate', () => {
      document.getElementById('timer').innerHTML = `${fmt(audio.currentTime)} <span>/ ${fmt(audio.duration || 176)}</span>`;
      const currentTrack = soundscapeTracks.find(t => t.id === currentTrackId);
      const totalBars = currentTrack ? currentTrack.bars : 53;
      const currentBar = Math.floor(audio.currentTime / (4 * 60 / 72)); // 3.333s per bar at 72 BPM

      // Update Section badge in Tracks View
      const secBadge = document.getElementById(`secBadge-${currentTrackId}`);
      if (secBadge) {
        secBadge.textContent = getSectionCaption(currentBar, totalBars);
      }

      // Highlight active row in From Data to Bar table
      const rows = document.querySelectorAll('#auditTableBody tr');
      rows.forEach(r => {
        const b = parseInt(r.getAttribute('data-bar'), 10);
        if (b === currentBar) {
          if (!r.classList.contains('active-bar')) {
            r.classList.add('active-bar');
            r.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        } else {
          r.classList.remove('active-bar');
        }
      });
    });

    audio.addEventListener('play', () => { document.getElementById('playPauseBtn').innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>'; });
    audio.addEventListener('pause', () => { document.getElementById('playPauseBtn').innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'; });

    function togglePlay() {
      initWebAudio();
      if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
      audio.paused ? audio.play() : audio.pause();
    }
    function stopAudio() { audio.pause(); audio.currentTime = 0; }
    function restartAudio() { audio.currentTime = 0; audio.play(); }
    function seek(d) { audio.currentTime = Math.max(0, Math.min(audio.duration || 176, audio.currentTime + d)); }
    function toggleLoop() { audio.loop = !audio.loop; document.getElementById('loopBtn').style.color = audio.loop ? '#38bdf8' : '#e4e4e7'; }
    function switchMode(m) {
      currentMode = m;
      document.getElementById('btnA').classList.toggle('active', m === 'musical');
      document.getElementById('btnB').classList.toggle('active', m === 'diagnostic');
    }
    function downloadFile(ext) {
      if (ext === 'json') {
        window.open(`/data/audit_${currentTrackId}.json`, '_blank');
      } else {
        window.open(`/tracks/${currentTrackId}.mp3`, '_blank');
      }
    }
    function resetGlobe() { targetCamPos = new THREE.Vector3(0, 0.5, 2.7); ringMesh.visible = false; }

    // ==========================================
    // REQUIREMENT 6: MERGED LEFT PANEL CONTROLS (MINIMIZE / MAXIMIZE)
    // ==========================================
    const leftPanel = document.getElementById('leftPanel');
    const minPill = document.getElementById('minimizedPill');

    function toggleLeftPanel() {
      if (leftPanel.classList.contains('closed')) {
        restoreLeftPanel();
      } else {
        closeLeftPanel();
      }
    }
    function closeLeftPanel() {
      leftPanel.classList.add('closed');
      minPill.classList.remove('show');
      document.body.classList.remove('panel-maximized');
      isPanelMaximized = false;
      updateGlobeViewport(false);
      document.getElementById('btnToggleLeft').classList.remove('active');
    }
    function minimizeLeftPanel() {
      leftPanel.classList.add('closed');
      minPill.classList.add('show');
      document.body.classList.remove('panel-maximized');
      isPanelMaximized = false;
      updateGlobeViewport(false);
    }
    function restoreLeftPanel() {
      leftPanel.classList.remove('closed');
      minPill.classList.remove('show');
      document.getElementById('btnToggleLeft').classList.add('active');
    }
    function toggleMaximizePanel() {
      isPanelMaximized = !isPanelMaximized;
      leftPanel.classList.toggle('maximized', isPanelMaximized);
      document.body.classList.toggle('panel-maximized', isPanelMaximized);
      document.getElementById('btnMaxPanel').textContent = isPanelMaximized ? '🗗' : '⛶';
      updateGlobeViewport(isPanelMaximized);
    }

    function switchPanelView(viewId) {
      document.querySelectorAll('.panel-tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.panel-view').forEach(v => v.classList.remove('active'));
      const activeBtn = Array.from(document.querySelectorAll('.panel-tab-btn')).find(b => b.getAttribute('onclick')?.includes(viewId));
      if (activeBtn) activeBtn.classList.add('active');
      const targetView = document.getElementById(viewId);
      if (targetView) targetView.classList.add('active');
    }

    function toggleSvsCatalog() {
      const c = document.getElementById('svsCatalog');
      c.classList.toggle('open');
      document.getElementById('openSvsCatalog').classList.toggle('active', c.classList.contains('open'));
      if (c.classList.contains('open') && !document.getElementById('svsResults').children.length) searchSvs();
    }

    // Populate Soundscapes Tracks
    async function initSoundscapes() {
      try {
        const res = await fetch('/data/tracks.json');
        const data = await res.json();
        soundscapeTracks = data.tracks || [];

        const container = document.getElementById('trackListContainer');
        container.innerHTML = '';
        soundscapeTracks.forEach(t => {
          const card = document.createElement('div');
          card.className = `track-card ${t.id === currentTrackId ? 'active' : ''}`;
          card.id = `trackCard-${t.id}`;
          card.innerHTML = `
            <div class="tc-top">
              <span class="tc-title">${t.title}</span>
              <span class="tc-badge">${t.bars} bars · Key ${t.key}</span>
            </div>
            <div class="tc-meta">
              Dates: ${t.start_date} to ${t.end_date}<br/>
              Mean Speed: ${t.mean_speed_m_s.toFixed(3)} m/s · ${t.chord_changes} chord changes
            </div>
            <div class="tc-section-badge" id="secBadge-${t.id}">Section: Intro</div>
            <div class="tc-visual">
              Paired Visual: <a href="https://svs.gsfc.nasa.gov/3912/" target="_blank" rel="noopener noreferrer">NASA SVS 3912 (Perpetual Ocean)</a>
              <small>Credit: NASA/Goddard Space Flight Center Scientific Visualization Studio / Horace Mitchell</small>
            </div>
          `;
          card.addEventListener('click', () => selectAndPlayTrack(t.id));
          container.appendChild(card);
        });

        loadAuditTable('2025');
      } catch (err) {
        console.error('Could not load soundscape tracks:', err);
      }
    }
    initSoundscapes();

    async function selectAndPlayTrack(trackId) {
      currentTrackId = trackId;
      const track = soundscapeTracks.find(t => t.id === trackId) || soundscapeTracks[0];
      if (!track) return;

      document.querySelectorAll('.track-card').forEach(c => c.classList.remove('active'));
      const activeCard = document.getElementById(`trackCard-${trackId}`);
      if (activeCard) activeCard.classList.add('active');

      document.getElementById('auditTrackSelect').value = trackId;

      initWebAudio();
      if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();

      audio.src = `/tracks/${track.id}.mp3`;
      audio.currentTime = 0;
      audio.play().catch(() => {});

      document.getElementById('trackLabel').textContent = `${track.title} (${track.key}) — FluidSynth Soundscape`;
      loadAuditTable(trackId);
    }

    function loadAuditForSelectedTrack() {
      const tid = document.getElementById('auditTrackSelect').value;
      selectAndPlayTrack(tid);
    }

    async function loadAuditTable(trackId) {
      const tbody = document.getElementById('auditTableBody');
      tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; padding:18px; color:var(--muted);">Loading audit data...</td></tr>';
      try {
        const fname = trackId === '2025' ? '/data/audit_2025.json' : `/data/audit_${trackId}.json`;
        const res = await fetch(fname);
        const data = await res.json();
        currentAuditData = data;
        tbody.innerHTML = '';
        data.forEach(row => {
          const tr = document.createElement('tr');
          tr.setAttribute('data-bar', row.bar);
          const mel = row.melody_notes ? row.melody_notes.join(', ') : (row.melody || 'REST');
          tr.innerHTML = `
            <td style="font-weight:600; color:var(--accent);">${row.bar}</td>
            <td>${row.start_date.slice(5)} - ${row.end_date.slice(5)}</td>
            <td>${row.days_in_block}</td>
            <td>${row.mean_speed_p95_m_s.toFixed(3)}</td>
            <td>${row.norm_speed.toFixed(3)}</td>
            <td>${row.majority_sector_of_the_ageostrophic_component}</td>
            <td>${row.block_ageostrophic_magnitude_m_s.toFixed(4)}</td>
            <td>${row.held ? 'Yes' : 'No'}</td>
            <td style="font-weight:600; color:#fff;">${row.chord}</td>
            <td>${row.drum_tier}</td>
            <td style="max-width:130px; overflow:hidden; text-overflow:ellipsis;">${mel}</td>
            <td>${row.velocity_scale.toFixed(2)}</td>
          `;
          tbody.appendChild(tr);
        });
      } catch (err) {
        tbody.innerHTML = '<tr><td colspan="12" style="text-align:center; color:#f87171;">Audit table unavailable for this track.</td></tr>';
      }
    }

    // Globe Click Handler: Gulf Stream Check (lat 30-40, lon 280-300 / -80 to -60)
    function handleGlobeClick(lat, lng) {
      lastCoords = { lat, lng };
      const lon360 = (lng + 360) % 360;
      const isGulfStream = (lat >= 30 && lat <= 40) && ((lon360 >= 280 && lon360 <= 300) || (lng >= -80 && lng <= -60));
      const oceanCard = document.getElementById('oceanCard');
      oceanCard.classList.add('open');

      if (isGulfStream) {
        liveU = 0.892; liveV = 0.803; liveSpeed = 1.200;
        document.getElementById('ocName').textContent = 'North Atlantic (Gulf Stream)';
        document.getElementById('ocCoords').textContent = `${lat.toFixed(2)}°, ${lng.toFixed(2)}°`;
        document.getElementById('ocSpeed').textContent = '1.200 m/s';
        document.getElementById('ocAngle').textContent = '42.0° (NE)';
        document.getElementById('ocU').textContent = '0.892 m/s';
        document.getElementById('ocV').textContent = '0.803 m/s';
        document.getElementById('ocNote').textContent = 'Inside Gulf Stream box (30-40°N, 60-80°W). Derived from satellite data.';
        document.getElementById('ocBrief').textContent = 'Every note is computed from the data by rules we chose.';
        document.getElementById('lblFlow').textContent = '1.20 m/s';

        selectAndPlayTrack(currentTrackId || '2025');
      } else {
        const ocean = identifyOcean(lat, lng);
        document.getElementById('ocName').textContent = ocean.name;
        document.getElementById('ocCoords').textContent = `${lat.toFixed(2)}°, ${lng.toFixed(2)}°`;
        document.getElementById('ocSpeed').textContent = '—';
        document.getElementById('ocAngle').textContent = '—';
        document.getElementById('ocU').textContent = '—';
        document.getElementById('ocV').textContent = '—';
        document.getElementById('ocNote').textContent = 'No soundscape for this region yet. Only the Gulf Stream box is built.';
        document.getElementById('ocBrief').textContent = '';
        document.getElementById('trackLabel').textContent = 'No soundscape for this region yet. Only the Gulf Stream box is built.';
        audio.pause();
      }
    }

    // ==========================================
    // REQUIREMENT 5: SVS SEARCH, GENERATE & PAIR
    // ==========================================
    const catalog = document.getElementById('svsCatalog');
    const svsStatus = document.getElementById('svsStatus');
    document.getElementById('openSvsCatalog').addEventListener('click', toggleSvsCatalog);
    document.getElementById('svsSearchButton').addEventListener('click', () => { svsOffset = 0; searchSvs(); });
    document.getElementById('svsSearch').addEventListener('keydown', e => { if (e.key === 'Enter') { svsOffset = 0; searchSvs(); } });
    document.getElementById('svsEicOnly').addEventListener('change', () => { svsOffset = 0; searchSvs(); });
    document.getElementById('svsPrevious').addEventListener('click', () => { svsOffset = Math.max(0, svsOffset - 24); searchSvs(); });
    document.getElementById('svsNext').addEventListener('click', () => { if (svsOffset + 24 < svsCount) { svsOffset += 24; searchSvs(); } });
    document.getElementById('svsGenerate').addEventListener('click', generateSvs);
    document.getElementById('svsCancel').addEventListener('click', cancelSvs);

    window.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        catalog.classList.remove('open');
        document.getElementById('openSvsCatalog').classList.remove('active');
      }
    });

    async function searchSvs() {
      const results = document.getElementById('svsResults'); results.textContent = '';
      svsStatus.textContent = 'Connecting to NASA SVS…';
      try {
        const q = new URLSearchParams({ q: document.getElementById('svsSearch').value, offset: svsOffset, limit: 24, eic_only: document.getElementById('svsEicOnly').checked });
        const response = await fetch(`/api/svs/search?${q}`);
        if (!response.ok) throw new Error((await response.json()).detail || 'NASA SVS search failed.');
        const data = await response.json(); svsCount = data.count;
        data.results.forEach(item => {
          const button = document.createElement('button'); button.className = 'svs-result'; button.type = 'button';
          button.innerHTML = `<strong></strong><small></small>`;
          button.querySelector('strong').textContent = item.title || `NASA visualization ${item.id}`;
          button.querySelector('small').textContent = `ID ${item.id} · ${item.release_date || 'Date unavailable'} · ${item.result_type || 'NASA SVS'}`;
          button.addEventListener('click', () => loadSvs(item.id));
          results.appendChild(button);
        });
        document.getElementById('svsPrevious').disabled = svsOffset <= 0;
        document.getElementById('svsNext').disabled = svsOffset + 24 >= svsCount;
        svsStatus.textContent = `${svsCount.toLocaleString()} matching NASA SVS visualizations.`;
      } catch (error) {
        svsStatus.textContent = `NASA SVS catalog: ${error.message}`;
      }
    }

    async function loadSvs(id) {
      svsStatus.textContent = 'Retrieving visualization details…';
      try {
        const response = await fetch(`/api/svs/${id}`);
        if (!response.ok) throw new Error((await response.json()).detail || 'Metadata request failed.');
        selectedSvs = await response.json();

        // Pin selected item at top
        const pinned = document.getElementById('svsPinnedSelection');
        pinned.classList.add('open');
        document.getElementById('pinnedTitle').textContent = selectedSvs.title;
        document.getElementById('pinnedBadge').textContent = `NASA SVS ID ${selectedSvs.id}`;
        document.getElementById('pinnedDesc').textContent = selectedSvs.description || 'NASA visualization from Goddard Space Flight Center.';
        document.getElementById('pinnedMeta').textContent = `Released: ${selectedSvs.release_date || 'unknown'} · Credits: ${selectedSvs.credits ? selectedSvs.credits.slice(0, 100) : 'NASA GSFC'}`;

        const mediaDiv = document.getElementById('pinnedMedia'); mediaDiv.innerHTML = '';
        const media = selectedSvs.media || [], movie = media.find(a => ['Movie','Video'].includes(a.type));
        if (movie) {
          const video = document.createElement('video'); video.controls = true; video.muted = true; video.playsInline = true;
          video.src = `/api/svs/${selectedSvs.id}/video`;
          mediaDiv.appendChild(video);
        }

        document.getElementById('svsGenerate').disabled = !media.some(a => ['Frames','Movie','Video'].includes(a.type));
        svsStatus.textContent = 'Visualization selected. You can pair it with soundscapes or generate sound from frames.';
      } catch (error) {
        svsStatus.textContent = `Could not load visualization: ${error.message}`;
      }
    }

    // FIX FOR SVS PAIR: Proxy through server video endpoint to avoid CORS failure
    function pairSelectedSvsWithSoundscape() {
      if (!selectedSvs) return;
      const media = selectedSvs.media || [];
      const movie = media.find(a => ['Movie', 'Video'].includes(a.type));
      if (movie) {
        svsVideo.src = `/api/svs/${selectedSvs.id}/video`;
      }
      setVisualMode('svs');
      selectAndPlayTrack(currentTrackId || '2025');
      svsStatus.textContent = `Paired SVS ${selectedSvs.id} (${selectedSvs.title}) with Gulf Stream soundscape.`;
    }

    // FIX FOR SVS GENERATE: Fixed backend sonification_mapper import & frame extraction
    async function generateSvs() {
      if (!selectedSvs) return;
      const button = document.getElementById('svsGenerate'); button.disabled = true;
      initWebAudio(); if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
      svsStatus.textContent = 'Preparing frames…';
      try {
        const response = await fetch(`/api/svs/${selectedSvs.id}/sonify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sample_every: Number(document.getElementById('svsSampleEvery').value), max_frames: 120, mode: currentMode })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Could not start frame processing.');
        svsJob = (await response.json()).job_id;
        document.getElementById('svsCancel').hidden = false;
        svsPoll = setInterval(pollSvs, 700);
      } catch (error) {
        svsStatus.textContent = error.message; button.disabled = false;
      }
    }

    async function pollSvs() {
      if (!svsJob) return;
      try {
        const response = await fetch(`/api/svs/jobs/${svsJob}`);
        const job = await response.json();
        const p = job.progress || {};
        const stageNames = { queued: 'Queued', retrieving_metadata: 'Retrieving visualization info', processing_frames: 'Processing frame', rendering_audio: 'Rendering audio', complete: 'Complete' };
        svsStatus.textContent = p.total ? `${stageNames[job.status] || job.status}: ${p.current} of ${p.total}` : (stageNames[job.status] || job.status);
        const progress = document.getElementById('svsProgress');
        progress.max = Math.max(1, p.total || 1);
        progress.value = Math.min(progress.max, p.current || 0);
        if (job.status === 'complete') {
          clearInterval(svsPoll); svsPoll = null; svsJob = null;
          document.getElementById('svsCancel').hidden = true;
          document.getElementById('svsGenerate').disabled = false;
          audio.src = job.result.audio_url;
          document.getElementById('trackLabel').textContent = `${selectedSvs?.title || 'NASA SVS'} · visual-derived sound`;
          audio.play();
          svsStatus.textContent = 'Complete. Visual-derived sound is playing; audit record is available.';
        }
        if (['failed','cancelled'].includes(job.status)) {
          clearInterval(svsPoll); svsPoll = null; svsJob = null;
          document.getElementById('svsCancel').hidden = true;
          document.getElementById('svsGenerate').disabled = false;
          svsStatus.textContent = job.status === 'cancelled' ? 'Processing cancelled.' : `Processing failed: ${job.error}`;
        }
      } catch (error) {
        svsStatus.textContent = `Processing status: ${error.message}`;
      }
    }

    async function cancelSvs() {
      if (svsJob) await fetch(`/api/svs/jobs/${svsJob}`, { method: 'DELETE' });
      svsStatus.textContent = 'Cancelling frame processing…';
    }

    Object.assign(window, {
      resetGlobe, seek, restartAudio, togglePlay, stopAudio, toggleLoop, downloadFile, switchMode, setVisualMode,
      toggleLeftPanel, closeLeftPanel, minimizeLeftPanel, restoreLeftPanel, toggleMaximizePanel, switchPanelView,
      toggleSvsCatalog, selectAndPlayTrack, loadAuditForSelectedTrack, pairSelectedSvsWithSoundscape,
      selectTimelineYear
    });
  </script>
</body>
</html>
"""

with open("web/index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
print("Updated web/index.html with Requirements 1, 2, 3, 4, 5, 6!")
