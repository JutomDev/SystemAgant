/**
 * SystemAgant Tactile UI Controller (v2.2)
 * Interactive Multi-Agent Conversation, Live Workspace Explorer & Telemetry
 */

// In-memory session key (never persisted to disk/localStorage)
let sessionApiKey = "";

// DOM Elements
const dom = {
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatStatusMeta: document.getElementById("chat-status-meta"),
  hitlBanner: document.getElementById("hitl-banner"),
  btnHitlApprove: document.getElementById("btn-hitl-approve"),
  btnHitlAsk: document.getElementById("btn-hitl-ask"),
  chipKwiaciarnia: document.getElementById("chip-kwiaciarnia"),
  chipGame: document.getElementById("chip-game"),
  chipCli: document.getElementById("chip-cli"),
  btnApiKey: document.getElementById("btn-api-key"),
  inputProjectName: document.getElementById("input-project-name"),
  selectWorkspace: document.getElementById("select-workspace"),
  btnNewWorkspace: document.getElementById("btn-new-workspace"),
  workspaceBadge: document.getElementById("workspace-badge"),

  // LEDs
  ledArchitect: document.getElementById("led-architect"),
  ledCoder: document.getElementById("led-coder"),
  ledTester: document.getElementById("led-tester"),
  ledRouter: document.getElementById("led-router"),
  modeLabel: document.getElementById("mode-label"),

  // Graph nodes
  nodeRouter: document.getElementById("node-router"),
  nodeArchitect: document.getElementById("node-architect"),
  nodeCoder: document.getElementById("node-coder"),
  nodeTester: document.getElementById("node-tester"),
  nodeHuman: document.getElementById("node-human"),

  statusRouter: document.getElementById("status-router"),
  statusArchitect: document.getElementById("status-architect"),
  statusCoder: document.getElementById("status-coder"),
  statusTester: document.getElementById("status-tester"),
  statusHuman: document.getElementById("status-human"),
  graphCycleMeta: document.getElementById("graph-cycle-meta"),

  // Tabs & Views
  tabLivePreview: document.getElementById("tab-live-preview"),
  tabFiles: document.getElementById("tab-files"),
  tabWbs: document.getElementById("tab-wbs"),
  tabLogs: document.getElementById("tab-logs"),

  panePreview: document.getElementById("pane-preview"),
  paneFiles: document.getElementById("pane-files"),
  paneWbs: document.getElementById("pane-wbs"),
  paneLogs: document.getElementById("pane-logs"),

  previewFrame: document.getElementById("preview-frame"),
  previewPageSelect: document.getElementById("preview-page-select"),
  btnRefreshPreview: document.getElementById("btn-refresh-preview"),

  fileTree: document.getElementById("file-tree"),
  codeFilename: document.getElementById("code-filename"),
  codeContent: document.getElementById("code-content"),

  wbsContainer: document.getElementById("wbs-container"),
  terminalStream: document.getElementById("terminal-stream"),
  progressVal: document.getElementById("progress-val"),
  progressMeter: document.getElementById("progress-meter"),
  btnResetSession: document.getElementById("btn-reset-session")
};

let currentFiles = [];

function getHeaders() {
  const h = { "Content-Type": "application/json" };
  if (sessionApiKey) {
    h["X-Gemini-Key"] = sessionApiKey;
  }
  return h;
}

