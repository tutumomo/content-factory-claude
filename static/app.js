"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const main = $("#main");
let META = null;
let pollTimer = null;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  if (!r.ok) throw new Error(data?.detail || text || r.statusText);
  return data;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 3500); }
const file = (p) => `/files/${p}?t=${Date.now() >> 12}`;
const fmtName = (f) => (f === "long" ? "長片" : "短片");
const when = (t) => new Date(t * 1000).toLocaleString("zh-TW", { hour12: false });

function statusPill(ep) {
  if (ep.status === "waiting") return `<span class="pill waiting">等你：${esc(META.wait_label[ep.waiting_for])}</span>`;
  const map = { queued: "排隊中", running: "agent 處理中", done: "已核准", error: "出錯" };
  return `<span class="pill ${ep.status}">${map[ep.status] || ep.status}</span>`;
}
function stepper(ep) {
  const i = META.stages.indexOf(ep.stage);
  return `<div class="steps">${META.stages.map((s, k) =>
    `<span class="${k < i || ep.status === "done" ? "done" : k === i ? "cur" : ""}">${META.stage_label[s]}</span>`).join("")}</div>`;
}

// ---------- status bar ----------
async function refreshStatus() {
  try {
    const [h, eps] = await Promise.all([api("/api/health"), api("/api/episodes")]);
    const waiting = eps.filter((e) => e.status === "waiting").length;
    $("#badge-review").textContent = waiting || "";
    const cur = h.worker.current?.kind ? (h.worker.current.kind === "radar" ? "雷達掃描中" : "處理一集中") : "閒置";
    $("#status").innerHTML = `<div><span class="dot ${h.tts.ok ? "ok" : "bad"}"></span>配音 <b>${h.tts.ok ? "就緒" : "未就緒"}</b></div>
      <div><span class="dot ok"></span>LLM <b>${esc({ claude_cli: "Claude CLI", openai: "OpenAI 相容", mock: "示範模式" }[h.provider])}</b></div>
      <div>agent：<b>${cur}</b>${h.worker.queued ? `（排隊 ${h.worker.queued}）` : ""}</div>`;
  } catch { /* server restarting */ }
}

// ---------- views ----------
const views = {};

views.review = async () => {
  const eps = await api("/api/episodes");
  const w = eps.filter((e) => e.status === "waiting");
  const err = eps.filter((e) => e.status === "error");
  const run = eps.filter((e) => ["running", "queued"].includes(e.status));
  main.innerHTML = `<h1>審核區</h1><p class="sub">agent 做好、等你決定的東西都在這裡。你只需要挑、退件或按核准。</p>
    ${w.length ? w.map(item).join("") : `<div class="card empty">目前沒有等你決定的項目。</div>`}
    ${err.length ? `<h2>出錯的集數</h2>${err.map(item).join("")}` : ""}
    ${run.length ? `<h2>agent 正在做</h2>${run.map(item).join("")}` : ""}`;
  function item(e) {
    return `<a class="card queue-item" href="#/ep/${encodeURIComponent(e.id)}" style="text-decoration:none">
      <div class="grow"><div class="row"><b>${esc(e.topic)}</b><span class="pill">${fmtName(e.format)}</span>${statusPill(e)}</div>
      <div class="muted">${esc(META.stage_label[e.stage])}・更新於 ${when(e.updated)}${e.error ? "・" + esc(e.error).slice(0, 120) : ""}</div></div>
      <span class="btn">${e.status === "waiting" ? "去決定 →" : "查看 →"}</span></a>`;
  }
};

views.episodes = async () => {
  const eps = await api("/api/episodes");
  main.innerHTML = `<div class="row"><h1 class="grow">集數</h1><a class="btn primary" href="#/new">＋ 做一支新的</a></div>
    <p class="sub">每一支內容的進度與成品。</p>
    ${eps.length ? eps.map((e) => `<a class="card row" href="#/ep/${encodeURIComponent(e.id)}" style="text-decoration:none">
      <div class="grow"><b>${esc(e.package_choice?.title || e.topic)}</b><div class="muted">${when(e.created)}・${esc(META.stage_label[e.stage])}</div></div>
      <span class="pill">${fmtName(e.format)}</span>${statusPill(e)}</a>`).join("") : `<div class="card empty">還沒有集數。先到「選題雷達」找題目，或直接「做一支新的」。</div>`}`;
};

