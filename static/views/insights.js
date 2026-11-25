import { $, $$, api, compactNum, esc, fileUrl, fmtName, toast, when } from "../lib.js?v=20261125g";
import { openAddMetricModal, openImportCsvModal } from "../modals.js?v=20261125g";

let fDays = 30;
let fPlatform = "all";
let chartMetric = "views";
let chartMode = "chart";
let analyzePoll = null;

function niceMax(v) {
  if (v <= 0) return 10;
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((n) => n * pow >= v) || 10;
  return step * pow;
}

function renderTrendChart(box, daily, metricKey) {
  if (!daily.length) {
    box.innerHTML = `<div class="empty">這段期間尚無每日趨勢數據。</div>`;
    return;
  }
  const rows = daily.map((d) => ({ ...d, val: Number(d[metricKey]) || 0 }));
  const width = Math.max(box.clientWidth || 640, 320);
  const height = 220;
  const pad = { l: 48, r: 16, t: 14, b: 26 };
  const max = niceMax(Math.max(...rows.map((r) => r.val)));
  const x = (i) => rows.length === 1
    ? (pad.l + (width - pad.l - pad.r) / 2)
    : pad.l + (i / (rows.length - 1)) * (width - pad.l - pad.r);
  const y = (v) => pad.t + (1 - v / max) * (height - pad.t - pad.b);

  const line = rows.map((r, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(r.val).toFixed(1)}`).join(" ");
  const area = rows.length > 1
    ? `${line} L ${x(rows.length - 1).toFixed(1)} ${y(0).toFixed(1)} L ${x(0).toFixed(1)} ${y(0).toFixed(1)} Z`
    : "";
  const ticks = [0, 0.5, 1].map((t) => Math.round(t * max));
  const stepLabel = Math.max(1, Math.ceil(rows.length / 7));

  box.innerHTML = `
    <div class="chart-box">
      <svg class="trend-svg" viewBox="0 0 ${width} ${height}" id="trend-svg">
        ${ticks.map((tk) => `
          <line x1="${pad.l}" x2="${width - pad.r}" y1="${y(tk)}" y2="${y(tk)}" class="chart-grid" />
          <text x="${pad.l - 8}" y="${y(tk) + 4}" text-anchor="end" class="chart-axis">${compactNum(tk)}</text>
        `).join("")}
        ${rows.map((r, i) => (i % stepLabel === 0 || i === rows.length - 1
          ? `<text x="${x(i)}" y="${height - 6}" text-anchor="middle" class="chart-axis">${r.date.slice(5).replace("-", "/")}</text>`
          : "")).join("")}
        ${area ? `<path d="${area}" class="chart-area" />` : ""}
        ${rows.length > 1 ? `<path d="${line}" class="chart-line" />` : ""}
        ${rows.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.val)}" r="${rows.length === 1 ? 5 : 3}" class="chart-dot" />`).join("")}
        <line id="c-cross" x1="0" x2="0" y1="${pad.t}" y2="${height - pad.b}" class="chart-cross" style="display:none" />
        <circle id="c-dot" cx="0" cy="0" r="5" class="chart-dot" style="display:none" />
      </svg>
      <div class="chart-tip" id="c-tip" style="display:none"></div>
    </div>`;

  const svg = $("#trend-svg", box);
  const cross = $("#c-cross", box);
  const dot = $("#c-dot", box);
  const tip = $("#c-tip", box);

  svg.onpointermove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const px = ((ev.clientX - rect.left) / rect.width) * width;
    let idx = 0;
    if (rows.length > 1) {
      const ratio = (px - pad.l) / Math.max(1, width - pad.l - pad.r);
      idx = Math.max(0, Math.min(rows.length - 1, Math.round(ratio * (rows.length - 1))));
    }
    const r = rows[idx];
    const cx = x(idx);
    const cy = y(r.val);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.style.display = "";
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", cy);
    dot.style.display = "";
    tip.style.display = "";
    tip.innerHTML = `<div>${esc(r.date)}</div><b>觀看 ${compactNum(r.views)}・互動 ${compactNum(r.engaged)}・新追蹤 ${compactNum(r.followers)}</b>`;
    tip.style.left = `${Math.min(Math.max(8, (cx / width) * rect.width + 10), rect.width - 210)}px`;
    tip.style.top = `${Math.max(4, (cy / height) * rect.height - 46)}px`;
  };
  svg.onpointerleave = () => {
    cross.style.display = "none";
    dot.style.display = "none";
    tip.style.display = "none";
  };
}

export async function viewInsights(main) {
  clearInterval(analyzePoll);

  const load = async () => {
    const [data, eps] = await Promise.all([
      api(`/api/insights?days=${fDays}&platform=${encodeURIComponent(fPlatform)}`),
      api("/api/episodes"),
    ]);

    const t = data.totals;
    const sum = data.summary || {};
    const maxPlat = Math.max(1, ...(data.by_platform || []).map((p) => p.views || p.engaged || p.count));
    const platOpts = ["all", ...(data.platforms_available || [])];

    main.innerHTML = `
      <div class="page-head">
        <div><h1>復盤</h1><p class="sub">彙整跨集數成效表現，讓 AI 從真實數據提煉建議，一鍵寫進品味紀錄。</p></div>
        <div class="row">
          <button type="button" class="btn" id="in-yt">從 YouTube 更新</button>
          <button type="button" class="btn" id="in-csv">匯入 CSV</button>
          <button type="button" class="btn primary" id="in-add">＋ 錄入數據</button>
        </div>
      </div>

      <div class="toolbar">
        <div class="filter-pills">
          ${[[7, "近 7 天"], [30, "近 30 天"], [0, "全部時間"]].map(([d, label]) =>
            `<button type="button" class="fpill ${fDays === d ? "on" : ""}" data-days="${d}">${label}</button>`
          ).join("")}
        </div>
        <select id="in-plat" style="width:160px">
          ${platOpts.map((p) => `<option value="${esc(p)}" ${p === fPlatform ? "selected" : ""}>${p === "all" ? "全部平台" : esc(p)}</option>`).join("")}
        </select>
        <span class="muted grow">共 ${t.records} 筆紀錄、涵蓋 ${t.episodes_with_metrics} 集</span>
      </div>

      <div class="bento">
        <section class="card b-kpi" style="margin-bottom:0">
          <div class="kpi-grid">
            <div class="kpi-box"><small>總觀看</small><strong>${compactNum(t.views)}</strong></div>
            <div class="kpi-box"><small>新追蹤</small><strong>${compactNum(t.followers)}</strong></div>
            <div class="kpi-box"><small>總互動（讚＋藏＋評）</small><strong>${compactNum(t.engaged)}</strong></div>
            <div class="kpi-box"><small>集均觀看</small><strong>${compactNum(t.avg_views)}</strong></div>
          </div>
          ${sum.analyzing
            ? `<div class="ai-headline">⏳ 正在依成效數據進行復盤分析…</div>`
            : sum.error
              ? `<div class="warn" style="margin-top:12px;margin-bottom:0">復盤分析錯誤：${esc(sum.error)}</div>`
              : sum.headline
                ? `<div class="ai-headline"><b>AI 復盤一句話：</b>${esc(sum.headline)} ${sum.updated ? `<span class="muted">（更新於 ${when(sum.updated)}）</span>` : ""}</div>`
                : ""}
        </section>

        <section class="card b-trend" style="margin-bottom:0">
          <div class="row" style="margin-bottom:10px">
            <h2 style="margin:0" class="grow">每日趨勢</h2>
            <div class="seg">
              ${[["views", "觀看"], ["engaged", "互動"], ["followers", "追蹤"]].map(([k, l]) =>
                `<button type="button" data-im="${k}" class="${chartMetric === k ? "on" : ""}">${l}</button>`
              ).join("")}
            </div>
            <div class="seg">
              <button type="button" data-cmode="chart" class="${chartMode === "chart" ? "on" : ""}">圖</button>
              <button type="button" data-cmode="table" class="${chartMode === "table" ? "on" : ""}">表</button>
            </div>
          </div>
          <div id="trend-slot"></div>
        </section>

        <section class="card b-plat" style="margin-bottom:0">
          <h2 style="margin-top:0">平台分布</h2>
          ${data.by_platform.length ? `<ul class="bar-list">
            ${data.by_platform.map((p) => {
              const v = p.views || p.engaged || p.count;
              const pct = Math.round((v / maxPlat) * 100);
              return `<li>
                <div class="bar-row-head"><b>${esc(p.platform)}</b><span class="muted">${compactNum(p.views)} 觀看・${p.count} 筆</span></div>
                <div class="bar-track"><i style="width:${pct}%"></i></div>
              </li>`;
            }).join("")}
          </ul>` : `<div class="empty">尚無平台數據</div>`}
        </section>

        <section class="card b-top" style="margin-bottom:0">
          <h2 style="margin-top:0">表現最好的內容</h2>
          ${data.top_episodes.length ? `<ol class="top-list">
            ${data.top_episodes.map((ep, idx) => `
              <li>
                <a class="top-item" href="#/ep/${encodeURIComponent(ep.id)}">
                  <span class="top-rank">${idx + 1}</span>
                  ${ep.thumb ? `<img src="${fileUrl(ep.thumb)}" alt="">` : ""}
                  <div class="grow">
                    <b>${esc(ep.title)}</b>
                    <div class="muted">${fmtName(ep.format)}・${esc(ep.platforms.join(" / "))}</div>
                  </div>
                  <b>${compactNum(ep.views)}</b>
                </a>
              </li>`).join("")}
          </ol>` : `<div class="empty">錄入數據後會顯示 Top 5 表現集數。</div>`}
        </section>

        <section class="card b-advice" style="margin-bottom:0">
          <div class="row" style="margin-bottom:10px">
            <h2 style="margin:0" class="grow">給你的建議（候選品味規則）</h2>
            <button type="button" class="btn sm" id="in-analyze" ${sum.analyzing ? "disabled" : ""}>${sum.analyzing ? "分析中…" : "✨ 重新分析"}</button>
          </div>
          ${data.proposed_rules.length ? data.proposed_rules.map((r) => `
            <div class="advice-card">
              <div class="row"><span class="pill accent">${esc(r.category)}</span><b class="grow">${esc(r.rule)}</b></div>
              ${r.evidence ? `<p>依據：${esc(r.evidence)}</p>` : ""}
              <div class="row" style="margin-top:6px">
                <button type="button" class="btn primary sm" data-accept-rule="${esc(r.id)}">寫進品味紀錄</button>
                <button type="button" class="btn sm" data-skip-rule="${esc(r.id)}">略過</button>
              </div>
            </div>`).join("") : `<div class="empty">先錄入成效數據後，點「重新分析」讓 Agent 找出值得寫進品味紀錄的規律。</div>`}
        </section>
      </div>

      <details class="card" style="margin-top:14px">
        <summary><b>數據明細（${data.records.length} 筆）</b></summary>
        <div class="data-table-wrap" style="margin-top:10px">
          <table class="data-table">
            <thead><tr><th>集數</th><th>平台</th><th>日期</th><th>觀看</th><th>平均觀看</th><th>新追蹤</th><th>讚/藏/評</th><th>備註</th><th></th></tr></thead>
            <tbody>
              ${data.records.length ? data.records.map((r) => `
                <tr>
                  <td><a href="#/ep/${encodeURIComponent(r.episode_id)}">${esc(r.episode_title)}</a></td>
                  <td>${esc(r.platform)}</td>
                  <td class="muted">${esc(r.date)}</td>
                  <td>${compactNum(r.views)}</td>
                  <td class="muted">${esc(r.watch_time || "—")}</td>
                  <td>${compactNum(r.followers)}</td>
                  <td class="muted">${r.likes}/${r.saves}/${r.comments}</td>
                  <td class="muted">${esc(r.note)}</td>
                  <td><button type="button" class="btn danger sm" data-del-metric="${esc(r.episode_id)}|${r.idx}">刪</button></td>
                </tr>`).join("") : `<tr><td colspan="9" class="empty">尚無數據明細</td></tr>`}
            </tbody>
          </table>
        </div>
      </details>
    `;

    const slot = $("#trend-slot", main);
    if (chartMode === "chart") {
      renderTrendChart(slot, data.daily, chartMetric);
    } else {
      slot.innerHTML = data.daily.length
        ? `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>日期</th><th>觀看</th><th>互動</th><th>新追蹤</th></tr></thead><tbody>
            ${[...data.daily].reverse().map((d) => `<tr><td>${esc(d.date)}</td><td>${d.views.toLocaleString()}</td><td>${d.engaged.toLocaleString()}</td><td>${d.followers.toLocaleString()}</td></tr>`).join("")}
          </tbody></table></div>`
        : `<div class="empty">尚無數據</div>`;
    }

    $("#in-add", main).onclick = () => openAddMetricModal(eps, null, load);
    $("#in-csv", main).onclick = () => openImportCsvModal(load);
    $("#in-yt", main).onclick = async () => {
      try {
        const r = await api("/api/insights/sync-youtube", { method: "POST" });
        const miss = r.missing?.length ? `；${r.missing.length} 支影片在 YouTube 找不到` : "";
        toast(`已更新 ${r.updated} 集的今日成效${miss}`);
        load();
      } catch (e) {
        toast(e.message);
      }
    };
    $$("[data-days]", main).forEach((b) => { b.onclick = () => { fDays = +b.dataset.days; load(); }; });
    $("#in-plat", main).onchange = (e) => { fPlatform = e.target.value; load(); };
    $$("[data-im]", main).forEach((b) => { b.onclick = () => { chartMetric = b.dataset.im; load(); }; });
    $$("[data-cmode]", main).forEach((b) => { b.onclick = () => { chartMode = b.dataset.cmode; load(); }; });

    $("#in-analyze", main).onclick = async () => {
      try {
        await api("/api/insights/analyze", { method: "POST" });
        toast("已送入背景進行復盤分析");
        load();
      } catch (e) { toast(e.message); }
    };

    $$("[data-accept-rule]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/preferences/${encodeURIComponent(b.dataset.acceptRule)}`, {
          method: "PATCH",
          body: { status: "active" },
        });
        toast("已啟用並寫入品味紀錄");
        load();
      };
    });

    $$("[data-skip-rule]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/preferences/${encodeURIComponent(b.dataset.skipRule)}`, { method: "DELETE" });
        toast("已略過建議");
        load();
      };
    });

    $$("[data-del-metric]", main).forEach((b) => {
      b.onclick = async () => {
        const [eid, idx] = b.dataset.delMetric.split("|");
        await api(`/api/episodes/${encodeURIComponent(eid)}/metrics/${idx}`, { method: "DELETE" });
        toast("已刪除這筆數據");
        load();
      };
    });

    if (sum.analyzing) {
      analyzePoll = setInterval(() => {
        if (!location.hash.startsWith("#/insights")) return clearInterval(analyzePoll);
        load();
      }, 2500);
    }
  };

  await load();
}
