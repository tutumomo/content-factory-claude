import { $, $$, api, compactNum, esc, fileUrl, fmtName, fmtShortDate, miniSteps, state, statusPill, when } from "../lib.js?v=20261121f";
import { openNewEpisodeModal } from "../modals.js?v=20261121f";

let contentQuery = "";
let contentFormat = "all";
let contentView = (() => {
  try { return localStorage.getItem("cf_content_view") === "table" ? "table" : "board"; }
  catch { return "board"; }
})();
let contentPoll = null;

export async function viewContent(main) {
  clearInterval(contentPoll);
  const eps = await api("/api/episodes");

  const render = () => {
    const q = contentQuery.trim().toLowerCase();
    const list = eps.filter((e) => {
      if (contentFormat !== "all" && e.format !== contentFormat) return false;
      if (!q) return true;
      return [e.topic, e.package_choice?.title, e.id].some((v) => String(v || "").toLowerCase().includes(q));
    });

    const attention = eps.filter((e) => e.status === "waiting" || e.status === "error");
    const inboxHtml = attention.length
      ? `<section class="inbox-strip">
          <div class="inbox-head">
            <h2>待你決定（${attention.length}）</h2>
            <span class="muted">agent 已把前置苦工做完，只等你選方向、看稿、挑標題縮圖或核准。</span>
          </div>
          <div class="inbox-list">
            ${attention.map((e) => `
              <a class="inbox-item" href="#/ep/${encodeURIComponent(e.id)}">
                ${e.thumb ? `<img src="${fileUrl(e.thumb)}" alt="">` : ""}
                <div class="grow">
                  <div class="row" style="gap:6px">
                    <b style="font-size:14px">${esc(e.package_choice?.title || e.topic)}</b>
                    <span class="pill">${fmtName(e.format)}</span>
                    ${statusPill(e)}
                  </div>
                  <div class="muted" style="margin-top:2px">${esc(state.META.stage_label[e.stage])}・更新於 ${when(e.updated)}</div>
                </div>
                <span class="btn primary sm">${e.status === "waiting" ? "去決定 →" : "查看 →"}</span>
              </a>`).join("")}
          </div>
        </section>`
      : "";

    const cols = [
      { key: "waiting", title: "等你決定", dot: "var(--wait)", rows: list.filter((e) => e.status === "waiting") },
      { key: "running", title: "Agent 製作中", dot: "var(--info)", rows: list.filter((e) => ["running", "queued"].includes(e.status)) },
      { key: "done", title: "已核准", dot: "var(--ok)", rows: list.filter((e) => e.status === "done") },
      { key: "error", title: "出錯待處理", dot: "var(--bad)", rows: list.filter((e) => e.status === "error") },
    ];

    const bodyHtml = !eps.length
      ? `<div class="card empty">還沒有任何集數。到「靈感」找題目，或按右上角「＋ 新集數」開始第一支。</div>`
      : contentView === "board"
        ? `<div class="kanban">
            ${cols.map((col) => `
              <section class="kanban-col">
                <div class="kanban-col-head">
                  <span class="dot" style="background:${col.dot}"></span>
                  <span>${col.title}</span>
                  <span class="cnt">${col.rows.length}</span>
                </div>
                <div class="k-list">
                  ${col.rows.length ? col.rows.map((e) => `
                    <a class="k-card" href="#/ep/${encodeURIComponent(e.id)}">
                      ${e.thumb ? `<img class="k-card-thumb" src="${fileUrl(e.thumb)}" alt="" loading="lazy">` : ""}
                      <div class="k-card-title">${esc(e.package_choice?.title || e.topic)}</div>
                      <div class="k-card-meta">
                        <span class="pill">${fmtName(e.format)}</span>
                        ${statusPill(e)}
                        ${e.schedule ? `<span class="pill">📅 ${esc(fmtShortDate(e.schedule))}</span>` : ""}
                        ${e.total_views > 0 ? `<span class="pill">👁 ${compactNum(e.total_views)}</span>` : ""}
                      </div>
                      <div class="muted" style="font-size:12px">${esc(state.META.stage_label[e.stage])}</div>
                      ${miniSteps(e)}
                    </a>`).join("") : `<div class="muted" style="padding:18px 8px;text-align:center">無</div>`}
                </div>
              </section>`).join("")}
          </div>`
        : `<div class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>內容</th><th>格式</th><th>階段</th><th>狀態</th><th>排期</th><th>觀看</th><th>更新時間</th></tr></thead>
              <tbody>
                ${list.length ? list.map((e) => `
                  <tr style="cursor:pointer" data-ep="${esc(e.id)}">
                    <td>
                      ${e.thumb ? `<img class="table-thumb" src="${fileUrl(e.thumb)}" alt="">` : ""}
                      <b>${esc(e.package_choice?.title || e.topic)}</b>
                    </td>
                    <td><span class="pill">${fmtName(e.format)}</span></td>
                    <td>${esc(state.META.stage_label[e.stage])}</td>
                    <td>${statusPill(e)}</td>
                    <td class="muted">${e.schedule ? esc(fmtShortDate(e.schedule)) : "—"}</td>
                    <td>${e.total_views > 0 ? compactNum(e.total_views) : "—"}</td>
                    <td class="muted">${when(e.updated)}</td>
                  </tr>`).join("") : `<tr><td colspan="7" class="empty">沒有符合條件的集數</td></tr>`}
              </tbody>
            </table>
          </div>`;

    main.innerHTML = `
      <div class="page-head">
        <div><h1>內容</h1><p class="sub">集中掌握每一支片卡在哪個閘門、Agent 進度與待決策項目。</p></div>
        <button type="button" class="btn primary" id="c-new">＋ 做一支新的</button>
      </div>
      ${inboxHtml}
      <div class="toolbar">
        <input id="c-search" class="search-box" value="${esc(contentQuery)}" placeholder="搜尋集數標題…">
        <div class="filter-pills">
          ${[["all", "全部"], ["short", "短片"], ["long", "長片"]].map(([k, l]) =>
            `<button type="button" class="fpill ${contentFormat === k ? "on" : ""}" data-cfmt="${k}">${l}</button>`
          ).join("")}
        </div>
        <span class="grow"></span>
        <div class="seg">
          <button type="button" data-cview="board" class="${contentView === "board" ? "on" : ""}">看板</button>
          <button type="button" data-cview="table" class="${contentView === "table" ? "on" : ""}">表格</button>
        </div>
      </div>
      ${bodyHtml}
    `;

    $("#c-new", main).onclick = () => openNewEpisodeModal();
    $("#c-search", main).oninput = (ev) => {
      contentQuery = ev.target.value;
      const pos = ev.target.selectionStart;
      render();
      const inp = $("#c-search", main);
      if (inp) { inp.focus(); inp.setSelectionRange(pos, pos); }
    };
    $$("[data-cfmt]", main).forEach((b) => {
      b.onclick = () => { contentFormat = b.dataset.cfmt; render(); };
    });
    $$("[data-cview]", main).forEach((b) => {
      b.onclick = () => {
        contentView = b.dataset.cview;
        try { localStorage.setItem("cf_content_view", contentView); } catch {}
        render();
      };
    });
    $$("[data-ep]", main).forEach((tr) => {
      tr.onclick = () => { location.hash = `#/ep/${encodeURIComponent(tr.dataset.ep)}`; };
    });
  };

  render();

  // Keep running/queued episodes live-updated
  if (eps.some((e) => ["running", "queued"].includes(e.status))) {
    contentPoll = setInterval(async () => {
      if (!location.hash.startsWith("#/content") && location.hash !== "" && location.hash !== "#/") {
        return clearInterval(contentPoll);
      }
      const next = await api("/api/episodes").catch(() => null);
      if (!next) return;
      const sig = (xs) => xs.map((x) => `${x.id}:${x.status}:${x.stage}:${x.updated}`).join("|");
      if (sig(next) !== sig(eps)) {
        eps.length = 0;
        eps.push(...next);
        render();
      }
    }, 4000);
  }
}