views.new = async (params) => {
  const topic = params.get("topic") || "";
  const fmt = params.get("format") || "short";
  const ch = await api("/api/channel");
  main.innerHTML = `<h1>做一支新的</h1><p class="sub">給題目就好，後面 agent 會自己動起來，到需要你決定時會出現在審核區。</p>
    ${!ch.name ? `<div class="warn">還沒填頻道定位。agent 會不知道觀眾是誰、該用什麼語氣。<a href="#/channel">先去填 →</a></div>` : ""}
    <div class="card">
      <label>題目</label><input id="n-topic" value="${esc(topic)}" placeholder="例如：黃仁勳回應 AI 泡沫">
      <label>格式</label><select id="n-format"><option value="short">短片（直式 30–90 秒）</option><option value="long">長片（橫式 3–8 分鐘）</option></select>
      <label>參考連結（一行一個；官方公告、對標影片頁、社群討論）</label><textarea id="n-urls" placeholder="https://..."></textarea>
      <label>你的觀點與想強調的點（選填）</label><textarea id="n-notes" placeholder="身為觀眾，我最好奇的是…；這些不要講…"></textarea>
      <div class="row" style="margin-top:14px"><button class="btn primary" id="n-go">開始</button></div>
    </div>`;
  $("#n-format").value = fmt;
  $("#n-go").onclick = async () => {
    try {
      const ep = await api("/api/episodes", { method: "POST", body: {
        topic: $("#n-topic").value, format: $("#n-format").value, notes: $("#n-notes").value,
        source_urls: $("#n-urls").value.split("\n") } });
      location.hash = `#/ep/${encodeURIComponent(ep.id)}`;
    } catch (e) { toast(e.message); }
  };
};

views.radar = async () => {
  const items = await api("/api/radar");
  main.innerHTML = `<h1>選題雷達</h1><p class="sub">貼上線索（對標帳號熱門影片、官方公告、社群熱門貼文的連結或筆記），agent 整理成候選題目。挑一個就能開做。</p>
    <div class="card"><label>線索</label><textarea id="r-seeds" placeholder="https://...&#10;最近大家在討論…"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="r-go">掃描</button><span class="muted">掃描在背景跑，好了會出現在下面。</span></div></div>
    <h2>候選題目</h2>
    ${items.length ? items.map((t, i) => `<div class="card row"><div class="grow"><b>${esc(t.title)}</b>
      <div class="muted">${esc(t.why)}</div><div class="muted">來源：${esc(t.source)}・熱度：${esc(t.heat)}</div></div>
      <span class="pill">${fmtName(t.format)}</span>
      <a class="btn primary" href="#/new?topic=${encodeURIComponent(t.title)}&format=${t.format === "long" ? "long" : "short"}">做這個</a>
      <button class="btn danger" data-del="${i}">略過</button></div>`).join("") : `<div class="card empty">還沒有候選題目。</div>`}`;
  $("#r-go").onclick = async () => {
    try { await api("/api/radar/scan", { method: "POST", body: { seeds: $("#r-seeds").value } }); toast("已開始掃描"); $("#r-seeds").value = ""; }
    catch (e) { toast(e.message); }
  };
  $$("[data-del]").forEach((b) => (b.onclick = async () => { await api(`/api/radar/${b.dataset.del}`, { method: "DELETE" }); route(); }));
};