// Fetch state from server
async function fetchState() {
  try {
    const res = await fetch("/api/state", { headers: getHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderAll(data);
  } catch (err) {
    console.error("Failed to fetch state:", err);
  }
}

function renderAll(data) {
  renderHeaderAndGraph(data);
  renderChat(data);
  renderWbs(data.wbs);
  renderFiles(data.files);
  renderLogs(data.logs);
}

function renderHeaderAndGraph(data) {
  const modeText = data.mode === "GEMINI-FREE" ? "GEMINI FLASH LIVE" : (data.mode || "LIVE");
  dom.modeLabel.textContent = modeText;
  dom.graphCycleMeta.textContent = `CYCLE: ${data.iteration || 0} | PHASE: ${data.current_phase || "IDLE"}`;
  dom.chatStatusMeta.textContent = `STATUS: ${data.current_phase}`;

  // Update LEDs
  const active = (data.active_node || "").toLowerCase();
  [dom.ledArchitect, dom.ledCoder, dom.ledTester, dom.ledRouter].forEach(el => el.classList.remove("active"));
  
  if (active === "architect") dom.ledArchitect.classList.add("active");
  if (active === "coder") dom.ledCoder.classList.add("active");
  if (active === "tester") dom.ledTester.classList.add("active");
  if (active === "router") dom.ledRouter.classList.add("active");

  // Update wire nodes
  [dom.nodeRouter, dom.nodeArchitect, dom.nodeCoder, dom.nodeTester, dom.nodeHuman].forEach(el => el.classList.remove("active"));
  [dom.statusRouter, dom.statusArchitect, dom.statusCoder, dom.statusTester, dom.statusHuman].forEach(el => el.textContent = "STANDBY");

  if (active === "router") {
    dom.nodeRouter.classList.add("active");
    dom.statusRouter.textContent = "EVALUATING";
  } else if (active === "architect") {
    dom.nodeArchitect.classList.add("active");
    dom.statusArchitect.textContent = "SYNTHESIZING";
  } else if (active === "coder") {
    dom.nodeCoder.classList.add("active");
    dom.statusCoder.textContent = "GENERATING";
  } else if (active === "tester") {
    dom.nodeTester.classList.add("active");
    dom.statusTester.textContent = "VERIFYING";
  } else if (active === "human_approval") {
    dom.nodeHuman.classList.add("active");
    dom.statusHuman.textContent = "AWAITING";
  }

  // HITL Banner Visibility
  if (data.awaiting_hitl) {
    dom.hitlBanner.classList.remove("hidden");
  } else {
    dom.hitlBanner.classList.add("hidden");
  }

  // Progress Meter
  const pct = data.progress_percent || 0;
  dom.progressVal.textContent = `${pct}%`;
  const segs = dom.progressMeter.querySelectorAll(".meter-segment");
  const fillCount = Math.round((pct / 100) * segs.length);
  segs.forEach((seg, i) => {
    if (i < fillCount) seg.classList.add("filled");
    else seg.classList.remove("filled");
  });

  if (data.has_api_key || sessionApiKey) {
    dom.btnApiKey.textContent = "[ KEY: ACTIVE ]";
    dom.btnApiKey.style.color = "var(--accent-green)";
  }

  if (data.workspace_dir && dom.workspaceBadge) {
    dom.workspaceBadge.textContent = data.workspace_dir;
  }
  if (data.project_name) {
    if (dom.inputProjectName) dom.inputProjectName.value = data.project_name;
    if (dom.selectWorkspace && dom.selectWorkspace.value !== data.project_name) {
      dom.selectWorkspace.value = data.project_name;
    }
  }

  if (dom.chatInput) {
    if (data.current_phase === "COMPLETED") {
      dom.chatInput.placeholder = "Project complete. Enter follow-up requirements to extend or refine...";
    } else {
      dom.chatInput.placeholder = "Enter instructions or architectural requirements...";
    }
  }
}

function renderChat(data) {
  const messages = data.chat_messages || [];
  dom.chatMessages.innerHTML = "";

  messages.forEach(msg => {
    const el = document.createElement("div");
    el.className = `chat-bubble ${msg.sender || "system"}`;
    
    let html = `<div class="bubble-header">[${(msg.title || msg.sender || "").toUpperCase()}]</div>`;
    html += `<div class="bubble-body">${escapeHtml(msg.text)}</div>`;

    if (msg.has_wbs && data.wbs && data.wbs.length > 0) {
      html += `<div class="wbs-preview-box">`;
      html += `<div style="font-size: 10px; color: var(--accent-amber); margin-bottom: 6px;">[ PROPOSED WORK BREAKDOWN STRUCTURE ]</div>`;
      data.wbs.forEach(epic => {
        html += `<div style="font-weight: 700; margin-top: 4px; color: var(--accent-cyan); font-size: 11px;">${escapeHtml(epic.epic_id)}: ${escapeHtml(epic.description)}</div>`;
        (epic.tasks || []).forEach(t => {
          html += `<div style="padding-left: 12px; font-size: 10px; color: var(--text-base); margin: 2px 0;">• [${escapeHtml(t.task_id)}] ${escapeHtml(t.description)}</div>`;
        });
      });
      html += `</div>`;
    }

    el.innerHTML = html;
    dom.chatMessages.appendChild(el);
  });

  dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
}

function renderWbs(wbs) {
  if (!wbs || wbs.length === 0) {
    dom.wbsContainer.innerHTML = '<div style="color: var(--text-dim); font-size: 11px;">// No active WBS synthesized yet.</div>';
    return;
  }

  let html = "";
  wbs.forEach(epic => {
    html += `<div class="wbs-epic">`;
    html += `<div class="wbs-epic-title">${escapeHtml(epic.epic_id)}: ${escapeHtml(epic.description)}</div>`;
    (epic.tasks || []).forEach(t => {
      const statusClass = `status-${t.status}`;
      html += `
        <div class="wbs-task ${statusClass}">
          <span class="wbs-task-id">${escapeHtml(t.task_id)}</span>
          <span class="wbs-task-desc">${escapeHtml(t.description)}</span>
          <span class="wbs-badge ${statusClass}">${escapeHtml((t.status || "pending").toUpperCase())}</span>
        </div>
      `;
    });
    html += `</div>`;
  });
  dom.wbsContainer.innerHTML = html;
}

function renderFiles(files) {
  currentFiles = files || [];
  
  // Populate Preview Page Selector dropdown with all HTML files
  if (dom.previewPageSelect) {
    const htmlFiles = currentFiles.filter(f => f.name.endsWith(".html"));
    const currentVal = dom.previewPageSelect.value;
    dom.previewPageSelect.innerHTML = "";
    if (htmlFiles.length === 0) {
      dom.previewPageSelect.innerHTML = '<option value="index.html">index.html (Default)</option>';
    } else {
      htmlFiles.forEach(hf => {
        const opt = document.createElement("option");
        opt.value = hf.name;
        opt.textContent = `${hf.name} (${hf.size} B)`;
        if (hf.name === currentVal) opt.selected = true;
        dom.previewPageSelect.appendChild(opt);
      });
    }
  }

  if (currentFiles.length === 0) {
    dom.fileTree.innerHTML = '<div style="color: var(--text-dim); font-size: 11px; padding: 10px;">// Workspace directory empty.</div>';
    return;
  }

  let html = "";
  currentFiles.forEach(f => {
    html += `
      <div class="file-item" data-filename="${escapeHtml(f.name)}">
        <span class="file-name">[FILE] ${escapeHtml(f.name)}</span>
        <span class="file-size">${f.size} B</span>
      </div>
    `;
  });
  dom.fileTree.innerHTML = html;

  dom.fileTree.querySelectorAll(".file-item").forEach(el => {
    el.addEventListener("click", () => {
      const fname = el.getAttribute("data-filename");
      loadFileContent(fname);
      // If it is an HTML file, also update the preview dropdown
      if (fname.endsWith(".html") && dom.previewPageSelect) {
        dom.previewPageSelect.value = fname;
      }
    });
  });
}

async function loadFileContent(filename) {
  dom.codeFilename.textContent = `// ${filename}`;
  dom.codeContent.textContent = "// Fetching content from sandbox...";
  try {
    const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error("File not found");
    const text = await res.text();
    dom.codeContent.textContent = text;
  } catch (err) {
    dom.codeContent.textContent = `// Error loading file: ${err.message}`;
  }
}

function renderLogs(logs) {
  if (!logs || logs.length === 0) return;
  dom.terminalStream.innerHTML = "";
  logs.forEach(l => {
    const el = document.createElement("div");
    el.className = "log-line";
    const nodeTag = l.node ? `[${l.node.toUpperCase()}]` : "[SYS]";
    el.innerHTML = `<span style="color: var(--accent-amber);">${nodeTag}</span> ${escapeHtml(l.content || "")}`;
    dom.terminalStream.appendChild(el);
  });
  dom.terminalStream.scrollTop = dom.terminalStream.scrollHeight;
}

// User submit message
dom.chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = dom.chatInput.value.trim();
  if (!msg) return;

  dom.chatInput.value = "";
  
  // Render user bubble immediately
  const userEl = document.createElement("div");
  userEl.className = "chat-bubble user";
  userEl.innerHTML = `<div class="bubble-header">[USER]</div><div class="bubble-body">${escapeHtml(msg)}</div>`;
  dom.chatMessages.appendChild(userEl);
  dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;

  try {
    const proj = dom.inputProjectName ? dom.inputProjectName.value.trim() : undefined;
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({ message: msg, project_name: proj, api_key: sessionApiKey || undefined })
    });
    if (!res.ok) throw new Error("Server error");
    const data = await res.json();
    renderAll(data);
    dom.previewFrame.src = "/api/workspace/preview?t=" + Date.now();
  } catch (err) {
    console.error("Chat error:", err);
  }
});

