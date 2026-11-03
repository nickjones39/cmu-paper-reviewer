// Local-models mode for the upload form (fork add-on, injected by backend/localmodels/app.py).
//
// Loaded *before* upload.js so the extra mode pill exists when upload.js binds
// its pill handlers. Everything that needs upload.js (updateSubmitButton,
// performUpload, showConsentModal, reviewSettings, selectedFile, ...) runs on
// DOMContentLoaded, after every classic script has executed.
(function () {
  "use strict";

  const STORE_KEY = "localModels.v1";
  const HAS_UPSTREAM = () =>
    typeof updateSubmitButton === "function" &&
    typeof performUpload === "function" &&
    typeof showMessage === "function";

  const css = `
    .lm-row { display:flex; gap:.5rem; align-items:center; }
    .lm-row > select, .lm-row > input { flex:1; min-width:0; }
    #lm-fields select, #lm-fields input[type="number"] {
      width:100%; height:44px; padding:0 .85rem; border:1px solid var(--gray-300);
      border-radius:var(--radius); font-size:.93rem; font-family:inherit; color:var(--gray-800); background:#fff;
    }
    #lm-fields select:focus, #lm-fields input[type="number"]:focus {
      outline:none; border-color:var(--cmu-red); box-shadow:0 0 0 3px rgba(196,18,48,.12);
    }
    #lm-fields .btn-sm { height:44px; flex:none; }
    .lm-servers { display:flex; flex-wrap:wrap; gap:.4rem; margin:.25rem 0 .5rem; min-height:1.6rem; align-items:center; }
    .lm-chip { display:inline-flex; align-items:center; gap:.35rem; padding:.25rem .7rem; border-radius:999px;
      border:1px solid var(--gray-300); background:#fff; font-size:.8rem; color:var(--gray-700); cursor:pointer; font-family:inherit; }
    .lm-chip:hover { border-color:var(--gray-400); }
    .lm-chip.active { border-color:var(--cmu-red); color:var(--cmu-red); background:var(--cmu-red-light); }
    .lm-dot { width:7px; height:7px; border-radius:50%; background:var(--success); }
    .lm-dot.warn { background:#D97706; }
    .lm-status { font-size:.8rem; color:var(--gray-500); }
    .lm-status.err { color:var(--error); }
    .lm-meta { font-size:.8rem; color:var(--gray-600); margin-top:.35rem; display:flex; flex-wrap:wrap; gap:.35rem; }
    .lm-tag { background:var(--gray-100); border:1px solid var(--gray-200); border-radius:4px; padding:.05rem .4rem; }
    .lm-tag.ok { background:var(--success-light); border-color:var(--success-border); color:#166534; }
    .lm-tag.warn { background:#FFFBEB; border-color:#FDE68A; color:#92400E; }
    .lm-check { display:flex; gap:.5rem; align-items:flex-start; font-weight:500; margin-top:.9rem; cursor:pointer; }
    .lm-check input { margin-top:.2rem; }
    .lm-more { margin-top:1rem; border-top:1px solid var(--gray-200); padding-top:.5rem; }
    .lm-more summary { cursor:pointer; font-size:.88rem; font-weight:600; color:var(--gray-700); padding:.35rem 0; }
    .lm-grid { display:grid; grid-template-columns:1fr 1fr; gap:0 .75rem; }
    @media (max-width:560px) { .lm-grid { grid-template-columns:1fr; } .mode-toggle { flex-wrap:wrap; } }
  `;

  const fieldsHtml = `
    <div class="mode-description" id="lm-description" style="display:none;">
      Run the reviewer against a model served on this machine — Ollama, LM Studio, oMLX, Splash, mlx-serve,
      mlx_lm, llama.cpp, vLLM, Jan, LocalAI or any OpenAI-compatible server. No email or cloud keys required;
      the paper text is extracted offline unless you add a Mistral key below.
    </div>
    <div id="lm-fields" style="display:none;">
      <label>Running servers</label>
      <div class="lm-servers" id="lm-servers"><span class="lm-status">Scanning…</span></div>

      <label for="lm-backend">Backend <span class="required">*</span></label>
      <div class="lm-row">
        <select id="lm-backend"></select>
        <button type="button" class="btn btn-secondary btn-sm" id="lm-scan" title="Scan default ports again">Scan</button>
      </div>
      <div class="field-hint" id="lm-backend-hint"></div>

      <label for="lm-url">Base URL <span class="required">*</span></label>
      <input type="text" id="lm-url" placeholder="http://127.0.0.1:11434" autocomplete="off" spellcheck="false">

      <label for="lm-key">API key <span class="optional">(optional)</span></label>
      <input type="password" id="lm-key" placeholder="Only if your server requires one" autocomplete="off">
      <div class="field-hint" id="lm-key-hint">Leave blank to use a key from the server's environment (e.g. OMLX_API_KEY) or oMLX's own settings.</div>

      <label for="lm-model">Model <span class="required">*</span></label>
      <input type="text" id="lm-filter" placeholder="Filter models…" style="display:none;margin-bottom:.4rem;" autocomplete="off">
      <div class="lm-row">
        <select id="lm-model"><option value="">— choose a server first —</option></select>
        <button type="button" class="btn btn-secondary btn-sm" id="lm-refresh" title="Reload the model list">Refresh</button>
      </div>
      <div class="lm-meta" id="lm-model-meta"></div>
      <div class="lm-status" id="lm-models-status"></div>
      <label class="lm-check"><input type="checkbox" id="lm-show-all"> Show embedding, speech and other non-chat models</label>

      <div class="lm-grid">
        <div>
          <label for="lm-ctx">Context window (tokens)</label>
          <input type="number" id="lm-ctx" min="16384" step="1024" placeholder="server default">
          <div class="field-hint" id="lm-ctx-hint">At least 16,384. The agent reads the whole paper, so 64k+ works best.</div>
        </div>
        <div>
          <label for="lm-maxout">Max output tokens</label>
          <input type="number" id="lm-maxout" min="512" step="512" placeholder="auto">
          <div class="field-hint">Auto: a quarter of the context, capped at 16k.</div>
        </div>
      </div>

      <label class="lm-check"><input type="checkbox" id="lm-tools" checked>
        <span>Native tool calling <span class="optional">— untick for models without tool support (prompt-based fallback)</span></span></label>

      <details class="lm-more">
        <summary>More options</summary>
        <div class="lm-grid">
          <div>
            <label for="lm-temp">Temperature</label>
            <input type="number" id="lm-temp" min="0" max="2" step="0.05" placeholder="server default">
          </div>
          <div>
            <label for="lm-email">Email <span class="optional">(optional)</span></label>
            <input type="email" id="lm-email" placeholder="only if SMTP is configured">
          </div>
        </div>
        <label for="lm-tavily">Tavily API key <span class="optional">(optional — literature search)</span></label>
        <input type="password" id="lm-tavily" placeholder="Leave blank to review without web search" autocomplete="off">
        <div class="field-hint">Web search noticeably improves reviews, but sends search queries to Tavily.</div>
        <label for="lm-mistral">Mistral API key <span class="optional">(optional — cloud OCR)</span></label>
        <input type="password" id="lm-mistral" placeholder="Leave blank for offline text extraction" autocomplete="off">
        <div class="field-hint">Offline extraction keeps the PDF on this Mac but flattens equations and tables; Mistral OCR uploads the PDF to Mistral.</div>
      </details>
    </div>`;

  // ─── State ──────────────────────────────────────────────────────────────────
  let backends = [];
  let servers = [];
  let models = [];
  let minCtx = 16384;
  let listSeq = 0;
  let defaults = {};      // LOCAL_DEFAULT_* from the server's .env
  const saved = load();
  // Model to preselect when the list arrives: the last one used here, else the server default.
  const preferredModel = () => saved.model || defaults.model || "";

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); } catch (_) { return {}; }
  }
  function save() {
    const s = {
      backend: $("lm-backend").value, base_url: $("lm-url").value.trim(), model: $("lm-model").value,
      ctx: $("lm-ctx").value, maxout: $("lm-maxout").value, tools: $("lm-tools").checked,
      temp: $("lm-temp").value, email: $("lm-email").value.trim(), active: isLocalMode(),
    };
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (_) { /* private mode */ }
  }

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const api = (path) => `${typeof API_BASE_URL === "string" ? API_BASE_URL : window.location.origin}${path}`;
  const isLocalMode = () => $("mode") && $("mode").value === "local";
  const fmtCtx = (n) => (n >= 1024 ? `${Math.round(n / 1024)}k` : String(n));
  const fmtSize = (b) => (b ? `${(b / 1e9).toFixed(b > 1e10 ? 0 : 1)} GB` : "");
  const backendById = (id) => backends.find((b) => b.id === id) || { id, label: id, default_url: "" };

  // ─── DOM injection (runs immediately, before upload.js) ─────────────────────
  function inject() {
    const toggle = document.querySelector(".mode-toggle");
    const byok = $("byok-fields");
    if (!toggle || !byok) { console.warn("[local-models] upload form layout changed; local mode not added."); return false; }

    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const pill = document.createElement("button");
    pill.className = "mode-pill";
    pill.dataset.mode = "local";
    pill.type = "button";
    pill.textContent = "Local Models (this Mac)";
    toggle.appendChild(pill);

    byok.insertAdjacentHTML("afterend", fieldsHtml);
    return true;
  }

  function showLocal(on) {
    $("lm-fields").style.display = on ? "" : "none";
    $("lm-description").style.display = on ? "" : "none";
  }

  // ─── Backends, detection, models ────────────────────────────────────────────
  async function loadBackends() {
    const r = await fetch(api("/api/local/backends"));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    backends = data.backends;
    minCtx = data.min_context_tokens || minCtx;
    defaults = data.defaults || {};
    renderBackendSelect();
  }

  function renderBackendSelect() {
    const sel = $("lm-backend");
    const current = sel.value;
    const running = new Set(servers.map((s) => s.backend));
    sel.innerHTML = backends.map((b) =>
      `<option value="${esc(b.id)}">${running.has(b.id) ? "● " : ""}${esc(b.label)}${b.apple_silicon_only ? " (Apple silicon)" : ""}</option>`
    ).join("");
    if (current) sel.value = current;
  }

  function updateBackendHint() {
    const b = backendById($("lm-backend").value);
    const parts = [];
    if (b.notes) parts.push(esc(b.notes).replace(/`([^`]+)`/g, "<code>$1</code>"));
    if (b.homepage) parts.push(`<a href="${esc(b.homepage)}" target="_blank" rel="noopener">Docs</a>`);
    $("lm-backend-hint").innerHTML = parts.join(" ");
    $("lm-url").placeholder = b.default_url || "http://127.0.0.1:8000/v1";
  }

  async function scan() {
    const box = $("lm-servers");
    box.innerHTML = `<span class="lm-status">Scanning default ports…</span>`;
    try {
      const r = await fetch(api("/api/local/detect"));
      servers = r.ok ? (await r.json()).servers : [];
    } catch (_) { servers = []; }
    renderBackendSelect();
    renderServers();
    return servers;
  }

  function renderServers() {
    const box = $("lm-servers");
    if (!servers.length) {
      box.innerHTML = `<span class="lm-status">No server found on the usual ports. Start one (e.g. <code>ollama serve</code>, LM Studio's server, oMLX) and click Scan, or enter its URL below.</span>`;
      return;
    }
    const activeUrl = $("lm-url").value.trim();
    box.innerHTML = servers.map((s, i) => {
      const b = backendById(s.backend);
      const locked = s.needs_key && !s.has_server_key;
      const guess = s.identified ? "" : " ?";
      return `<button type="button" class="lm-chip${s.base_url === activeUrl ? " active" : ""}" data-i="${i}"
        title="${esc(s.base_url)}${s.candidates.length > 1 && !s.identified ? " — could also be: " + esc(s.candidates.join(", ")) : ""}">
        <span class="lm-dot${locked ? " warn" : ""}"></span>${esc(s.is_default && defaults.label ? defaults.label : b.label)}${s.is_default && defaults.label ? "" : guess} · ${esc(s.base_url.replace(/^https?:\/\//, ""))}${s.is_default ? " · default" : ""}${locked ? " · needs key" : ""}</button>`;
    }).join("");
    box.querySelectorAll(".lm-chip").forEach((chip) =>
      chip.addEventListener("click", () => pickServer(servers[Number(chip.dataset.i)])));
  }

  function pickServer(s) {
    $("lm-backend").value = s.backend;
    $("lm-url").value = s.base_url;
    $("lm-ctx").value = ""; // re-derived from the new server's model list
    updateBackendHint();
    renderServers();
    listModels();
  }

  async function listModels() {
    const seq = ++listSeq;
    const status = $("lm-models-status");
    const sel = $("lm-model");
    status.className = "lm-status";
    status.textContent = "Loading models…";
    let data;
    try {
      const r = await fetch(api("/api/local/models"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend: $("lm-backend").value, base_url: $("lm-url").value.trim() || null, api_key: $("lm-key").value.trim() || null }),
      });
      data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    } catch (err) {
      if (seq !== listSeq) return;
      models = [];
      sel.innerHTML = `<option value="">— unavailable —</option>`;
      status.className = "lm-status err";
      status.textContent = `Could not list models: ${err.message}`;
      updateMeta(); revalidate();
      return;
    }
    if (seq !== listSeq) return; // a newer request superseded this one

    if (!$("lm-url").value.trim() && data.base_url) $("lm-url").value = data.base_url;
    $("lm-key-hint").textContent = data.has_server_key
      ? "A key for this server was found on the backend (env var or oMLX settings) — you can leave this blank."
      : "Leave blank to use a key from the server's environment (e.g. OMLX_API_KEY) or oMLX's own settings.";

    models = data.models || [];
    if (data.error) {
      status.className = "lm-status err";
      status.textContent = data.error + (data.needs_key ? " Enter it above, then Refresh." : "");
    } else {
      const chat = models.filter((m) => m.kind === "chat").length;
      const loaded = models.filter((m) => m.loaded).length;
      status.className = "lm-status";
      status.textContent = `${chat} chat model${chat === 1 ? "" : "s"}${models.length > chat ? ` (+${models.length - chat} other)` : ""}` +
        (loaded ? ` · ${loaded} loaded in memory` : "");
    }
    renderModels();
  }

  function renderModels() {
    const sel = $("lm-model");
    const prev = sel.value || preferredModel();
    const showAll = $("lm-show-all").checked;
    const q = $("lm-filter").value.trim().toLowerCase();
    const visible = models.filter((m) => (showAll || m.kind === "chat") && (!q || m.id.toLowerCase().includes(q)));
    $("lm-filter").style.display = models.length > 12 ? "" : "none";

    if (!visible.length) {
      sel.innerHTML = `<option value="">${models.length ? "— no models match —" : "— no models —"}</option>`;
    } else {
      sel.innerHTML = `<option value="">— choose a model —</option>` + visible.map((m) => {
        const bits = [m.context_length ? `${fmtCtx(m.context_length)} ctx` : "", m.loaded ? "loaded" : "", fmtSize(m.size_bytes), m.kind !== "chat" ? m.kind : ""]
          .filter(Boolean).join(" · ");
        return `<option value="${esc(m.id)}">${esc(m.id)}${bits ? "  —  " + esc(bits) : ""}</option>`;
      }).join("");
      if (prev && visible.some((m) => m.id === prev)) sel.value = prev;
      else if (visible.length === 1) sel.value = visible[0].id;
    }
    onModelChange(false);
  }

  function selectedModel() {
    return models.find((m) => m.id === $("lm-model").value) || null;
  }

  function onModelChange(userAction) {
    const m = selectedModel();
    const ctx = $("lm-ctx");
    if (m && userAction !== false) {
      // New model picked: default the context to what the server reports.
      ctx.value = m.context_length ? String(defaultCtx(m)) : "";
      if (m.supports_tools === false) $("lm-tools").checked = false;
      else if (m.supports_tools === true) $("lm-tools").checked = true;
    } else if (m && !ctx.value) {
      // A remembered window can outgrow the model if a stable alias was
      // re-pointed (e.g. 256k Qwen → 32k DeepSeek), so clamp it.
      if (saved.model === m.id && saved.ctx) ctx.value = String(m.context_length ? Math.min(Number(saved.ctx), m.context_length) : saved.ctx);
      else if (!saved.model && defaults.model === m.id && defaults.context_length) ctx.value = String(defaults.context_length);
      else if (m.context_length) ctx.value = String(defaultCtx(m));
    }
    updateMeta();
    revalidate();
  }

  function defaultCtx(m) {
    // Ollama allocates the KV cache for num_ctx up front, so don't default to a
    // 256k window there; OpenAI-style servers enforce their own served window.
    if ($("lm-backend").value === "ollama") return Math.min(m.context_length, 32768);
    return m.context_length;
  }

  function updateMeta() {
    const m = selectedModel();
    const box = $("lm-model-meta");
    if (!m) { box.innerHTML = ""; return; }
    const tags = [];
    if (m.context_length) tags.push(`<span class="lm-tag${m.context_length < minCtx ? " warn" : ""}">max ${m.context_length.toLocaleString()} tokens</span>`);
    if (m.loaded === true) tags.push(`<span class="lm-tag ok">loaded</span>`);
    if (m.loaded === false) tags.push(`<span class="lm-tag">loads on first request</span>`);
    if (m.supports_tools === true) tags.push(`<span class="lm-tag ok">tools</span>`);
    if (m.supports_tools === false) tags.push(`<span class="lm-tag warn">no tool support reported</span>`);
    if (m.supports_vision) tags.push(`<span class="lm-tag">vision</span>`);
    if (m.size_bytes) tags.push(`<span class="lm-tag">${fmtSize(m.size_bytes)}</span>`);
    if (m.details) tags.push(`<span class="lm-tag">${esc(m.details)}</span>`);
    box.innerHTML = tags.join("");
  }

  function ctxProblem() {
    const v = $("lm-ctx").value.trim();
    if (!v) return null;
    const n = Number(v);
    if (!Number.isFinite(n) || n < minCtx) return `Context must be at least ${minCtx.toLocaleString()} tokens.`;
    return null;
  }

  function revalidate() {
    const problem = ctxProblem();
    const hint = $("lm-ctx-hint");
    hint.style.color = problem ? "var(--error)" : "";
    hint.textContent = problem || `At least ${minCtx.toLocaleString()}. The agent reads the whole paper, so 64k+ works best.`;
    if (typeof updateSubmitButton === "function") updateSubmitButton();
  }

  function localReady() {
    return !!$("lm-backend").value && !!$("lm-url").value.trim() && !!$("lm-model").value && !ctxProblem();
  }

  // ─── Upload (replaces performUpload for mode=local) ─────────────────────────
  function localModelChoice() {
    const num = (id) => { const v = $(id).value.trim(); return v ? Number(v) : null; };
    return {
      backend: $("lm-backend").value,
      base_url: $("lm-url").value.trim(),
      model: $("lm-model").value,
      context_length: num("lm-ctx"),
      max_output_tokens: num("lm-maxout"),
      temperature: num("lm-temp"),
      native_tool_calling: $("lm-tools").checked,
    };
  }

  async function performLocalUpload() {
    submitBtn.disabled = true;
    submitBtn.textContent = "Uploading...";
    save();

    const formData = new FormData();
    formData.append("mode", "local");
    formData.append("file", selectedFile);
    const email = $("lm-email").value.trim();
    if (email) formData.append("email", email);
    const key = $("lm-key").value.trim();
    if (key) formData.append("user_litellm_api_key", key);
    const tavily = $("lm-tavily").value.trim();
    if (tavily) formData.append("user_tavily_api_key", tavily);
    const mistral = $("lm-mistral").value.trim();
    if (mistral) formData.append("user_mistral_api_key", mistral);

    const focusArea = $("focus-area") ? $("focus-area").value.trim() : "";
    if (focusArea) reviewSettings.focus_area = focusArea;
    if (codeInput.files.length > 0) formData.append("code_file", codeInput.files[0]);
    if (suppInput.files.length > 0) formData.append("supplementary_file", suppInput.files[0]);
    formData.append("review_settings", JSON.stringify({ ...reviewSettings, local_model: localModelChoice() }));

    try {
      const resp = await fetch(api("/api/submit"), { method: "POST", body: formData });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `Submission failed (HTTP ${resp.status}).`);
      const k = esc(data.key);
      showMessage("success",
        `<strong>Submitted!</strong> Reviewing with <code>${esc($("lm-model").value)}</code> on ${esc(backendById($("lm-backend").value).label)}.
         <div class="key-display"><span>${k}</span><button class="copy-btn" onclick="copyToClipboard('${k}')" title="Copy key">Copy</button></div>
         <p>Follow progress on the <a href="review.html?key=${k}">review page</a>. Local models are slower than the cloud —
         expect anywhere from several minutes to an hour depending on the model and your Mac.</p>`);
    } catch (err) {
      showMessage("error", `<strong>Error:</strong> ${esc(err.message)}`);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit Paper";
      updateSubmitButton();
    }
  }

  // ─── Wire-up after upload.js ────────────────────────────────────────────────
  function wireUp() {
    if (!HAS_UPSTREAM()) {
      console.error("[local-models] upload.js no longer exposes updateSubmitButton/performUpload/showMessage; local mode disabled.");
      document.querySelector('.mode-pill[data-mode="local"]')?.remove();
      return;
    }

    const upstreamUpdate = window.updateSubmitButton;
    const upstreamUpload = window.performUpload;
    const upstreamConsent = window.showConsentModal;
    window.updateSubmitButton = function () {
      if (!isLocalMode()) return upstreamUpdate.apply(this, arguments);
      submitBtn.disabled = !selectedFile || !localReady();
    };
    window.performUpload = function () {
      if (!isLocalMode()) return upstreamUpload.apply(this, arguments);
      return performLocalUpload();
    };
    if (typeof upstreamConsent === "function") {
      // The consent text is about the hosted service's public dataset; local
      // runs never leave this machine, so skip straight to the upload.
      window.showConsentModal = function (onConsent) {
        if (isLocalMode()) return onConsent();
        return upstreamConsent.apply(this, arguments);
      };
    }

    document.querySelectorAll(".mode-pill").forEach((p) =>
      p.addEventListener("click", () => { showLocal(p.dataset.mode === "local"); save(); updateSubmitButton(); }));

    $("lm-backend").addEventListener("change", () => {
      const b = backendById($("lm-backend").value);
      const detected = servers.find((s) => s.backend === b.id);
      $("lm-url").value = detected ? detected.base_url : b.default_url || "";
      $("lm-ctx").value = "";
      updateBackendHint(); renderServers(); listModels();
    });
    let urlTimer;
    $("lm-url").addEventListener("input", () => { clearTimeout(urlTimer); urlTimer = setTimeout(() => { renderServers(); listModels(); }, 600); revalidate(); });
    $("lm-key").addEventListener("change", listModels);
    $("lm-refresh").addEventListener("click", listModels);
    $("lm-scan").addEventListener("click", scan);
    $("lm-model").addEventListener("change", () => { onModelChange(true); save(); });
    $("lm-filter").addEventListener("input", renderModels);
    $("lm-show-all").addEventListener("change", renderModels);
    ["lm-ctx", "lm-maxout", "lm-temp", "lm-email"].forEach((id) => $(id).addEventListener("input", () => { revalidate(); save(); }));
    $("lm-tools").addEventListener("change", save);

    init();
  }

  async function init() {
    if (saved.maxout) $("lm-maxout").value = saved.maxout;
    if (saved.temp) $("lm-temp").value = saved.temp;
    if (saved.email) $("lm-email").value = saved.email;
    if (typeof saved.tools === "boolean") $("lm-tools").checked = saved.tools;

    try {
      await loadBackends();
    } catch (err) {
      $("lm-servers").innerHTML = `<span class="lm-status err">This backend has no /api/local endpoints (${esc(err.message)}). Start it with ./run_local.sh.</span>`;
      return;
    }
    await scan();

    // Prefer the last-used server if it's still up, then the configured
    // default (LOCAL_DEFAULT_*), then the first detected one.
    const last = saved.backend && servers.find((s) => s.backend === saved.backend && s.base_url === saved.base_url);
    const dflt = servers.find((s) => s.is_default);
    const pick = last || dflt || servers[0];
    if (pick) {
      pickServer(pick);
    } else {
      // Nothing answered: still preselect the configured default so a Refresh
      // after starting the server is all it takes.
      $("lm-backend").value = saved.backend || defaults.backend || "ollama";
      $("lm-url").value = saved.base_url || defaults.base_url || backendById($("lm-backend").value).default_url || "";
      updateBackendHint();
      if ($("lm-url").value) listModels();
    }

    // Open in local mode by default when served by the local app.
    if (saved.active !== false) document.querySelector('.mode-pill[data-mode="local"]')?.click();
  }

  if (inject()) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireUp);
    else wireUp();
  }
})();