const PREF_CATS = ["選題", "方向與觀點", "講稿語氣", "開頭與節奏", "畫面風格", "標題", "縮圖", "配音與字幕"];
views.prefs = async () => {
  let prefs = await api("/api/preferences");
  const draw = () => {
    main.innerHTML = `<h1>品味紀錄</h1><p class="sub">每次退件，系統把你的意見變成一條規則寫在這裡，之後每一步都會遵守。這是讓它「越來越像你」的地方。</p>
      <div class="card">${prefs.map((p, i) => `<div class="pref">
        <select data-i="${i}" data-k="category">${PREF_CATS.map((c) => `<option ${c === p.category ? "selected" : ""}>${c}</option>`).join("")}</select>
        <input data-i="${i}" data-k="rule" value="${esc(p.rule)}"><span class="date">${esc(p.date)}</span>
        <button class="btn danger" data-rm="${i}">刪</button></div>`).join("")}
        <div class="row" style="margin-top:12px"><button class="btn" id="p-add">＋ 新增</button><button class="btn primary" id="p-save">儲存</button></div></div>`;
    $$("[data-k]").forEach((el) => (el.oninput = () => (prefs[el.dataset.i][el.dataset.k] = el.value)));
    $$("[data-rm]").forEach((b) => (b.onclick = () => { prefs.splice(+b.dataset.rm, 1); draw(); }));
    $("#p-add").onclick = () => { prefs.push({ category: "講稿語氣", rule: "", date: new Date().toISOString().slice(0, 10) }); draw(); };
    $("#p-save").onclick = async () => { prefs = await api("/api/preferences", { method: "PUT", body: prefs.filter((p) => p.rule.trim()) }); toast("已儲存"); draw(); };
  };
  draw();
};

views.channel = async () => {
  const c = await api("/api/channel");
  const f = (k, label, ph, ta) => `<label>${label}</label>${ta ? `<textarea id="c-${k}" placeholder="${esc(ph)}">${esc(c[k])}</textarea>` : `<input id="c-${k}" value="${esc(c[k])}" placeholder="${esc(ph)}">`}`;
  main.innerHTML = `<h1>頻道定位</h1><p class="sub">agent 每一步都會讀這裡：觀眾是誰、用什麼語氣、對標誰、哪些不碰。</p><div class="card">
    ${f("name", "頻道名稱", "例如：AI 懶人包")}${f("topic", "主題", "例如：每天 AI 新聞與工具")}
    ${f("audience", "目標觀眾", "例如：想跟上 AI 但沒時間的上班族", true)}${f("tone", "語氣", "例如：口語、輕鬆、有觀點但不浮誇")}
    ${f("benchmarks", "對標帳號（平台＋連結）", "", true)}${f("taboo", "禁區（不碰的題材、不用的說法）", "", true)}
    <label>發布平台</label><input id="c-platforms" value="${esc((c.platforms || []).join(", "))}">
    <div class="row" style="margin-top:14px"><button class="btn primary" id="c-save">儲存</button></div></div>`;
  $("#c-save").onclick = async () => {
    const body = { ...c };
    for (const k of ["name", "topic", "audience", "tone", "benchmarks", "taboo"]) body[k] = $(`#c-${k}`).value;
    body.platforms = $("#c-platforms").value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    await api("/api/channel", { method: "PUT", body }); toast("已儲存");
  };
};

