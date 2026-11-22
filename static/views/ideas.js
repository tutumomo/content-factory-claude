import { $, $$, api, esc, fmtName, statusPill, toast, when } from "../lib.js?v=20261122d";
import { openNewEpisodeModal } from "../modals.js?v=20261122d";

const KIND_LABEL = { radar: "雷達", note: "筆記", link: "連結", quote: "金句" };

let ideaFilter = "all";
let ideaQuery = "";
let quickTab = "note";
let ideaView = (() => {
  try { return localStorage.getItem("cf_ideas_view") === "table" ? "table" : "board"; }
  catch { return "board"; }
})();
let radarTimer = null;

export async function viewIdeas(main) {
  clearInterval(radarTimer);
  const [ideas, eps] = await Promise.all([api("/api/ideas"), api("/api/episodes")]);
  const epMap = new Map(eps.map((e) => [e.id, e]));

  const renderList = () => {
    const q = ideaQuery.trim().toLowerCase();
    const filtered = ideas.filter((it) => {
      if (ideaFilter === "short" || ideaFilter === "long") {
        if (it.format !== ideaFilter) return false;
      } else if (ideaFilter !== "all" && it.kind !== ideaFilter) {
        return false;
      }
      if (!q) return true;
      return [it.title, it.why, it.notes, it.source, ...(it.urls || [])].some((v) =>
        String(v || "").toLowerCase().includes(q)
      );
    });

    const box = $("#idea-view", main);
    if (!box) return;
    if (!filtered.length) {
      box.innerHTML = `<div class="card empty">目前沒有符合條件的靈感。隨手記一條，或用右邊「AI 雷達掃描」找題目。</div>`;
      return;
    }

    const linkUrl = (it) => (it.urls && it.urls[0]) || (String(it.source || "").startsWith("http") ? it.source : "");
    const actions = (it) => {
      const ep = it.episode_id ? epMap.get(it.episode_id) : null;
      return `${ep ? `<a class="btn sm" href="#/ep/${encodeURIComponent(ep.id)}">前往集數 →</a>` : `<button type="button" class="btn primary sm" data-make="${esc(it.id)}">開做這支 →</button>`}
        ${ep ? `<button type="button" class="btn sm" data-make="${esc(it.id)}">再開新集</button>` : ""}
        <button type="button" class="btn danger sm" data-del="${esc(it.id)}">刪除</button>`;
    };

    box.innerHTML = ideaView === "board"
      ? `<div class="idea-grid">${filtered.map((it) => {
          const ep = it.episode_id ? epMap.get(it.episode_id) : null;
          const bodyTxt = it.notes || it.why || "";
          const url = linkUrl(it);
          return `<article class="card idea-card">
            <div class="idea-card-head">
              <span class="pill accent">${esc(KIND_LABEL[it.kind] || it.kind)}</span>
              <span class="pill">${fmtName(it.format)}</span>
              ${it.attention_score != null ? `<span class="pill" title="${esc(it.score_reason || "")}">注意力 ${it.attention_score}</span>` : it.heat ? `<span class="pill">熱度：${esc(it.heat)}</span>` : ""}
              ${it.group_size > 1 ? `<span class="pill" title="${esc((it.members || []).map((m) => m.title).join("\n"))}">${it.group_size} 篇同事件</span>` : ""}
              ${it.needs_more ? `<span class="pill">待補</span>` : ""}
              <span class="grow"></span>
              <span class="muted" style="font-size:12px">${when(it.found).slice(5, 16)}</span>
            </div>
            <div class="idea-title">${esc(it.title)}</div>
            ${bodyTxt && bodyTxt !== it.title ? `<div class="idea-body">${esc(bodyTxt)}</div>` : ""}
            ${it.score_reason ? `<div class="muted" style="font-size:12px">評分依據：${esc(it.score_reason)}</div>` : ""}
            ${url ? `<div class="muted" style="word-break:break-all"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">🔗 ${esc(url)}</a></div>` : it.source ? `<div class="muted">來源：${esc(it.source)}</div>` : ""}
            <div class="idea-foot">
              ${ep ? statusPill(ep) : ""}
              ${actions(it)}
            </div>
          </article>`;
        }).join("")}</div>`
      : `<div class="data-table-wrap">
          <table class="data-table" style="table-layout:fixed">
            <colgroup>
              <col style="width:32%"><col style="width:76px"><col style="width:64px"><col style="width:72px">
              <col style="width:170px"><col style="width:100px"><col style="width:84px"><col style="width:168px">
            </colgroup>
            <thead><tr><th>靈感</th><th>類型</th><th>格式</th><th>熱度</th><th>來源</th><th>集數</th><th>收錄時間</th><th>操作</th></tr></thead>
            <tbody>
              ${filtered.map((it) => {
                const ep = it.episode_id ? epMap.get(it.episode_id) : null;
                const url = linkUrl(it);
                const bodyTxt = it.notes || it.why || "";
                return `<tr>
                  <td>
                    <b>${esc(it.title)}</b>
                    ${bodyTxt && bodyTxt !== it.title ? `<div class="muted" style="font-size:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${esc(bodyTxt)}</div>` : ""}
                  </td>
                  <td><span class="pill accent">${esc(KIND_LABEL[it.kind] || it.kind)}</span></td>
                  <td><span class="pill">${fmtName(it.format)}</span></td>
                  <td>${it.attention_score != null ? `<span class="pill" title="${esc(it.score_reason || "")}">${it.attention_score}</span>` : it.heat ? `<span class="pill" title="${esc(it.heat)}" style="max-width:66px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle">${esc(it.heat)}</span>` : `<span class="muted">—</span>`}</td>
                  <td class="muted" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(url || it.source || "")}">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>` : esc(it.source || "—")}</td>
                  <td>${ep ? statusPill(ep) : `<span class="muted">未開拍</span>`}</td>
                  <td class="muted">${when(it.found).slice(5, 16)}</td>
                  <td><div class="row" style="gap:6px;flex-wrap:nowrap;white-space:nowrap">${actions(it)}</div></td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>`;

    $$("[data-make]", box).forEach((btn) => {
      btn.onclick = () => {
        const it = ideas.find((x) => x.id === btn.dataset.make);
        if (!it) return;
        openNewEpisodeModal({
          topic: it.title,
          format: it.format,
          source_urls: it.urls?.length ? it.urls : (String(it.source || "").startsWith("http") ? [it.source] : []),
          notes: it.notes || it.why || "",
          idea_id: it.id,
        });
      };
    });

    $$("[data-del]", box).forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/ideas/${encodeURIComponent(btn.dataset.del)}`, { method: "DELETE" });
        const idx = ideas.findIndex((x) => x.id === btn.dataset.del);
        if (idx >= 0) ideas.splice(idx, 1);
        toast("已移除靈感");
        renderList();
      };
    });
  };

  main.innerHTML = `
    <div class="page-head">
      <div><h1>靈感</h1><p class="sub">隨手記下想法、連結或金句，或把多個線索丟給 AI 雷達掃描，點一下就能開拍。</p></div>
    </div>
    <div class="ideas-top">
      <div class="card" style="margin-bottom:0">
        <div class="row" style="margin-bottom:10px">
          <b class="grow">隨手記靈感</b>
          <div class="seg">
            <button type="button" data-qtab="note" class="${quickTab === "note" ? "on" : ""}">筆記</button>
            <button type="button" data-qtab="link" class="${quickTab === "link" ? "on" : ""}">連結</button>
            <button type="button" data-qtab="quote" class="${quickTab === "quote" ? "on" : ""}">金句</button>
          </div>
        </div>
        <div id="qi-link-wrap" style="${quickTab === "link" ? "" : "display:none"}">
          <input id="qi-url" placeholder="https://... 貼上參考文章、影片或 GitHub 連結" style="margin-bottom:8px">
        </div>
        <textarea id="qi-text" rows="2" placeholder="${quickTab === "quote" ? "記下一句很有共鳴的觀點或金句…" : quickTab === "link" ? "補一句為什麼想拍這個連結（選填）…" : "一句話記下靈感（Ctrl+Enter 直接儲存）…"}"></textarea>
        <div class="row" style="margin-top:10px">
          <select id="qi-fmt" style="width:130px">
            <option value="short">短片</option>
            <option value="long">長片</option>
          </select>
          <span class="grow"></span>
          <button type="button" class="btn primary" id="qi-save">記下來</button>
        </div>
      </div>

      <div class="card" style="margin-bottom:0">
        <div class="row" style="margin-bottom:8px">
          <b class="grow">AI 雷達掃描</b>
          <span class="muted" id="radar-state"></span>
        </div>
        <textarea id="r-seeds" rows="3" placeholder="貼上多行線索（對標帳號熱門片連結、官方公告、社群討論筆記）…"></textarea>
        <div class="row" style="margin-top:10px">
          <span class="muted grow">掃描在背景跑，好了自動整理成下方候選卡。</span>
          <button type="button" class="btn" id="r-go">開始掃描</button>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <input id="i-search" class="search-box" value="${esc(ideaQuery)}" placeholder="搜尋靈感標題、備註、連結…">
      <div class="filter-pills">
        ${[
          ["all", "全部"], ["radar", "雷達"], ["note", "筆記"], ["link", "連結"], ["quote", "金句"],
          ["short", "短片"], ["long", "長片"],
        ].map(([k, l]) => `<button type="button" class="fpill ${ideaFilter === k ? "on" : ""}" data-ifilt="${k}">${l}</button>`).join("")}
      </div>
      <span class="grow"></span>
      <div class="seg">
        <button type="button" data-iview="board" class="${ideaView === "board" ? "on" : ""}">看板</button>
        <button type="button" data-iview="table" class="${ideaView === "table" ? "on" : ""}">表格</button>
      </div>
    </div>
    <div id="idea-view"></div>
  `;

  $$("[data-qtab]", main).forEach((b) => {
    b.onclick = () => {
      quickTab = b.dataset.qtab;
      $$("[data-qtab]", main).forEach((x) => x.classList.toggle("on", x.dataset.qtab === quickTab));
      $("#qi-link-wrap", main).style.display = quickTab === "link" ? "" : "none";
      $("#qi-text", main).placeholder =
        quickTab === "quote"
          ? "記下一句很有共鳴的觀點或金句…"
          : quickTab === "link"
            ? "補一句為什麼想拍這個連結（選填）…"
            : "一句話記下靈感（Ctrl+Enter 直接儲存）…";
    };
  });

  const saveQuick = async () => {
    const txt = $("#qi-text", main).value.trim();
    const url = $("#qi-url", main).value.trim();
    const fmt = $("#qi-fmt", main).value;
    if (quickTab === "link" && !url) return toast("請貼上連結");
    if (quickTab !== "link" && !txt) return toast("請先輸入內容");
    const firstLine = txt.split(/[。！？\n]|[.!?](?=\s|$)/)[0].trim().slice(0, 48);
    const title = quickTab === "link" ? (firstLine || url) : firstLine;
    try {
      const created = await api("/api/ideas", {
        method: "POST",
        body: {
          kind: quickTab,
          title,
          notes: txt,
          urls: url ? [url] : [],
          source: url || "隨手記",
          format: fmt,
        },
      });
      ideas.unshift(created);
      $("#qi-text", main).value = "";
      $("#qi-url", main).value = "";
      toast("已記下靈感");
      renderList();
    } catch (e) {
      toast(e.message);
    }
  };

  $("#qi-save", main).onclick = saveQuick;
  $("#qi-text", main).addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") saveQuick();
  });

  $("#r-go", main).onclick = async () => {
    try {
      await api("/api/radar/scan", { method: "POST", body: { seeds: $("#r-seeds", main).value } });
      $("#r-seeds", main).value = "";
      $("#radar-state", main).textContent = "掃描中…";
      toast("已送入背景雷達掃描");
      let sawRadar = false;
      clearInterval(radarTimer);
      radarTimer = setInterval(async () => {
        if (!location.hash.startsWith("#/ideas")) return clearInterval(radarTimer);
        const h = await api("/api/health").catch(() => null);
        if (!h) return;
        const busyRadar = h.worker?.current?.kind === "radar";
        if (busyRadar) sawRadar = true;
        if (!busyRadar && (sawRadar || h.worker?.queued === 0)) {
          clearInterval(radarTimer);
          viewIdeas(main);
        }
      }, 2000);
    } catch (e) {
      toast(e.message);
    }
  };

  $("#i-search", main).oninput = (e) => {
    ideaQuery = e.target.value;
    renderList();
  };
  $$("[data-ifilt]", main).forEach((b) => {
    b.onclick = () => {
      ideaFilter = b.dataset.ifilt;
      $$("[data-ifilt]", main).forEach((x) => x.classList.toggle("on", x.dataset.ifilt === ideaFilter));
      renderList();
    };
  });
  $$("[data-iview]", main).forEach((b) => {
    b.onclick = () => {
      ideaView = b.dataset.iview;
      try { localStorage.setItem("cf_ideas_view", ideaView); } catch {}
      $$("[data-iview]", main).forEach((x) => x.classList.toggle("on", x.dataset.iview === ideaView));
      renderList();
    };
  });

  renderList();
}
