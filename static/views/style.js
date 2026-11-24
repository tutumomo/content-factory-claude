import { $, $$, api, esc, state, toast } from "../lib.js?v=20261124d";
import { openExtractStyleModal, openStyleEditorModal, openVideoStyleModal } from "../modals.js?v=20261124d";

let styleCatFilter = "全部";
let styleQuery = "";
let prefCatFilter = "全部";
let prefStatusFilter = "all";

const SOURCE_LABEL = {
  seed: "預設",
  manual: "手寫",
  reject: "退件學到",
  insights: "復盤提煉",
};

export async function viewStyle(main) {
  const load = async () => {
    const [ch, stylesRes, prefs, eps] = await Promise.all([
      api("/api/channel"),
      api("/api/styles"),
      api("/api/preferences"),
      api("/api/episodes"),
    ]);

    const cats = state.META?.style_categories || ["科技數碼", "新聞快評", "知識科普", "觀點深度", "生活工具"];
    const prefCats = state.META?.pref_cats || ["選題", "方向與觀點", "講稿語氣", "開頭與節奏", "畫面風格", "標題", "縮圖", "配音與字幕"];
    const allStyles = stylesRes.items || [];
    const q = styleQuery.trim().toLowerCase();
    const styles = allStyles.filter((s) => (styleCatFilter === "全部" || s.category === styleCatFilter)
      && (!q || [s.name, s.summary, s.category, s.visual].some((v) => (v || "").toLowerCase().includes(q))));
    const catCount = (c) => (c === "全部" ? allStyles.length : allStyles.filter((s) => s.category === c).length);

    const proposed = prefs.filter((p) => p.status === "proposed");
    const rules = prefs.filter((p) => {
      if (p.status === "proposed") return false;
      if (prefCatFilter !== "全部" && p.category !== prefCatFilter) return false;
      if (prefStatusFilter !== "all" && p.status !== prefStatusFilter) return false;
      return true;
    });

    main.innerHTML = `
      <div class="page-head">
        <div><h1>風格與品味紀錄</h1><p class="sub">設定頻道基本定位、挑選或提煉風格卡，並用開關管理每一條寫作規則。</p></div>
      </div>

      <section class="card">
        <div class="row" style="margin-bottom:8px">
          <h2 style="margin:0" class="grow">頻道基本定位</h2>
          <button type="button" class="btn primary sm" id="ch-save">儲存定位</button>
        </div>
        <div class="grid-2">
          <div><label>頻道名稱</label><input id="c-name" value="${esc(ch.name)}" placeholder="例如：AI 懶人包"></div>
          <div><label>頻道主題</label><input id="c-topic" value="${esc(ch.topic)}" placeholder="例如：每天 AI 新聞與工具"></div>
          <div><label>目標觀眾</label><input id="c-audience" value="${esc(ch.audience)}" placeholder="例如：想跟上 AI 但沒時間的上班族"></div>
          <div><label>發布平台（逗號分隔）</label><input id="c-platforms" value="${esc((ch.platforms || []).join(", "))}"></div>
          <div><label>對標帳號</label><textarea id="c-benchmarks" style="min-height:58px">${esc(ch.benchmarks)}</textarea></div>
          <div><label>禁區（不碰的題材、不用的說法）</label><textarea id="c-taboo" style="min-height:58px">${esc(ch.taboo)}</textarea></div>
          <div><label>分級上限（這個頻道最多做到哪一級）</label>
            <select id="c-max_rating">
              ${["general", "suggestive", "adult"].map((r) => `<option value="${esc(r)}" ${(ch.max_rating || "general") === r ? "selected" : ""}>${esc({ general: "一般", suggestive: "暗示", adult: "成人" }[r])}</option>`).join("")}
            </select>
            <div class="muted" style="font-size:12px">預設「一般」。調高之後才能建受限分級的集數；受限分級不會自動上傳任何平台。</div></div>
        </div>
      </section>

      <div class="row" style="margin:22px 0 10px">
        <h2 style="margin:0" class="grow">風格卡（寫簡報、講稿與包裝時套用）</h2>
        <button type="button" class="btn sm" id="st-extract">✨ 從文字／講稿提煉</button>
        <button type="button" class="btn sm" id="st-video">🎞 從參考影片分析</button>
        <button type="button" class="btn primary sm" id="st-new">＋ 新增風格卡</button>
      </div>
      <div class="toolbar" style="margin-bottom:12px">
        <div class="filter-pills">
          ${["全部", ...cats].map((c) => `<button type="button" class="fpill ${styleCatFilter === c ? "on" : ""}" data-scat="${esc(c)}">${esc(c)} ${catCount(c)}</button>`).join("")}
        </div>
        <span class="grow"></span>
        <input id="st-q" type="search" value="${esc(styleQuery)}" placeholder="搜尋風格卡" style="width:180px">
      </div>
      <div class="style-grid">
        ${styles.map((s) => {
          const active = s.id === stylesRes.active_id;
          return `<article class="card style-card ${active ? "is-active" : ""}">
            <div class="style-card-head">
              <span class="style-ico">${esc(s.icon)}</span>
              <div class="grow">
                <b>${esc(s.name)}</b>
                <div class="muted" style="font-size:12px">${esc(s.category)}・${esc(s.source)}</div>
              </div>
              ${active ? `<span class="pill accent">使用中</span>` : ""}
            </div>
            <div style="font-size:13px">${esc(s.summary || s.tone)}</div>
            ${s.opening ? `<div class="muted" style="font-size:12px"><b>開頭：</b>${esc(s.opening)}</div>` : ""}
            ${s.visual ? `<div class="muted" style="font-size:12px"><b>畫面：</b>${esc(s.visual)}</div>` : ""}
            <div class="style-tags">
              ${(s.words || []).slice(0, 3).map((w) => `<span class="style-tag">＋ ${esc(w)}</span>`).join("")}
              ${(s.avoid || []).slice(0, 2).map((w) => `<span class="style-tag avoid">✕ ${esc(w)}</span>`).join("")}
            </div>
            <div class="row" style="margin-top:auto;padding-top:6px">
              ${active ? "" : `<button type="button" class="btn primary sm" data-sact="${esc(s.id)}">設為使用中</button>`}
              <button type="button" class="btn sm" data-sedit="${esc(s.id)}">${s.preset ? "複製自訂" : "編輯"}</button>
              ${s.preset ? "" : `<button type="button" class="btn danger sm" data-sdel="${esc(s.id)}">刪除</button>`}
            </div>
          </article>`;
        }).join("")}
      </div>
      ${styles.length ? "" : `<div class="empty">沒有符合條件的風格卡。</div>`}

      <div class="row" style="margin:26px 0 10px">
        <h2 style="margin:0" class="grow">品味紀錄（寫作規則庫）</h2>
        <span class="muted">只有「開啟」的規則會注入給 Agent</span>
      </div>

      ${proposed.length ? `
        <div class="proposed-banner">
          <div class="row" style="margin-bottom:8px"><b>✨ 來自復盤的待確認建議（${proposed.length}）</b></div>
          ${proposed.map((p) => `
            <div class="row" style="padding:6px 0;border-top:1px solid #f5dfb8">
              <span class="pill accent">${esc(p.category)}</span>
              <div class="grow">
                <b>${esc(p.rule)}</b>
                ${p.evidence ? `<div class="muted" style="font-size:12px">依據：${esc(p.evidence)}</div>` : ""}
              </div>
              <button type="button" class="btn primary sm" data-pacc="${esc(p.id)}">啟用</button>
              <button type="button" class="btn sm" data-pskip="${esc(p.id)}">略過</button>
            </div>`).join("")}
        </div>` : ""}

      <div class="card">
        <div class="row" style="margin-bottom:12px">
          <select id="np-cat" style="width:140px">${prefCats.map((c) => `<option>${esc(c)}</option>`).join("")}</select>
          <input id="np-rule" class="grow" placeholder="新增一條規則（例如：標題不要超過 22 字）">
          <button type="button" class="btn primary" id="np-add">＋ 新增規則</button>
        </div>

        <div class="toolbar" style="margin-bottom:10px">
          <div class="filter-pills">
            ${["全部", ...prefCats].map((c) => `<button type="button" class="fpill ${prefCatFilter === c ? "on" : ""}" data-pcat="${esc(c)}">${esc(c)}</button>`).join("")}
          </div>
          <span class="grow"></span>
          <div class="seg">
            ${[["all", "全部"], ["active", "啟用中"], ["paused", "已停用"]].map(([k, l]) =>
              `<button type="button" data-pstat="${k}" class="${prefStatusFilter === k ? "on" : ""}">${l}</button>`
            ).join("")}
          </div>
        </div>

        ${rules.length ? rules.map((p) => `
          <div class="pref-row ${p.status === "paused" ? "is-paused" : ""}">
            <label class="switch" title="${p.status === "active" ? "點擊停用" : "點擊啟用"}">
              <input type="checkbox" data-ptog="${esc(p.id)}" ${p.status === "active" ? "checked" : ""}>
              <span></span>
            </label>
            <select data-pcat-edit="${esc(p.id)}">${prefCats.map((c) => `<option ${c === p.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
            <input class="pref-input" data-prule-edit="${esc(p.id)}" value="${esc(p.rule)}">
            <span class="pill">${esc(SOURCE_LABEL[p.source] || p.source)}</span>
            <span class="muted" style="font-size:12px;width:82px">${esc(p.date)}</span>
            <button type="button" class="btn danger sm" data-pdel="${esc(p.id)}">刪</button>
          </div>`).join("") : `<div class="empty">沒有符合篩選條件的規則。</div>`}
      </div>
    `;

    $("#ch-save", main).onclick = async () => {
      const body = { ...ch };
      for (const k of ["name", "topic", "audience", "benchmarks", "taboo"]) {
        body[k] = $(`#c-${k}`, main).value;
      }
      body.platforms = $("#c-platforms", main).value.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
      body.max_rating = $("#c-max_rating", main).value;
      await api("/api/channel", { method: "PUT", body });
      toast("已儲存頻道定位");
    };

    $$("[data-scat]", main).forEach((b) => { b.onclick = () => { styleCatFilter = b.dataset.scat; load(); }; });
    $("#st-q", main).onchange = $("#st-q", main).onsearch = (e) => { styleQuery = e.target.value; load(); };
    $("#st-new", main).onclick = () => openStyleEditorModal(null, load);
    $("#st-extract", main).onclick = () => openExtractStyleModal(eps, load);
    $("#st-video", main).onclick = () => openVideoStyleModal(load);

    $$("[data-sact]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/styles/${encodeURIComponent(b.dataset.sact)}/activate`, { method: "POST" });
        toast("已切換使用中風格卡");
        load();
      };
    });
    $$("[data-sedit]", main).forEach((b) => {
      b.onclick = () => {
        const s = (stylesRes.items || []).find((x) => x.id === b.dataset.sedit);
        if (!s) return;
        openStyleEditorModal(s.preset ? { ...s, name: `${s.name}（自訂）`, asCopy: true } : s, load);
      };
    });
    $$("[data-sdel]", main).forEach((b) => {
      b.onclick = async () => {
        if (!confirm("確定刪除這張風格卡？")) return;
        await api(`/api/styles/${encodeURIComponent(b.dataset.sdel)}`, { method: "DELETE" });
        toast("已刪除風格卡");
        load();
      };
    });

    $$("[data-pacc]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/preferences/${encodeURIComponent(b.dataset.pacc)}`, { method: "PATCH", body: { status: "active" } });
        toast("已啟用規則");
        load();
      };
    });
    $$("[data-pskip]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/preferences/${encodeURIComponent(b.dataset.pskip)}`, { method: "DELETE" });
        toast("已略過");
        load();
      };
    });

    const addRule = async () => {
      const rule = $("#np-rule", main).value.trim();
      if (!rule) return toast("請輸入規則內容");
      await api("/api/preferences", { method: "POST", body: { category: $("#np-cat", main).value, rule } });
      toast("已新增品味規則");
      load();
    };
    $("#np-add", main).onclick = addRule;
    $("#np-rule", main).addEventListener("keydown", (e) => { if (e.key === "Enter") addRule(); });

    $$("[data-pcat]", main).forEach((b) => { b.onclick = () => { prefCatFilter = b.dataset.pcat; load(); }; });
    $$("[data-pstat]", main).forEach((b) => { b.onclick = () => { prefStatusFilter = b.dataset.pstat; load(); }; });

    $$("[data-ptog]", main).forEach((chk) => {
      chk.onchange = async () => {
        await api(`/api/preferences/${encodeURIComponent(chk.dataset.ptog)}`, {
          method: "PATCH",
          body: { status: chk.checked ? "active" : "paused" },
        });
        toast(chk.checked ? "已啟用規則" : "已停用規則");
        load();
      };
    });
    $$("[data-pcat-edit]", main).forEach((sel) => {
      sel.onchange = async () => {
        await api(`/api/preferences/${encodeURIComponent(sel.dataset.pcatEdit)}`, {
          method: "PATCH",
          body: { category: sel.value },
        });
        toast("已更新分類");
      };
    });
    $$("[data-prule-edit]", main).forEach((inp) => {
      inp.onkeydown = (e) => { if (e.key === "Enter") inp.blur(); };
      inp.onchange = async () => {
        const val = inp.value.trim();
        if (!val) return;
        await api(`/api/preferences/${encodeURIComponent(inp.dataset.pruleEdit)}`, {
          method: "PATCH",
          body: { rule: val },
        });
        toast("已更新規則");
      };
    });
    $$("[data-pdel]", main).forEach((b) => {
      b.onclick = async () => {
        await api(`/api/preferences/${encodeURIComponent(b.dataset.pdel)}`, { method: "DELETE" });
        toast("已刪除規則");
        load();
      };
    });
  };

  await load();
}