views.settings = async () => {
  const s = await api("/api/settings");
  main.innerHTML = `<h1>系統設定</h1><p class="sub">選用哪個模型寫稿、哪個聲音配音。</p>
    <div class="card"><h2 style="margin-top:0">LLM（寫簡報、講稿、審稿、包裝）</h2>
      <label>提供者</label><select id="s-provider"><option value="claude_cli">Claude CLI（claude -p，用你的 Claude Code 登入）</option>
      <option value="openai">OpenAI 相容端點（LM Studio／Strata／其他）</option><option value="mock">示範模式（不呼叫模型，只用來測流程）</option></select>
      <label>Claude 模型（留空用預設）</label><input id="s-claude_model" value="${esc(s.llm.claude_model)}" placeholder="例如 opus、sonnet">
      <label>OpenAI 相容 base URL</label><input id="s-openai_base_url" value="${esc(s.llm.openai_base_url)}">
      <label>模型名稱</label><input id="s-openai_model" value="${esc(s.llm.openai_model)}">
      <label>API key 的環境變數名稱（只填名稱，不要填金鑰）</label><input id="s-openai_key_env" value="${esc(s.llm.openai_key_env)}" placeholder="例如 STRATA_API_KEY">
      <div class="row" style="margin-top:12px"><button class="btn" id="s-test">測試 LLM 連線</button><span class="muted" id="s-test-out"></span></div>
      <div class="warn" style="margin-top:12px">LM Studio、Strata、ComfyUI 共用同一塊 GPU 記憶體，不要同時載入大模型。</div></div>
    <div class="card"><h2 style="margin-top:0">配音（audio.cpp）</h2>
      <label>audio.cpp 伺服器</label><input id="t-base_url" value="${esc(s.tts.base_url)}">
      <label>TTS 模型 id</label><input id="t-model" value="${esc(s.tts.model)}">
      <label>聲音</label><select id="t-voice">${["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"].map((v) => `<option ${v === s.tts.voice ? "selected" : ""}>${v}</option>`).join("")}</select>
      <label>語氣指示</label><input id="t-instruct" value="${esc(s.tts.instruct)}">
      <label>字幕對齊模型 id（留空改用字數估算）</label><input id="t-align_model" value="${esc(s.tts.align_model)}"></div>
    <div class="card"><h2 style="margin-top:0">流程</h2>
      <label><input type="checkbox" id="p-review_script" style="width:auto" ${s.pipeline.review_script ? "checked" : ""}> 講稿定稿前先給我看（初期建議開著；穩定後可關掉放手）</label>
      <label>審稿通過門檻（每個角色至少幾分）</label><input id="p-critique_threshold" type="number" min="1" max="10" value="${s.pipeline.critique_threshold}">
      <label>最多修稿幾輪</label><input id="p-critique_max_rounds" type="number" min="1" max="6" value="${s.pipeline.critique_max_rounds}">
      <label>標題候選數</label><input id="p-title_count" type="number" min="2" max="12" value="${s.pipeline.title_count}">
      <label>縮圖候選數</label><input id="p-thumbnail_count" type="number" min="2" max="8" value="${s.pipeline.thumbnail_count}"></div>
    <button class="btn primary" id="s-save">儲存設定</button>`;
  $("#s-provider").value = s.llm.provider;
  const collect = () => {
    for (const k of ["provider", "claude_model", "openai_base_url", "openai_model", "openai_key_env"]) s.llm[k] = $(`#s-${k}`).value;
    for (const k of ["base_url", "model", "voice", "instruct", "align_model"]) s.tts[k] = $(`#t-${k}`).value;
    s.pipeline.review_script = $("#p-review_script").checked;
    for (const k of ["critique_threshold", "critique_max_rounds", "title_count", "thumbnail_count"]) s.pipeline[k] = +$(`#p-${k}`).value;
    return s;
  };
  $("#s-save").onclick = async () => { await api("/api/settings", { method: "PUT", body: collect() }); toast("已儲存"); refreshStatus(); };
  $("#s-test").onclick = async () => {
    await api("/api/settings", { method: "PUT", body: collect() });
    $("#s-test-out").textContent = "測試中…";
    const h = await api("/api/health?llm_check=true");
    $("#s-test-out").textContent = (h.llm.ok ? "✓ " : "✗ ") + h.llm.detail;
  };
};

