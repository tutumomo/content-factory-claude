import { $, $$, api, esc, fileUrl, fmtName, fmtShortDate, state, statusPill, stepper, toast } from "../lib.js?v=20261124b";
import { loginGoogle } from "../modals.js?v=20261124b";

function gateDirection(brief) {
  if (!brief) return "";
  return `<div class="card gate"><h2>挑方向</h2><p class="muted">方向是整支片最重要的決定。挑一個，並補上你的觀點：哪裡要講細、要跟什麼比較、多講應用面。</p>
    ${(brief.stale_warnings || []).length ? `<div class="warn">可能過時或需求證：${brief.stale_warnings.map(esc).join("；")}</div>` : ""}
    <div class="choices">${brief.directions.map((d, i) => `<div class="choice ${i === 0 ? "sel" : ""}" data-dir="${esc(d.id)}">
      <h3>${esc(d.id)}｜${esc(d.angle)}</h3><div class="muted">給誰看：${esc(d.audience)}</div><div class="muted">為什麼適合：${esc(d.why)}</div>
      <ul>${(d.outline || []).map((o) => `<li>${esc(o)}</li>`).join("")}</ul>
      <div class="muted">要講：${(d.include || []).map(esc).join("、")}</div><div class="muted">不講：${(d.exclude || []).map(esc).join("、")}</div></div>`).join("")}</div>
    <label>你的觀點與要 agent 注意的點</label><textarea id="dir-notes" placeholder="身為觀眾我最好奇的是…；這段要講細；不要講…"></textarea>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="dir-go">用這個方向寫稿</button>
      <button type="button" class="btn" data-reject="brief">都不好，重給方向</button></div></div>`;
}