// HITL Approve Button
dom.btnHitlApprove.addEventListener("click", async () => {
  try {
    const proj = dom.inputProjectName ? dom.inputProjectName.value.trim() : undefined;
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({ message: "APPROVE", project_name: proj, api_key: sessionApiKey || undefined })
    });
    if (!res.ok) throw new Error("Server error");
    const data = await res.json();
    renderAll(data);
    dom.previewFrame.src = "/api/workspace/preview?t=" + Date.now();
    // Auto switch to preview tab
    switchTab("preview");
  } catch (err) {
    console.error("Approval error:", err);
  }
});

dom.btnHitlAsk.addEventListener("click", () => {
  dom.chatInput.value = "Can we adjust the architecture: ";
  dom.chatInput.focus();
});

// Example prompt presets
if (dom.chipKwiaciarnia) {
  dom.chipKwiaciarnia.addEventListener("click", () => {
    if (dom.inputProjectName) dom.inputProjectName.value = "kwiaciarnia_mex";
    dom.chatInput.value = "Create a botanical floral shop website for Kwiaciarnia-Mex in Toruń with 3 subpages (Home, Catalog with flower photos, Contact) and clean responsive styles.";
    dom.chatInput.focus();
  });
}

if (dom.chipGame) {
  dom.chipGame.addEventListener("click", () => {
    if (dom.inputProjectName) dom.inputProjectName.value = "breakout_arcade";
    dom.chatInput.value = "Build a retro 2D arcade game in HTML5 Canvas and JavaScript with scoring, player controls, and start/game-over screens.";
    dom.chatInput.focus();
  });
}