// ---------- episode detail ----------
views.ep = async (params, id) => {
  const ep = await api(`/api/episodes/${encodeURIComponent(id)}`);
  const F = ep.files;
  const vertical = ep.format === "short";
  let html = `<div class="row"><h1 class="grow">${esc(ep.package_choice?.title || ep.topic)}</h1><span class="pill">${fmtName(ep.format)}</span>${statusPill(ep)}</div>
    ${stepper(ep)}`;
  if (ep.status === "error") html += `<div class="card" style="border-color:var(--bad)"><b>出錯了</b><div class="muted">${esc(ep.error)}</div>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="retry">重試這一步</button></div></div>`;
  if (["running", "queued"].includes(ep.status)) html += `<div class="card muted">agent 正在「${esc(META.stage_label[ep.stage])}」。你可以先去做別的事，好了會出現在審核區。</div>`;

  // ---- gates ----
  if (ep.status === "waiting" && ep.waiting_for === "direction") html += gateDirection(F.brief);
  if (ep.status === "waiting" && ep.waiting_for === "script") html += gateScript(F.script, F.critique);
  if (ep.status === "waiting" && ep.waiting_for === "package") html += gatePackage(F.package, vertical, ep.video);
  if (ep.status === "waiting" && ep.waiting_for === "approval") html += gateApproval(ep, F, vertical);

  // ---- finished work ----
  if (ep.status === "done") {
    html += `<div class="card"><h2 style="margin-top:0">已核准</h2>
      <div class="muted">發布包：<code>${esc(ep.published_dir)}</code>（影片、縮圖、字幕、說明欄、輪播圖卡、metadata.json）${ep.schedule ? `・排程 ${esc(ep.schedule)}` : ""}</div>
      <div class="muted">目前沒有串各平台的上傳 API，請用發布包手動上傳或交給你的排程工具。</div></div>`;
    html += videoBlock(ep, vertical) + packageSummary(F.package, ep) + metricsBlock(ep);
  }
  if (ep.direction && ep.waiting_for !== "direction") html += `<details class="card"><summary><b>選定方向</b>：${esc(ep.direction.angle)}</summary>
    <ul>${(ep.direction.outline || []).map((o) => `<li>${esc(o)}</li>`).join("")}</ul>${ep.direction_notes ? `<div class="muted">你的補充：${esc(ep.direction_notes)}</div>` : ""}</details>`;
  if (F.critique && ep.waiting_for !== "script") html += `<details class="card"><summary><b>多模型互審紀錄</b></summary>${critiqueTable(F.critique)}</details>`;
  html += `<details class="card" ${ep.status === "running" ? "open" : ""}><summary><b>agent 工作紀錄</b></summary><div class="log" id="log">${(ep.log || []).map((l) => `${new Date(l.t * 1000).toLocaleTimeString("zh-TW", { hour12: false })}  ${esc(l.msg)}`).join("\n")}</div></details>
    <div class="row"><span class="grow muted">${esc(ep.id)}</span><button class="btn danger" id="del">刪除這一集</button></div>`;
  main.innerHTML = html;
  const lg = $("#log"); if (lg) lg.scrollTop = lg.scrollHeight;
  bindEpisode(ep);

  const sig = `${ep.status}|${ep.stage}|${ep.waiting_for}|${(ep.log || []).length}`;
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!location.hash.startsWith("#/ep/")) return clearInterval(pollTimer);
    const e2 = await api(`/api/episodes/${encodeURIComponent(id)}`).catch(() => null);
    if (e2 && `${e2.status}|${e2.stage}|${e2.waiting_for}|${(e2.log || []).length}` !== sig) {
      if (e2.status === "waiting" && ep.status === "waiting" && e2.waiting_for === ep.waiting_for) return; // don't wipe your edits
      route();
    }
  }, 3000);
};

function gateDirection(brief) {
  if (!brief) return "";
  return `<div class="card gate"><h2>挑方向</h2><p class="muted">方向是整支片最重要的決定。挑一個，並補上你的觀點：哪裡要講細、要跟什麼比較、多講應用面。</p>
    ${(brief.stale_warnings || []).length ? `<div class="warn">可能過時或需求證：${brief.stale_warnings.map(esc).join("；")}</div>` : ""}
    <div class="choices">${brief.directions.map((d, i) => `<div class="choice ${i === 0 ? "sel" : ""}" data-dir="${esc(d.id)}">
      <h3>${esc(d.id)}｜${esc(d.angle)}</h3><div class="muted">給誰看：${esc(d.audience)}</div><div class="muted">為什麼適合：${esc(d.why)}</div>
      <ul>${(d.outline || []).map((o) => `<li>${esc(o)}</li>`).join("")}</ul>
      <div class="muted">要講：${(d.include || []).map(esc).join("、")}</div><div class="muted">不講：${(d.exclude || []).map(esc).join("、")}</div></div>`).join("")}</div>
    <label>你的觀點與要 agent 注意的點</label><textarea id="dir-notes" placeholder="身為觀眾我最好奇…；這段要講細；不要講…"></textarea>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="dir-go">用這個方向寫稿</button>
      <button class="btn" data-reject="brief">都不好，重給方向</button></div></div>`;
}

