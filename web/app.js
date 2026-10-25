/**
 * SystemAgant Tactile UI Controller (v0.2.1)
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

let telemetryInterval = null;

function updatePreviewFrame(page) {
  if (!dom.previewFrame) return;
  const targetPage = page || (dom.previewPageSelect ? dom.previewPageSelect.value : "index.html") || "index.html";
  dom.previewFrame.src = `/api/workspace/preview/${encodeURIComponent(targetPage)}?t=${Date.now()}`;
}

function isApprovalText(text) {
  if (!text) return false;
  const upper = text.toUpperCase();
  const keywords = [
    "APPROVE",
    "ZATWIERDZ",
    "ZATWIEDZ",
    "YES",
    "TAK",
    "OK",
    "PROCEED",
    "WYKONAJ",
    "START",
    "ROZPOCZNIJ",
    "WDROŻ",
    "WDROZ",
    "AKCEPTUJ",
    "ZGODA",
  ];
  return keywords.some(kw => upper.includes(kw));
}

function startTelemetryPolling() {
  if (telemetryInterval) return;
  const pollOnce = async () => {
    try {
      const res = await fetch("/api/state", { headers: getHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      renderAll(data);
      if (!data.is_busy && data.current_phase !== "EXECUTION") {
        stopTelemetryPolling();
        updatePreviewFrame();
      }
    } catch (err) {
      console.error("Telemetry polling error:", err);
    }
  };
  pollOnce();
  telemetryInterval = setInterval(pollOnce, 250);
}

function stopTelemetryPolling() {
  if (telemetryInterval) {
    clearInterval(telemetryInterval);
    telemetryInterval = null;
  }
}

// Fetch state from server
async function fetchState() {
  try {
    const res = await fetch("/api/state", { headers: getHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderAll(data);
    if (data.is_busy) {
      startTelemetryPolling();
    }
  } catch (err) {
    console.error("Failed to fetch state:", err);
  }
}

function renderAll(data) {
  if (!data) return;
  try { renderHeaderAndGraph(data); } catch (err) { console.error("renderHeaderAndGraph error:", err); }
  try { renderChat(data); } catch (err) { console.error("renderChat error:", err); }
  try { renderWbs(data.wbs); } catch (err) { console.error("renderWbs error:", err); }
  try { renderFiles(data.files); } catch (err) { console.error("renderFiles error:", err); }
  try { renderLogs(data.logs); } catch (err) { console.error("renderLogs error:", err); }
}

function renderHeaderAndGraph(data) {
  const modeText = data.mode === "GEMINI-FREE" ? "GEMINI FLASH LIVE" : (data.mode || "LIVE");
  if (dom.modeLabel) dom.modeLabel.textContent = modeText;
  if (dom.graphCycleMeta) dom.graphCycleMeta.textContent = `CYCLE: ${data.iteration || 0} | PHASE: ${data.current_phase || "IDLE"}`;
  
  const active = (data.active_node || "").toLowerCase();
  if (data.is_busy) {
    if (dom.chatStatusMeta) dom.chatStatusMeta.textContent = `STATUS: ACTIVE [${active.toUpperCase()}]`;
  } else {
    if (dom.chatStatusMeta) dom.chatStatusMeta.textContent = `STATUS: ${data.current_phase || "IDLE"}`;
  }

  // Update LEDs
  [dom.ledArchitect, dom.ledCoder, dom.ledTester, dom.ledRouter].forEach(el => {
    if (el) el.classList.remove("active");
  });
  
  if (active === "architect" && dom.ledArchitect) dom.ledArchitect.classList.add("active");
  if (active === "coder" && dom.ledCoder) dom.ledCoder.classList.add("active");
  if (active === "tester" && dom.ledTester) dom.ledTester.classList.add("active");
  if (active === "router" && dom.ledRouter) dom.ledRouter.classList.add("active");

  // Update wire nodes
  [dom.nodeRouter, dom.nodeArchitect, dom.nodeCoder, dom.nodeTester, dom.nodeHuman].forEach(el => {
    if (el) {
      el.classList.remove("active");
      el.classList.remove("current");
    }
  });
  [dom.statusRouter, dom.statusArchitect, dom.statusCoder, dom.statusTester, dom.statusHuman].forEach(el => {
    if (el) el.textContent = "STANDBY";
  });

  if (active === "router" && dom.nodeRouter) {
    dom.nodeRouter.classList.add("active", "current");
    if (dom.statusRouter) dom.statusRouter.textContent = data.is_busy ? "ROUTING" : "STANDBY";
  } else if (active === "architect" && dom.nodeArchitect) {
    dom.nodeArchitect.classList.add("active", "current");
    if (dom.statusArchitect) dom.statusArchitect.textContent = "SYNTHESIZING";
  } else if (active === "coder" && dom.nodeCoder) {
    dom.nodeCoder.classList.add("active", "current");
    if (dom.statusCoder) dom.statusCoder.textContent = "GENERATING";
  } else if (active === "tester" && dom.nodeTester) {
    dom.nodeTester.classList.add("active", "current");
    if (dom.statusTester) dom.statusTester.textContent = "VERIFYING";
  } else if (active === "human_approval" && dom.nodeHuman) {
    dom.nodeHuman.classList.add("active", "current");
    if (dom.statusHuman) dom.statusHuman.textContent = "AWAITING";
  }

  // HITL Banner Visibility
  if (dom.hitlBanner) {
    if (data.awaiting_hitl) {
      dom.hitlBanner.classList.remove("hidden");
    } else {
      dom.hitlBanner.classList.add("hidden");
    }
  }

  // Progress Meter
  const pct = data.progress_percent || 0;
  if (dom.progressVal) dom.progressVal.textContent = `${pct}%`;
  if (dom.progressMeter) {
    const segs = dom.progressMeter.querySelectorAll(".meter-segment");
    const fillCount = Math.round((pct / 100) * segs.length);
    segs.forEach((seg, i) => {
      if (i < fillCount) seg.classList.add("filled");
      else seg.classList.remove("filled");
    });
  }

  if ((data.has_api_key || sessionApiKey) && dom.btnApiKey) {
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

  // Render live in-progress agent bubble while state machine is active
  if (data.is_busy) {
    const active = (data.active_node || "ROUTER").toUpperCase();
    const currentTask = data.current_task_id ? ` // ${escapeHtml(data.current_task_id)}` : "";
    let statusText = "System processing state transition...";
    if (data.logs && data.logs.length > 0) {
      statusText = data.logs[data.logs.length - 1].content || statusText;
    }

    const liveEl = document.createElement("div");
    liveEl.className = "chat-bubble system live-activity-bubble";
    liveEl.innerHTML = `
      <div class="bubble-header" style="color: var(--accent-amber); display: flex; justify-content: space-between; align-items: center;">
        <span>[${active}${currentTask}]</span>
        <span class="live-status-pill"><span class="pulse-indicator">●</span>LIVE ACTIVE</span>
      </div>
      <div class="bubble-body" style="color: #fff; font-size: 11px; margin-top: 4px;">
        ${escapeHtml(statusText)}
      </div>
    `;
    dom.chatMessages.appendChild(liveEl);
  }

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
      dom.previewPageSelect.innerHTML = '<option value="">No HTML pages</option>';
    } else {
      htmlFiles.forEach((hf, idx) => {
        const opt = document.createElement("option");
        opt.value = hf.name;
        opt.textContent = `${hf.name} (${hf.size} B)`;
        if (hf.name === currentVal || (!currentVal && idx === 0)) opt.selected = true;
        dom.previewPageSelect.appendChild(opt);
      });
    }
  }

  if (currentFiles.length === 0) {
    dom.fileTree.innerHTML = '<div style="color: var(--text-dim); font-size: 11px; padding: 10px;">// Workspace directory empty.</div>';
    dom.codeFilename.textContent = "// No files in workspace";
    dom.codeContent.textContent = "// Workspace contains no code files yet. Describe your requirements to generate code.";
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

  // Auto-load primary file into the code viewer
  const defaultFile = currentFiles[0].name;
  loadFileContent(defaultFile);
}

async function loadFileContent(filename) {
  if (dom.codeFilename) dom.codeFilename.textContent = `// ${filename}`;
  if (dom.codeContent) dom.codeContent.textContent = "// Fetching content from sandbox...";

  // Highlight active file in file tree
  if (dom.fileTree) {
    dom.fileTree.querySelectorAll(".file-item, .file-tree-item").forEach(el => {
      if (el.getAttribute("data-filename") === filename) {
        el.classList.add("selected");
      } else {
        el.classList.remove("selected");
      }
    });
  }

  try {
    const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error("File not found");
    const text = await res.text();
    if (dom.codeContent) dom.codeContent.textContent = text;
  } catch (err) {
    if (dom.codeContent) dom.codeContent.textContent = `// Error loading file: ${err.message}`;
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

  const isApproval = isApprovalText(msg);
  if (isApproval) {
    if (dom.chatStatusMeta) dom.chatStatusMeta.textContent = "STATUS: ACTIVE [CODER // INITIALIZING]";
    if (dom.nodeCoder) dom.nodeCoder.classList.add("active", "current");
    if (dom.ledCoder) dom.ledCoder.classList.add("active");
    startTelemetryPolling();
    switchTab("preview");
  } else {
    if (dom.chatStatusMeta) dom.chatStatusMeta.textContent = "STATUS: ACTIVE [ARCHITECT // ANALYZING]";
    if (dom.nodeArchitect) dom.nodeArchitect.classList.add("active", "current");
    if (dom.ledArchitect) dom.ledArchitect.classList.add("active");
    startTelemetryPolling();
  }

  // Render optimistic agent telemetry pulse indicator
  const tempEl = document.createElement("div");
  tempEl.id = "tempAgentIndicator";
  tempEl.className = "chat-bubble system live-activity-bubble";
  const agentTitle = isApproval ? "CODER // INITIALIZING" : "ARCHITECT // ANALYZING";
  const agentDesc = isApproval
    ? "Execution cycle engaged. Routing atomic tasks through state machine..."
    : "Analyzing requirements and synthesizing architecture...";
  tempEl.innerHTML = `
    <div class="bubble-header" style="color: var(--accent-amber); display: flex; justify-content: space-between; align-items: center;">
      <span>[${agentTitle}]</span>
      <span class="live-status-pill"><span class="pulse-indicator">●</span>LIVE ACTIVE</span>
    </div>
    <div class="bubble-body" style="color: #fff; font-size: 11px; margin-top: 4px;">
      ${agentDesc}
    </div>
  `;
  dom.chatMessages.appendChild(tempEl);
  dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;

  const btnSubmit = dom.chatForm.querySelector("button[type='submit']");
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.textContent = "[ RUNNING... ]";
  }

  try {
    const proj = dom.inputProjectName ? dom.inputProjectName.value.trim() : undefined;
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({
        message: msg,
        project_name: proj,
        api_key: sessionApiKey || undefined,
        async_execution: true,
      }),
    });
    if (!res.ok) throw new Error("Server error");
    const data = await res.json();
    const temp = document.getElementById("tempAgentIndicator");
    if (temp) temp.remove();
    renderAll(data);
    if (data.is_busy) {
      startTelemetryPolling();
    } else {
      stopTelemetryPolling();
      updatePreviewFrame();
    }
  } catch (err) {
    console.error("Chat error:", err);
    const temp = document.getElementById("tempAgentIndicator");
    if (temp) temp.remove();
    stopTelemetryPolling();
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.textContent = "[ TRANSMIT ]";
    }
  }
});

// HITL Approve Button
dom.btnHitlApprove.addEventListener("click", async () => {
  try {
    const proj = dom.inputProjectName ? dom.inputProjectName.value.trim() : undefined;
    if (dom.chatStatusMeta) dom.chatStatusMeta.textContent = "STATUS: ACTIVE [CODER // INITIALIZING]";
    if (dom.nodeCoder) dom.nodeCoder.classList.add("active", "current");
    if (dom.ledCoder) dom.ledCoder.classList.add("active");
    startTelemetryPolling();
    switchTab("preview");
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({ message: "APPROVE", project_name: proj, api_key: sessionApiKey || undefined, async_execution: true }),
    });
    if (!res.ok) throw new Error("Server error");
    const data = await res.json();
    renderAll(data);
    if (data.is_busy) {
      startTelemetryPolling();
    }
  } catch (err) {
    console.error("Approval error:", err);
    stopTelemetryPolling();
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
    updatePreviewFrame();
  } catch (err) {
    console.error("Reset error:", err);
  }
});

// Preview page selection & refresh
if (dom.previewPageSelect) {
  dom.previewPageSelect.addEventListener("change", () => {
    updatePreviewFrame(dom.previewPageSelect.value);
  });
}

dom.btnRefreshPreview.addEventListener("click", () => {
  updatePreviewFrame();
});

// Tab navigation
function switchTab(tabKey) {
  [dom.tabLivePreview, dom.tabFiles, dom.tabWbs, dom.tabLogs].forEach(t => t.classList.remove("active"));
  [dom.panePreview, dom.paneFiles, dom.paneWbs, dom.paneLogs].forEach(p => p.classList.remove("active"));

  if (tabKey === "preview") {
    dom.tabLivePreview.classList.add("active");
    dom.panePreview.classList.add("active");
    updatePreviewFrame();
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
      
      // Determine primary file for preview
      const htmlFile = (state.files || []).find(f => f.name.endsWith(".html"));
      const previewFile = htmlFile ? htmlFile.name : "";
      updatePreviewFrame(previewFile);
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
      updatePreviewFrame();
    } catch (err) {
      console.error("Failed to create new workspace:", err);
    }
  });
}

// Iframe load listener to synchronize page selector when user clicks links inside preview
if (dom.previewFrame) {
  dom.previewFrame.addEventListener("load", () => {
    try {
      const loc = dom.previewFrame.contentWindow.location;
      const pathname = loc.pathname || "";
      const filename = pathname.split("/").filter(Boolean).pop();
      if (filename && filename.endsWith(".html") && dom.previewPageSelect) {
        if (dom.previewPageSelect.value !== filename) {
          dom.previewPageSelect.value = filename;
        }
      }
    } catch (e) {
      // Cross-origin fallback
    }
  });
}

// Initial state fetch & background standby refresh (5 seconds)
loadWorkspacesList();
fetchState();

setInterval(() => {
  if (!telemetryInterval) {
    fetchState();
  }
}, 5000);