if (dom.chipCli) {
  dom.chipCli.addEventListener("click", () => {
    if (dom.inputProjectName) dom.inputProjectName.value = "python_cli_tool";
    dom.chatInput.value = "Build a Python CLI developer tool with argparse, robust logging, modular architecture, and unit tests.";
    dom.chatInput.focus();
  });
}

// Session API Key configuration
if (dom.btnApiKey) {
  dom.btnApiKey.addEventListener("click", () => {
    const entered = prompt(
      "Enter your Google AI Studio Gemini API Key\n(Stored strictly in browser session memory, never written to disk or repository):",
      sessionApiKey || ""
    );
    if (entered !== null) {
      sessionApiKey = entered.trim();
      alert(sessionApiKey ? "Session API Key configured." : "Session API Key cleared.");
      fetchState();
    }
  });
}

// Reset Session
dom.btnResetSession.addEventListener("click", async () => {
  if (!confirm("Are you sure you want to reset the agent session and clear workspace state?")) return;
  try {
    const proj = dom.inputProjectName ? dom.inputProjectName.value.trim() : undefined;
    const res = await fetch("/api/reset", {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({ project_name: proj })
    });
    if (!res.ok) return;
    const data = await res.json();
    renderAll(data);
    dom.previewFrame.src = "/api/workspace/preview?t=" + Date.now();
  } catch (err) {
    console.error("Reset error:", err);
  }
});