function critiqueTable(c) {
  if (!c?.rounds?.length) return "";
  return `<div class="crit">${c.rounds.map((r) => `<div class="muted" style="margin-top:8px">第 ${r.round} 輪</div><table>
    ${Object.entries(r.reviews).map(([k, v]) => `<tr><td style="width:110px">${esc(META.critics[k])}</td>
      <td style="width:50px"><span class="score ${v.score >= 8 ? "hi" : "low"}">${v.score}</span></td><td>${esc(v.summary)}
      ${(v.issues || []).length ? `<ul>${v.issues.slice(0, 5).map((x) => `<li>「${esc(x.quote)}」— ${esc(x.problem)} → ${esc(x.fix)}</li>`).join("")}</ul>` : ""}</td></tr>`).join("")}</table>`).join("")}</div>`;
}

function gateScript(scr, crit) {
  if (!scr) return "";
  const chars = scr.scenes.reduce((n, s) => n + s.narration.length, 0);
  return `<div class="card gate"><h2>看講稿</h2><p class="muted">四個審稿角色已經先看過。你可以直接改字、核准，或寫一句意見讓 agent 重修（意見會寫進品味紀錄）。共 ${scr.scenes.length} 個畫面、${chars} 字，約 ${Math.round(chars / 4.5)} 秒。</p>
    ${critiqueTable(crit)}
    <h2>講稿</h2>${scr.scenes.map((s, i) => `<div class="scene"><div class="row"><span class="hl grow">${i + 1}. <input data-s="${i}" data-k="headline" value="${esc(s.headline)}" style="width:60%"></span>
      <select data-s="${i}" data-k="style" style="width:auto">${Object.entries(META.styles).map(([k, v]) => `<option value="${k}" ${k === s.style ? "selected" : ""}>${esc(v.split("：")[0])}</option>`).join("")}</select></div>
      <textarea data-s="${i}" data-k="narration">${esc(s.narration)}</textarea>
      <input data-s="${i}" data-k="bullets" value="${esc((s.bullets || []).join("｜"))}" placeholder="畫面重點，用｜分隔"></div>`).join("")}
    <label>修改意見（要 agent 重修才填）</label><textarea id="scr-fb" placeholder="例如：開頭太慢，第一句就講結論"></textarea>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="scr-ok">核准講稿，開始配音與做畫面</button>
      <button class="btn" id="scr-rev">照意見重修</button></div></div>`;
}

function gatePackage(pk, vertical, video) {
  if (!pk) return "";
  return `<div class="card gate"><h2>挑標題與縮圖</h2><p class="muted">這兩件事決定有沒有人點進來。挑你自己最想點的。</p>
    ${video ? `<details><summary>先看成片</summary><video src="${file(video)}" controls class="${vertical ? "vertical" : ""}"></video></details>` : ""}
    <h2>標題</h2><div class="choices">${pk.titles.map((t, i) => `<div class="choice ${i === 0 ? "sel" : ""}" data-title="${i}"><b>${esc(t.text)}</b><div class="muted">${esc(t.angle)}</div></div>`).join("")}</div>
    <label>或自己寫一個</label><input id="pk-custom" placeholder="留空就用上面選的">
    <h2>縮圖</h2><div class="thumbs ${vertical ? "vertical" : ""}">${pk.thumbnails.map((t, i) => `<div class="thumb ${i === 0 ? "sel" : ""}" data-thumb="${i}"><img src="${file(t.file)}"></div>`).join("")}</div>
    <h2>IG 輪播</h2><div class="carousel">${(pk.carousel || []).map((c) => `<img src="${file(c.file)}">`).join("")}</div>
    <h2>說明欄與貼文</h2><div class="muted" style="white-space:pre-wrap">${esc(pk.description)}</div><hr><div class="muted" style="white-space:pre-wrap">${esc(pk.fb_post)}\n${esc((pk.hashtags || []).join(" "))}</div>
    <label>排程發布時間（選填）</label><input id="pk-sched" type="datetime-local" style="width:260px">
    <div class="row" style="margin-top:12px"><button class="btn primary" id="pk-go">確定，送去最終審核</button>
      <button class="btn" data-reject="package">都不好，重做包裝</button></div></div>`;
}