function gateSources(ep) {
  const s = (ep.checks || {}).sources || {};
  const gaps = s.gaps || [];
  const sr = s.search;
  const searched = sr ? `<p class="muted">智能體已先自己上網搜尋${sr.engine ? `（${esc(sr.engine)}）` : ""}：試了 ${sr.tried || 0} 個網頁，${(sr.kept || []).length ? `可讀 ${sr.kept.length} 個，但還不夠` : "沒有找到可讀的網頁"}。${(sr.errors || []).length ? `<br>${sr.errors.map(esc).join("；")}` : ""}</p>` : "";
  return `<div class="card gate"><h2>來源不足，先補資料</h2>
    ${searched}
    <p class="muted">${esc(s.value || "沒有抓到可讀的一手來源")}。依照防幻覺規則，沒有材料就不該硬寫；你可以補連結或補上你已知的一手資訊，也可以明確選擇在標註需求證的情況下繼續。</p>
    ${gaps.length ? `<div class="warn">需求證或待補：<ul>${gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></div>` : ""}
    ${s.note ? `<div class="muted">${esc(s.note)}</div>` : ""}
    <label>補一手連結（一行一個，會重新抓取）</label>
    <textarea id="src-urls" placeholder="https://…"></textarea>
    <label>或補你已知的一手資訊（至少 80 字才算足夠）</label>
    <textarea id="src-notes" placeholder="我實際測試過…；官方公告寫的是…"></textarea>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="src-go">補好了，重新求證</button>
      <button type="button" class="btn" id="src-skip">來源不足也繼續（講稿會標註需求證）</button></div></div>`;
}

function critiqueTable(c, mode) {
  if (!c?.rounds?.length) return "";
  const labels = state.META?.critics_by_mode?.[mode || "news"] || state.META?.critics || {};
  return `<div class="crit">${c.rounds.map((r) => `<div class="muted" style="margin-top:8px">第 ${r.round} 輪</div><table>
    ${Object.entries(r.reviews).map(([k, v]) => `<tr><td style="width:110px">${esc(labels[k] || k)}</td>
      <td style="width:50px"><span class="score ${v.score >= 8 ? "hi" : "low"}">${v.score}</span></td><td>${esc(v.summary)}
      ${(v.issues || []).length ? `<ul>${v.issues.slice(0, 5).map((x) => `<li>「${esc(x.quote)}」— ${esc(x.problem)} → ${esc(x.fix)}</li>`).join("")}</ul>` : ""}</td></tr>`).join("")}</table>`).join("")}</div>`;
}

function gateScript(scr, crit) {
  if (!scr) return "";
  const chars = scr.scenes.reduce((n, s) => n + s.narration.length, 0);
  return `<div class="card gate"><h2>看講稿</h2><p class="muted">四個審稿角色已經先看過。你可以直接改字、核准，或寫一句意見讓 agent 重修（意見會寫進品味紀錄）。共 ${scr.scenes.length} 個畫面、${chars} 字，約 ${Math.round(chars / 4.5)} 秒。</p>
    ${critiqueTable(crit)}
    <label>背景音樂風格（英文，純音樂；留空用系統設定的預設風格）</label>
    <input id="scr-music" value="${esc(scr.music || "")}" placeholder="warm lo-fi, soft piano, light drums, no vocals">
    <h2>講稿</h2>${scr.scenes.map((s, i) => `<div class="scene"><div class="row"><span class="hl grow">${i + 1}. <input data-s="${i}" data-k="headline" value="${esc(s.headline)}" style="width:60%"></span>
      <select data-s="${i}" data-k="style" style="width:auto">${Object.entries(state.META.styles).map(([k, v]) => `<option value="${k}" ${k === s.style ? "selected" : ""}>${esc(v.split("：")[0])}</option>`).join("")}</select></div>
      <textarea data-s="${i}" data-k="narration">${esc(s.narration)}</textarea>
      <input data-s="${i}" data-k="bullets" value="${esc((s.bullets || []).join("｜"))}" placeholder="畫面重點，用｜分隔">
      <div class="row" style="margin-top:6px">
        <input data-s="${i}" data-k="visual" value="${esc(s.visual || "")}" placeholder="生圖用畫面描述（英文，可留空）" class="grow">
        <select data-s="${i}" data-k="sfx" style="width:auto"><option value="">（不墊音效）</option>
          ${Object.entries(state.META.sfx_tags || {}).map(([k, v]) => `<option value="${k}" ${k === (s.sfx || "") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
        <input data-s="${i}" data-k="emotion" value="${esc(s.emotion || "")}" placeholder="情緒" style="width:110px">
      </div></div>`).join("")}
    <label>修改意見（要 agent 重修才填）</label><textarea id="scr-fb" placeholder="例如：開頭太慢，第一句就講結論"></textarea>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="scr-ok">核准講稿，開始配音與做畫面</button>
      <button type="button" class="btn" id="scr-rev">照意見重修</button></div></div>`;
}

function gateStoryboard(sb, eid) {
  if (!sb) return "";
  return `<div class="card gate"><h2>看分鏡</h2>
    <p class="muted">配音與生圖之前先看一遍畫面安排。共 ${sb.scenes.length} 個畫面，預估 ${Math.round(sb.est_total)} 秒。核可就開始配音與做畫面；退回請寫一句原因，agent 會先修稿。</p>
    <div class="sb-grid">${sb.scenes.map((s) => `<div class="sb-card">
      ${s.thumb ? `<img src="${fileUrl(`episodes/${eid}/output/${s.thumb}`)}">` : ""}
      <div class="sb-meta"><b>${s.index + 1}. ${esc(s.headline || "（無標題）")}</b>
        <div class="muted">約 ${s.est_seconds} 秒${s.sfx ? `・音效 ${esc(state.META.sfx_tags?.[s.sfx] || s.sfx)}` : ""}${s.visual ? `・${esc(s.visual)}` : ""}</div>
        <div class="sb-narr">${esc(s.narration)}</div></div></div>`).join("")}</div>
    <label>退回原因（要退回才填）</label><textarea id="sb-fb" placeholder="例如：第 2 個畫面資訊太多，拆成兩個"></textarea>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="sb-ok">核准分鏡，開始配音</button>
      <button type="button" class="btn" id="sb-rev">退回重修</button></div></div>`;
}

function gateCost(ep) {
  return `<div class="card gate"><h2>核准雲端花費</h2>
    <p class="muted">這一集要用 Lyria 生成背景音樂，單筆金額超過設定的核准門檻。核准後會繼續配音與合成；不核准可改回 audio.cpp YuE2（免費）。</p>
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="cost-ok">核准這一筆花費</button>
      <a class="btn" href="#/content">先不做</a></div></div>`;
}

function gatePackage(pk, vertical, video) {
  if (!pk) return "";
  return `<div class="card gate"><h2>挑標題與縮圖</h2><p class="muted">這兩件事決定有沒有人點進來。挑你自己最想點的。</p>
    ${video ? `<details><summary>先看成片</summary><video src="${fileUrl(video)}" controls class="${vertical ? "vertical" : ""}"></video></details>` : ""}
    <h2>標題</h2><div class="choices">${pk.titles.map((t, i) => `<div class="choice ${i === 0 ? "sel" : ""}" data-title="${i}"><b>${esc(t.text)}</b><div class="muted">${esc(t.angle)}</div>${(t.warnings || []).length ? `<div class="warn">${t.warnings.map(esc).join("；")}</div>` : ""}</div>`).join("")}</div>
    <label>或自己寫一個</label><input id="pk-custom" placeholder="留空就用上面選的">
    <h2>縮圖</h2><div class="thumbs ${vertical ? "vertical" : ""}">${pk.thumbnails.map((t, i) => `<div class="thumb ${i === 0 ? "sel" : ""}" data-thumb="${i}"><img src="${fileUrl(t.file)}"></div>`).join("")}</div>
    <h2>IG 輪播</h2><div class="carousel">${(pk.carousel || []).map((c) => `<img src="${fileUrl(c.file)}">`).join("")}</div>
    <h2>說明欄與貼文</h2><div class="muted" style="white-space:pre-wrap">${esc(pk.description)}</div><hr><div class="muted" style="white-space:pre-wrap">${esc(pk.fb_post)}\n${esc((pk.hashtags || []).join(" "))}</div>
    <label>排程發布時間（選填）</label><input id="pk-sched" type="datetime-local" style="width:260px">
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="pk-go">確定，送去最終審核</button>
      <button type="button" class="btn" data-reject="package">都不好，重做包裝</button></div></div>`;
}

function sourcesBlock(v) {
  // The assembly step writes which source each category actually used (and every fallback).
  const s = v && v.sources;
  if (!s || (!(s.badges || []).length && !(s.plan || []).length)) return "";
  const badges = (s.badges || []).map((b) => `<div class="warn" style="margin:8px 0 0">${esc(b.label)}：${esc(b.text)}</div>`).join("");
  const plan = (s.plan || []).map((l) => `<div class="muted">${esc(l)}</div>`).join("");
  const voice = s.voice?.fallback
    ? `<div class="muted">配音：${esc(s.voice.reason || "改用備援聲音")}。這一集的音色跟原本設定的不同，字幕改用字數估時。</div>` : "";
  return `<details class="card" ${(s.badges || []).length ? "open" : ""}><summary><b>素材來源</b>${(s.badges || []).length ? `　<span class="pill" style="background:var(--wait-soft);color:#9c5700">${s.badges.length} 項降級</span>` : ""}</summary>
    ${badges}<div style="margin-top:8px">${plan}</div>${voice}</details>`;
}

function videoBlock(ep, vertical) {
  const v = ep.files.verify;
  return `<div class="card"><h2 style="margin-top:0">成片</h2>${ep.video ? `<video src="${fileUrl(ep.video)}" controls class="${vertical ? "vertical" : ""}"></video>` : ""}
    ${v ? `<h2>自動檢查（實測數字）</h2><div class="checks">${Object.entries(v.checks).map(([k, c]) => `<div class="check ${c.ok ? "ok" : "bad"}"><b>${esc(k)}</b>${esc(c.value)}</div>`).join("")}</div>` : ""}</div>`;
}

function packageSummary(pk, ep) {
  if (!pk || !ep.package_choice) return "";
  const t = pk.thumbnails[ep.package_choice.thumb];
  const carousel = (pk.carousel || []).length ? `<h2>IG 輪播</h2><div class="carousel">${(pk.carousel || []).map((c) => `<img src="${fileUrl(c.file)}">`).join("")}</div>` : "";
  return `<div class="card"><h2 style="margin-top:0">包裝</h2><div class="row">${t ? `<img src="${fileUrl(t.file)}" style="width:240px;border-radius:6px">` : ""}
    <div class="grow"><b>${esc(ep.package_choice.title)}</b><div class="muted" style="white-space:pre-wrap;margin-top:6px">${esc(pk.description).slice(0, 400)}</div></div></div>
    ${carousel}</div>`;
}

function gateApproval(ep, F, vertical) {
  const checks = F.verify ? Object.values(F.verify.checks) : [];
  const bad = checks.filter((c) => !c.ok).length;
  const rating = ep.rating || "general";
  const restricted = rating !== "general";
  const rlabel = state.META?.rating_label?.[rating] || rating;
  const confirmBlock = restricted ? `
    <div class="row" style="margin-top:10px"><label class="grow" style="margin:0">分級確認：這一集是
      <select id="ap-rating" style="width:auto">
        <option value="">請選擇分級</option>
        <option value="${esc(rating)}">${esc(rlabel)}</option>
      </select></label></div>
    <div class="warn" style="margin-top:8px">受限分級的發布包只留在本機（不含輪播、貼文與 shorts 文案），也不會自動上傳任何平台。</div>` : "";
  return `<div class="card gate"><h2>看成片，決定核准或退件</h2>
    <p class="muted">發出去就收不回來。逐項確認：影片、聲音、字幕、輪播、說明欄、標題與縮圖。</p>
    ${bad ? `<div class="warn">自動檢查有 ${bad} 項沒過，請特別看一下。</div>` : ""}</div>
    ${videoBlock(ep, vertical)}${packageSummary(F.package, ep)}
    <div class="card gate"><div class="row"><label class="grow" style="margin:0"><input type="checkbox" id="ap-check" style="width:auto"> 我看過成片，影片、聲音、字幕、輪播、說明欄都正常</label></div>
    ${confirmBlock}
    <div class="row" style="margin-top:12px"><button type="button" class="btn primary" id="ap-go" disabled>核准，輸出發布包</button></div>
    <h2>退件</h2><div class="row"><select id="rj-to" style="width:auto"><option value="assemble">重做畫面與配音</option><option value="script">重寫講稿</option>
      <option value="package">重做標題與縮圖</option><option value="brief">重給方向</option></select>
      <input id="rj-reason" class="grow" placeholder="一句理由，例如：開頭太無聊（會寫進品味紀錄）" style="width:auto"><button type="button" class="btn danger" id="rj-go">退件</button></div></div>`;
}

function metricsBlock(ep) {
  return `<div class="card"><h2 style="margin-top:0">成效回收</h2><p class="muted">發布後記下各平台數字，也會自動同步到「復盤」儀表板。</p>
    ${ep.metrics.length ? `<table class="crit" style="width:100%">${ep.metrics.map((m, idx) => `<tr><td>${esc(m.platform)}</td><td>${esc(m.date)}</td><td>觀看 ${esc(m.views)}</td><td>平均觀看 ${esc(m.watch_time)}</td><td>新追蹤 ${esc(m.followers)}</td><td>${esc(m.note)}</td><td><button type="button" class="btn danger sm" data-mdel="${idx}">刪</button></td></tr>`).join("")}</table>` : ""}
    <div class="row" style="margin-top:8px"><input id="m-platform" placeholder="平台" style="width:110px"><input id="m-date" type="date" style="width:150px">
    <input id="m-views" placeholder="觀看" style="width:90px"><input id="m-watch_time" placeholder="平均觀看" style="width:100px"><input id="m-followers" placeholder="新追蹤" style="width:90px">
    <input id="m-note" placeholder="備註" class="grow" style="width:auto"><button type="button" class="btn" id="m-add">記錄</button></div></div>`;
}

function youtubeBlock(ep) {
  const y = ep.youtube || {};
  const rating = ep.rating || "general";
  if (rating !== "general") {
    return `<div class="row" style="margin-top:12px"><b class="grow">YouTube</b></div>
      <div class="warn" style="margin-top:6px">受限分級不支援自動上傳：YouTube Data API 沒有可寫的 18+ 欄位，而且平台規範禁止這類內容。發布包只留本機。</div>`;
  }
  const label = { queued: "排隊中", uploading: "上傳中", processing: "設定縮圖中", done: "已上傳", error: "上傳失敗" }[y.status] || "";
  let html = `<div class="row" style="margin-top:12px"><b class="grow">YouTube ${label ? `・${label}` : ""}</b>`;
  if (["queued", "uploading", "processing"].includes(y.status)) {
    html += `<span class="muted">${Math.round((y.progress || 0) * 100)}%</span></div>
      <div style="height:6px;background:var(--line,#ddd);border-radius:3px;margin-top:6px"><div style="height:6px;width:${Math.round((y.progress || 0) * 100)}%;background:var(--accent,#3b82f6);border-radius:3px"></div></div>`;
    return html;
  }
  html += `<button type="button" class="btn ${y.status === "done" ? "" : "primary"}" id="yt-up">${y.status === "done" ? "再上傳一次" : "上傳到 YouTube"}</button></div>`;
  if (y.status === "done") {
    const vis = y.publish_at ? `排程 ${new Date(y.publish_at).toLocaleString("zh-TW", { hour12: false })} 公開` : { private: "私人", unlisted: "不公開", public: "公開" }[y.privacy] || "";
    html += `<div class="muted">✓ <a href="${esc(y.url)}" target="_blank" rel="noopener">${esc(y.url)}</a>・${esc(vis)}・<a href="https://studio.youtube.com/video/${esc(y.video_id)}/edit" target="_blank" rel="noopener">在 YouTube Studio 編輯</a></div>`;
    if (y.note) html += `<div class="warn" style="margin-top:6px">${esc(y.note)}</div>`;
  }
  if (y.status === "error") html += `<div class="muted" style="color:var(--bad)">${esc(y.error)}</div>`;
  return html;
}

function ratingPill(ep) {
  const r = ep.rating || "general";
  if (r === "general") return "";
  const label = state.META?.rating_label?.[r] || r;
  return `<span class="pill accent" title="內容分級">${esc(label)}</span>`;
}

function modePill(ep) {
  const m = ep.mode || "news";
  if (m === "news") return "";
  const label = state.META?.mode_label?.[m] || m;
  return `<span class="pill" title="內容模式">${esc(label)}</span>`;
}

export async function viewEpisode(main, id) {
  const [ep, stylesRes, health] = await Promise.all([
    api(`/api/episodes/${encodeURIComponent(id)}`),
    api("/api/styles").catch(() => ({ items: [] })),
    api("/api/health").catch(() => null),
  ]);
  const styleCard = (stylesRes.items || []).find((s) => s.id === ep.style_id);
  const F = ep.files;
  const vertical = ep.format === "short";

  let html = `
    <div class="row" style="margin-bottom:10px">
      <a class="btn sm" href="#/content">← 回到內容</a>
      ${styleCard ? `<span class="pill">${esc(styleCard.icon)} ${esc(styleCard.name)}</span>` : ""}
      ${ep.schedule ? `<a class="pill accent" href="#/schedule" style="text-decoration:none">📅 ${esc(fmtShortDate(ep.schedule))}</a>` : ""}
    </div>
    <div class="row"><h1 class="grow">${esc(ep.package_choice?.title || ep.topic)}</h1><span class="pill">${fmtName(ep.format)}</span>${ratingPill(ep)}${modePill(ep)}${statusPill(ep)}</div>
    ${stepper(ep)}`;

  if (health?.tts?.needs_voice_ref && !["done", "error"].includes(ep.status)) {
    html += `<div class="warn">未設定參考聲音：${esc(health.tts.detail)}（在「系統設定 → 配音 audio.cpp → 參考聲音」挑一個，按「測試發音」確認。）</div>`;
  }

  if (ep.status === "error") {
    html += `<div class="card" style="border-color:var(--bad)"><b>出錯了</b><div class="muted">${esc(ep.error)}</div>
      <div class="row" style="margin-top:10px"><button type="button" class="btn primary" id="retry">重試這一步</button></div></div>`;
  }
  if (["running", "queued"].includes(ep.status)) {
    html += `<div class="card muted">agent 正在「${esc(state.META.stage_label[ep.stage])}」。你可以先去做別的事，好了會出現在內容頁的待決定區。</div>`;
  }

  if (ep.status === "waiting" && ep.waiting_for === "sources") html += gateSources(ep);
  if (F.verify?.sources) html += sourcesBlock(F.verify);

  if (ep.status === "waiting" && ep.waiting_for === "direction") html += gateDirection(F.brief);
  if (ep.status === "waiting" && ep.waiting_for === "script") html += gateScript(F.script, F.critique);
  if (ep.status === "waiting" && ep.waiting_for === "storyboard") html += gateStoryboard(F.storyboard, ep.id);
  if (ep.status === "waiting" && ep.waiting_for === "cost") html += gateCost(ep);
  if (ep.status === "waiting" && ep.waiting_for === "package") html += gatePackage(F.package, vertical, ep.video);
  if (ep.status === "waiting" && ep.waiting_for === "approval") html += gateApproval(ep, F, vertical);

  if (ep.status === "done") {
    const restricted = (ep.rating || "general") !== "general";
    const pkgDesc = restricted
      ? "發布包：<code>${esc(ep.published_dir)}</code>（影片、字幕、縮圖、metadata.json、CHECKLIST.md；受限分級只留本機）"
      : "發布包：<code>${esc(ep.published_dir)}</code>（影片、縮圖、字幕、說明欄、輪播圖卡、metadata.json）";
    html += `<div class="card"><h2 style="margin-top:0">已核准</h2>
      <div class="muted">${pkgDesc}${ep.schedule ? `・排程 ${esc(ep.schedule)}` : ""}</div>
      ${youtubeBlock(ep)}</div>`;
    html += videoBlock(ep, vertical) + packageSummary(F.package, ep) + metricsBlock(ep);
  }
  if (ep.direction && ep.waiting_for !== "direction") {
    html += `<details class="card"><summary><b>選定方向</b>：${esc(ep.direction.angle)}</summary>
      <ul>${(ep.direction.outline || []).map((o) => `<li>${esc(o)}</li>`).join("")}</ul>${ep.direction_notes ? `<div class="muted">你的補充：${esc(ep.direction_notes)}</div>` : ""}</details>`;
  }
  if (F.critique && ep.waiting_for !== "script") {
    html += `<details class="card"><summary><b>多模型互審紀錄</b></summary>${critiqueTable(F.critique, ep.mode)}</details>`;
  }
  html += `<details class="card" ${ep.status === "running" ? "open" : ""}><summary><b>agent 工作紀錄</b></summary><div class="log" id="log">${(ep.log || []).map((l) => `${new Date(l.t * 1000).toLocaleTimeString("zh-TW", { hour12: false })}  ${esc(l.msg)}`).join("\n")}</div></details>
    <div class="row"><span class="grow muted">${esc(ep.id)}</span><button type="button" class="btn danger" id="del">刪除這一集</button></div>`;

  main.innerHTML = html;
  const lg = $("#log", main);
  if (lg) lg.scrollTop = lg.scrollHeight;

  const eid = encodeURIComponent(ep.id);
  const post = async (path, body) => {
    try {
      await api(`/api/episodes/${eid}/${path}`, { method: "POST", body });
      toast("好，交給 agent");
      if (state.onRoute) state.onRoute();
    } catch (e) { toast(e.message); }
  };
  const pick = (attr) => $$(`[data-${attr}]`, main).forEach((el) => (el.onclick = () => {
    $$(`[data-${attr}]`, main).forEach((x) => x.classList.remove("sel"));
    el.classList.add("sel");
  }));
  pick("dir"); pick("title"); pick("thumb");

  $("#retry", main) && ($("#retry", main).onclick = () => post("retry"));
  $("#del", main).onclick = async () => {
    if (!confirm("確定刪除這一集與所有檔案？無法復原。")) return;
    try {
      await api(`/api/episodes/${eid}`, { method: "DELETE" });
      location.hash = "#/content";
    } catch (e) { toast(e.message); }
  };
  $("#src-go", main) && ($("#src-go", main).onclick = () => post("sources", {
    notes: $("#src-notes", main).value,
    source_urls: $("#src-urls", main).value.split(/\s+/).filter((u) => u.startsWith("http")),
    proceed: false,
  }));
  $("#src-skip", main) && ($("#src-skip", main).onclick = () => {
    if (confirm("來源不足就繼續，講稿與說明欄只能標註需求證。確定嗎？")) post("sources", { proceed: true });
  });
  $("#dir-go", main) && ($("#dir-go", main).onclick = () => post("direction", {
    id: $(".choice.sel[data-dir]", main).dataset.dir,
    notes: $("#dir-notes", main).value,
  }));
  $$("[data-reject]", main).forEach((b) => (b.onclick = () => {
    const reason = prompt("一句理由（會寫進品味紀錄，下次不再犯）：");
    if (reason) post("reject", { back_to: b.dataset.reject, reason });
  }));
  const collectScript = () => {
    const scr = JSON.parse(JSON.stringify(ep.files.script));
    $$("[data-s]", main).forEach((el) => {
      const s = scr.scenes[+el.dataset.s];
      s[el.dataset.k] = el.dataset.k === "bullets"
        ? el.value.split("｜").map((x) => x.trim()).filter(Boolean)
        : el.value;
    });
    const m = $("#scr-music", main);
    if (m) scr.music = m.value.trim();
    return scr;
  };
  $("#scr-ok", main) && ($("#scr-ok", main).onclick = () => post("script", { approve: true, script: collectScript() }));
  $("#scr-rev", main) && ($("#scr-rev", main).onclick = () => {
    const fb = $("#scr-fb", main).value.trim();
    if (!fb) return toast("請先寫修改意見");
    post("script", { approve: false, feedback: fb, script: collectScript() });
  });
  $("#sb-ok", main) && ($("#sb-ok", main).onclick = () => post("storyboard", { approve: true }));
  $("#sb-rev", main) && ($("#sb-rev", main).onclick = () => {
    const n = $("#sb-fb", main).value.trim();
    if (!n) return toast("請先寫退回原因");
    post("storyboard", { approve: false, notes: n });
  });
  $("#cost-ok", main) && ($("#cost-ok", main).onclick = () => post("cost"));
  $("#pk-go", main) && ($("#pk-go", main).onclick = () => post("package", {
    title: +$(".choice.sel[data-title]", main).dataset.title,
    custom_title: $("#pk-custom", main).value,
    thumb: +$(".thumb.sel", main).dataset.thumb,
    schedule: $("#pk-sched", main).value,
  }));
  $("#ap-check", main) && ($("#ap-check", main).onchange = (e) => {
    const ratingSel = $("#ap-rating", main);
    const confirmed = !ratingSel || ratingSel.value === (ep.rating || "general");
    $("#ap-go", main).disabled = !e.target.checked || !confirmed;
  });
  $("#ap-rating", main) && ($("#ap-rating", main).onchange = () => {
    const box = $("#ap-check", main);
    if (box) {
      const ratingSel = $("#ap-rating", main);
      const confirmed = ratingSel.value === (ep.rating || "general");
      $("#ap-go", main).disabled = !box.checked || !confirmed;
    }
  });
  $("#ap-go", main) && ($("#ap-go", main).onclick = () => post("approve", {
    confirm_rating: ($("#ap-rating", main) || {}).value || "",
  }));
  $("#rj-go", main) && ($("#rj-go", main).onclick = () => {
    const r = $("#rj-reason", main).value.trim();
    if (!r) return toast("請留一句退件理由");
    post("reject", { back_to: $("#rj-to", main).value, reason: r });
  });
  $("#m-add", main) && ($("#m-add", main).onclick = async () => {
    const body = {};
    for (const k of ["platform", "date", "views", "watch_time", "followers", "note"]) body[k] = $(`#m-${k}`, main).value;
    await api(`/api/episodes/${eid}/metrics`, { method: "POST", body });
    if (state.onRoute) state.onRoute();
  });
  $$("[data-mdel]", main).forEach((b) => {
    b.onclick = async () => {
      await api(`/api/episodes/${eid}/metrics/${b.dataset.mdel}`, { method: "DELETE" });
      if (state.onRoute) state.onRoute();
    };
  });

  $("#yt-up", main) && ($("#yt-up", main).onclick = async () => {
    const y = ep.youtube || {};
    if (y.status === "done" && !confirm("這一集已經上傳過，確定要再上傳一支新影片嗎？")) return;
    let st = await api("/api/youtube/status");
    if (!st.logged_in) {
      if (!st.client?.ok) { toast(st.client?.error || "找不到 Google OAuth 用戶端檔"); return; }
      st = await loginGoogle();
      if (!st.logged_in) return;
    }
    if (!st.channel && !confirm("這個 Google 帳號讀不到 YouTube 頻道，仍要嘗試上傳嗎？")) return;
    await post("youtube");
  });

  const sigOf = (e) => `${e.status}|${e.stage}|${e.waiting_for}|${(e.log || []).length}|${e.youtube?.status}|${e.youtube?.progress}`;
  const sig = sigOf(ep);
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (!location.hash.startsWith("#/ep/")) return clearInterval(state.pollTimer);
    const e2 = await api(`/api/episodes/${encodeURIComponent(id)}`).catch(() => null);
    if (e2 && sigOf(e2) !== sig) {
      if (e2.status === "waiting" && ep.status === "waiting" && e2.waiting_for === ep.waiting_for) return;
      if (state.onRoute) state.onRoute();
    }
  }, 3000);
}