// Preview page selection & refresh
if (dom.previewPageSelect) {
  dom.previewPageSelect.addEventListener("change", () => {
    const page = dom.previewPageSelect.value;
    dom.previewFrame.src = `/api/workspace/preview?file=${encodeURIComponent(page)}&t=${Date.now()}`;
  });
}

dom.btnRefreshPreview.addEventListener("click", () => {
  const page = dom.previewPageSelect ? dom.previewPageSelect.value : "index.html";
  dom.previewFrame.src = `/api/workspace/preview?file=${encodeURIComponent(page)}&t=${Date.now()}`;
});

// Tab navigation
function switchTab(tabKey) {
  [dom.tabLivePreview, dom.tabFiles, dom.tabWbs, dom.tabLogs].forEach(t => t.classList.remove("active"));
  [dom.panePreview, dom.paneFiles, dom.paneWbs, dom.paneLogs].forEach(p => p.classList.remove("active"));

  if (tabKey === "preview") {
    dom.tabLivePreview.classList.add("active");
    dom.panePreview.classList.add("active");
    const page = dom.previewPageSelect ? dom.previewPageSelect.value : "index.html";
    dom.previewFrame.src = `/api/workspace/preview?file=${encodeURIComponent(page)}&t=${Date.now()}`;
  } else if (tabKey === "files") {
    dom.tabFiles.classList.add("active");
    dom.paneFiles.classList.add("active");
    if (currentFiles.length > 0) loadFileContent(currentFiles[0].name);
  } else if (tabKey === "wbs") {
    dom.tabWbs.classList.add("active");
    dom.paneWbs.classList.add("active");
  } else if (tabKey === "logs") {
    dom.tabLogs.classList.add("active");
    dom.paneLogs.classList.add("active");
  }
}

dom.tabLivePreview.addEventListener("click", () => switchTab("preview"));
dom.tabFiles.addEventListener("click", () => switchTab("files"));
dom.tabWbs.addEventListener("click", () => switchTab("wbs"));
dom.tabLogs.addEventListener("click", () => switchTab("logs"));

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Workspace Management: Switch, Resume and Create
async function loadWorkspacesList() {
  if (!dom.selectWorkspace) return;
  try {
    const res = await fetch("/api/workspaces");
    if (!res.ok) return;
    const data = await res.json();
    dom.selectWorkspace.innerHTML = "";
    (data.workspaces || []).forEach(ws => {
      const opt = document.createElement("option");
      opt.value = ws.name;
      opt.textContent = `${ws.name} (${ws.file_count} files [${ws.phase}])`;
      if (ws.name === data.active_workspace) {
        opt.selected = true;
      }
      dom.selectWorkspace.appendChild(opt);
    });
    if (dom.inputProjectName) {
      dom.inputProjectName.value = data.active_workspace;
    }
  } catch (err) {
    console.error("Failed to load workspaces list:", err);
  }
}

if (dom.selectWorkspace) {
  dom.selectWorkspace.addEventListener("change", async () => {
    const targetWs = dom.selectWorkspace.value;
    if (!targetWs) return;
    try {
      const res = await fetch("/api/workspace/load", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ project_name: targetWs })
      });
      if (!res.ok) return;
      const state = await res.json();
      renderAll(state);
      await loadWorkspacesList();
      dom.previewFrame.src = "/api/workspace/preview?t=" + Date.now();
    } catch (err) {
      console.error("Failed to load workspace:", err);
    }
  });
}

if (dom.btnNewWorkspace) {
  dom.btnNewWorkspace.addEventListener("click", async () => {
    const name = prompt("Enter a unique name for the new workspace (e.g. 'flower_shop', 'arcade_game'):");
    if (!name || !name.trim()) return;
    try {
      const res = await fetch("/api/workspace/new", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ project_name: name.trim() })
      });
      if (!res.ok) return;
      const state = await res.json();
      renderAll(state);
      await loadWorkspacesList();
      dom.previewFrame.src = "/api/workspace/preview?t=" + Date.now();
    } catch (err) {
      console.error("Failed to create new workspace:", err);
    }
  });
}

// Initial state fetch
loadWorkspacesList();
fetchState();