function videoBlock(ep, vertical) {
  const v = ep.files.verify;
  return `<div class="card"><h2 style="margin-top:0">成片</h2>${ep.video ? `<video src="${file(ep.video)}" controls class="${vertical ? "vertical" : ""}"></video>` : ""}
    ${v ? `<h2>自動檢查（實測數字）</h2><div class="checks">${Object.entries(v.checks).map(([k, c]) => `<div class="check ${c.ok ? "ok" : "bad"}"><b>${esc(k)}</b>${esc(c.value)}</div>`).join("")}</div>` : ""}</div>`;
}

function packageSummary(pk, ep) {
  if (!pk || !ep.package_choice) return "";
  const t = pk.thumbnails[ep.package_choice.thumb];
  return `<div class="card"><h2 style="margin-top:0">包裝</h2><div class="row"><img src="${file(t.file)}" style="width:240px;border-radius:6px">
    <div class="grow"><b>${esc(ep.package_choice.title)}</b><div class="muted" style="white-space:pre-wrap;margin-top:6px">${esc(pk.description).slice(0, 400)}</div></div></div>
    <h2>IG 輪播</h2><div class="carousel">${(pk.carousel || []).map((c) => `<img src="${file(c.file)}">`).join("")}</div></div>`;
}

function gateApproval(ep, F, vertical) {
  const checks = F.verify ? Object.values(F.verify.checks) : [];
  const bad = checks.filter((c) => !c.ok).length;
  return `<div class="card gate"><h2>看成片，決定核准或退件</h2>
    <p class="muted">發出去就收不回來。逐項確認：影片、聲音、字幕、輪播、說明欄、標題與縮圖。</p>
    ${bad ? `<div class="warn">自動檢查有 ${bad} 項沒過，請特別看一下。</div>` : ""}</div>
    ${videoBlock(ep, vertical)}${packageSummary(F.package, ep)}
    <div class="card gate"><div class="row"><label class="grow" style="margin:0"><input type="checkbox" id="ap-check" style="width:auto"> 我看過成片，影片、聲音、字幕、輪播、說明欄都正常</label></div>
    <div class="row" style="margin-top:12px"><button class="btn primary" id="ap-go" disabled>核准，輸出發布包</button></div>
    <h2>退件</h2><div class="row"><select id="rj-to" style="width:auto"><option value="assemble">重做畫面與配音</option><option value="script">重寫講稿</option>
      <option value="package">重做標題與縮圖</option><option value="brief">重給方向</option></select>
      <input id="rj-reason" class="grow" placeholder="一句理由，例如：開頭太無聊（會寫進品味紀錄）" style="width:auto"><button class="btn danger" id="rj-go">退件</button></div></div>`;
}

function metricsBlock(ep) {
  return `<div class="card"><h2 style="margin-top:0">成效回收</h2><p class="muted">發布後記下各平台數字，agent 之後選題會參考。</p>
    ${ep.metrics.length ? `<table class="crit" style="width:100%">${ep.metrics.map((m) => `<tr><td>${esc(m.platform)}</td><td>${esc(m.date)}</td><td>觀看 ${esc(m.views)}</td><td>平均觀看 ${esc(m.watch_time)}</td><td>新追蹤 ${esc(m.followers)}</td><td>${esc(m.note)}</td></tr>`).join("")}</table>` : ""}
    <div class="row" style="margin-top:8px"><input id="m-platform" placeholder="平台" style="width:110px"><input id="m-date" type="date" style="width:150px">
    <input id="m-views" placeholder="觀看" style="width:90px"><input id="m-watch_time" placeholder="平均觀看" style="width:100px"><input id="m-followers" placeholder="新追蹤" style="width:90px">
    <input id="m-note" placeholder="備註" class="grow" style="width:auto"><button class="btn" id="m-add">記錄</button></div></div>`;
}

