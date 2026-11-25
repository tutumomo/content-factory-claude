import { $, api, esc, when } from "../lib.js?v=20261126c";

let timer = null;

const STATE = {
  ok: { label: "就緒", color: "var(--good,#22c55e)" },
  warn: { label: "降級", color: "var(--warn,#f59e0b)" },
  off: { label: "停用", color: "var(--bad,#ef4444)" },
};

function card(s) {
  const st = STATE[s.state] || STATE.warn;
  return `<div class="card" style="margin:0">
    <div class="row" style="gap:8px">
      <span style="width:10px;height:10px;border-radius:50%;background:${st.color};display:inline-block;flex:none"></span>
      <b class="grow">${esc(s.name)}</b>
      <span class="pill">${st.label}</span>
    </div>
    <div class="muted" style="margin-top:2px">${esc(s.role)}</div>
    <div style="margin-top:8px;word-break:break-word">${esc(s.detail || "—")}</div>
    ${s.hint ? `<div class="warn" style="margin-top:8px">${esc(s.hint)}</div>` : ""}
  </div>`;
}

export async function viewStatus(main) {
  clearInterval(timer);
  let first = true;
  const load = async (quiet = false) => {
    let d;
    try {
      d = await api("/api/status");
    } catch (e) {
      if (!quiet || first) main.innerHTML = `<div class="card">讀取失敗：${esc(e.message)}</div>`;
      return;
    }
    first = false;
    const s = d.summary;
    const summary = s.off
      ? `有 ${s.off} 項停用，出片前要先修`
      : s.warn
        ? `可出片；${s.warn} 項會自動降級`
        : "全部就緒";
    main.innerHTML = `
      <div class="page-head">
        <div><h1>系統狀態</h1><p class="sub">本機服務與命令列工具的即時檢查。只讀取、不會幫你啟動任何服務。</p></div>
        <div class="row">
          <span class="muted">上次檢查 ${when(d.checked)}</span>
          <button type="button" class="btn primary" id="st-refresh">重新檢查</button>
        </div>
      </div>
      <div class="card" style="margin-bottom:14px">
        <div class="row" style="gap:16px;flex-wrap:wrap">
          <b class="grow">${s.ok}/${s.total} 就緒・${summary}</b>
          <span class="muted">降級 ${s.warn}・停用 ${s.off}</span>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">
        ${d.services.map(card).join("")}
      </div>`;
    $("#st-refresh", main).onclick = () => load();
  };
  await load();
  timer = setInterval(() => {
    if (!location.hash.startsWith("#/status")) return clearInterval(timer);
    load(true);
  }, 30000);
}