function bindEpisode(ep) {
  const id = encodeURIComponent(ep.id);
  const post = async (path, body) => { try { await api(`/api/episodes/${id}/${path}`, { method: "POST", body }); toast("好，交給 agent"); route(); } catch (e) { toast(e.message); } };
  const pick = (attr) => $$(`[data-${attr}]`).forEach((el) => (el.onclick = () => { $$(`[data-${attr}]`).forEach((x) => x.classList.remove("sel")); el.classList.add("sel"); }));
  pick("dir"); pick("title"); pick("thumb");
  $("#retry") && ($("#retry").onclick = () => post("retry"));
  $("#del").onclick = async () => { if (!confirm("確定刪除這一集與所有檔案？無法復原。")) return; try { await api(`/api/episodes/${id}`, { method: "DELETE" }); location.hash = "#/episodes"; } catch (e) { toast(e.message); } };
  $("#dir-go") && ($("#dir-go").onclick = () => post("direction", { id: $(".choice.sel[data-dir]").dataset.dir, notes: $("#dir-notes").value }));
  $$("[data-reject]").forEach((b) => (b.onclick = () => {
    const reason = prompt("一句理由（會寫進品味紀錄，下次不再犯）："); if (reason) post("reject", { back_to: b.dataset.reject, reason });
  }));
  const collectScript = () => {
    const scr = JSON.parse(JSON.stringify(ep.files.script));
    $$("[data-s]").forEach((el) => { const s = scr.scenes[+el.dataset.s]; s[el.dataset.k] = el.dataset.k === "bullets" ? el.value.split("｜").map((x) => x.trim()).filter(Boolean) : el.value; });
    return scr;
  };
  $("#scr-ok") && ($("#scr-ok").onclick = () => post("script", { approve: true, script: collectScript() }));
  $("#scr-rev") && ($("#scr-rev").onclick = () => { const fb = $("#scr-fb").value.trim(); if (!fb) return toast("請先寫修改意見"); post("script", { approve: false, feedback: fb, script: collectScript() }); });
  $("#pk-go") && ($("#pk-go").onclick = () => post("package", { title: +$(".choice.sel[data-title]").dataset.title, custom_title: $("#pk-custom").value, thumb: +$(".thumb.sel").dataset.thumb, schedule: $("#pk-sched").value }));
  $("#ap-check") && ($("#ap-check").onchange = (e) => ($("#ap-go").disabled = !e.target.checked));
  $("#ap-go") && ($("#ap-go").onclick = () => post("approve"));
  $("#rj-go") && ($("#rj-go").onclick = () => { const r = $("#rj-reason").value.trim(); if (!r) return toast("請留一句退件理由"); post("reject", { back_to: $("#rj-to").value, reason: r }); });
  $("#m-add") && ($("#m-add").onclick = async () => {
    const body = {}; for (const k of ["platform", "date", "views", "watch_time", "followers", "note"]) body[k] = $(`#m-${k}`).value;
    await api(`/api/episodes/${id}/metrics`, { method: "POST", body }); route();
  });
}

// ---------- router ----------
async function route() {
  clearInterval(pollTimer);
  const [path, qs] = (location.hash.slice(2) || "review").split("?");
  const [name, arg] = path.split("/");
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === name));
  try { await (views[name] || views.review)(new URLSearchParams(qs || ""), arg && decodeURIComponent(arg)); }
  catch (e) { main.innerHTML = `<div class="card">載入失敗：${esc(e.message)}</div>`; }
  refreshStatus();
}
(async () => {
  META = await api("/api/meta");
  window.addEventListener("hashchange", route);
  route();
  setInterval(refreshStatus, 5000);
})();
