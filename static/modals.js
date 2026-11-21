import { $, $$, api, applyNavLayout, closeModal, esc, getNavLayout, openModal, state, toast } from "./lib.js";

export async function openSettingsModal() {
  const s = await api("/api/settings");
  state.SETTINGS = s;
  let activeTab = "ui";

  const draw = () => {
    const curLayout = s.ui?.nav_layout || getNavLayout();
    const tabs = [
      ["ui", "介面"],
      ["llm", "LLM 模型"],
      ["tts", "配音 audio.cpp"],
      ["pipeline", "流程參數"],
    ];
    const bodyHtml = `
      <div class="seg" style="margin-bottom:14px">
        ${tabs.map(([id, label]) => `<button type="button" data-stab="${id}" class="${activeTab === id ? "on" : ""}">${label}</button>`).join("")}
      </div>
      <div data-spane="ui" style="${activeTab === "ui" ? "" : "display:none"}">
        <label>導覽列位置（也可隨時點導覽列右上角按鈕快速切換）</label>
        <div class="layout-picker">
          <button type="button" class="layout-opt ${curLayout === "top" ? "sel" : ""}" data-lay="top">
            <b>⬒ 頂部單行導覽</b>
            <div class="muted" style="margin-top:4px">最大橫向工作空間，適合看板、月曆與復盤儀表板</div>
          </button>
          <button type="button" class="layout-opt ${curLayout === "side" ? "sel" : ""}" data-lay="side">
            <b>◧ 左側邊欄</b>
            <div class="muted" style="margin-top:4px">經典深色側邊導覽列，固定顯示狀態與待審計數</div>
          </button>
        </div>
      </div>
      <div data-spane="llm" style="${activeTab === "llm" ? "" : "display:none"}">
        <label>提供者</label>
        <select id="s-provider">
          <option value="claude_cli">Claude CLI（claude -p，用你的 Claude Code 登入）</option>
          <option value="openai">OpenAI 相容端點（LM Studio／Strata／其他）</option>
          <option value="mock">示範模式（不呼叫模型，只用來測流程）</option>
        </select>
        <label>Claude 模型（留空用預設）</label>
        <input id="s-claude_model" value="${esc(s.llm.claude_model)}" placeholder="例如 opus、sonnet">
        <label>OpenAI 相容 base URL</label>
        <input id="s-openai_base_url" value="${esc(s.llm.openai_base_url)}">
        <div class="grid-2">
          <div><label>模型名稱</label><input id="s-openai_model" value="${esc(s.llm.openai_model)}"></div>
          <div><label>API key 環境變數名稱（只填名稱）</label><input id="s-openai_key_env" value="${esc(s.llm.openai_key_env)}" placeholder="例如 STRATA_API_KEY"></div>
        </div>
        <div class="row" style="margin-top:12px">
          <button type="button" class="btn" id="s-test">測試 LLM 連線</button>
          <span class="muted" id="s-test-out"></span>
        </div>
        <div class="warn" style="margin-top:12px;margin-bottom:0">LM Studio、Strata、ComfyUI 共用同一塊 GPU 記憶體，不要同時載入大模型。</div>
      </div>
      <div data-spane="tts" style="${activeTab === "tts" ? "" : "display:none"}">
        <label>audio.cpp 伺服器</label>
        <input id="t-base_url" value="${esc(s.tts.base_url)}">
        <div class="grid-2">
          <div><label>TTS 模型 id</label><input id="t-model" value="${esc(s.tts.model)}"></div>
          <div><label>聲音</label><select id="t-voice">${["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"].map((v) => `<option ${v === s.tts.voice ? "selected" : ""}>${v}</option>`).join("")}</select></div>
        </div>
        <label>語氣指示</label>
        <input id="t-instruct" value="${esc(s.tts.instruct)}">
        <label>字幕對齊模型 id（留空改用字數估算）</label>
        <input id="t-align_model" value="${esc(s.tts.align_model)}">
      </div>
      <div data-spane="pipeline" style="${activeTab === "pipeline" ? "" : "display:none"}">
        <label style="margin-top:0"><input type="checkbox" id="p-review_script" style="width:auto;margin-right:6px" ${s.pipeline.review_script ? "checked" : ""}> 講稿定稿前先給我看（初期建議開著；穩定後可關掉放手）</label>
        <div class="grid-2">
          <div><label>審稿通過門檻（每個角色至少幾分）</label><input id="p-critique_threshold" type="number" min="1" max="10" value="${s.pipeline.critique_threshold}"></div>
          <div><label>最多修稿幾輪</label><input id="p-critique_max_rounds" type="number" min="1" max="6" value="${s.pipeline.critique_max_rounds}"></div>
          <div><label>標題候選數</label><input id="p-title_count" type="number" min="2" max="12" value="${s.pipeline.title_count}"></div>
          <div><label>縮圖候選數</label><input id="p-thumbnail_count" type="number" min="2" max="8" value="${s.pipeline.thumbnail_count}"></div>
        </div>
      </div>`;

    openModal({
      title: "系統設定",
      bodyHtml,
      footHtml: `<button type="button" class="btn" id="s-cancel">關閉</button><button type="button" class="btn primary" id="s-save">儲存設定</button>`,
      width: 640,
      onMount: (root) => {
        $("#s-provider", root).value = s.llm.provider;
        const collect = () => {
          for (const k of ["provider", "claude_model", "openai_base_url", "openai_model", "openai_key_env"]) {
            s.llm[k] = $(`#s-${k}`, root).value;
          }
          for (const k of ["base_url", "model", "voice", "instruct", "align_model"]) {
            s.tts[k] = $(`#t-${k}`, root).value;
          }
          s.pipeline.review_script = $("#p-review_script", root).checked;
          for (const k of ["critique_threshold", "critique_max_rounds", "title_count", "thumbnail_count"]) {
            s.pipeline[k] = +$(`#p-${k}`, root).value;
          }
          return s;
        };
        $$("[data-stab]", root).forEach((b) => {
          b.onclick = () => {
            collect();
            activeTab = b.dataset.stab;
            $$("[data-stab]", root).forEach((x) => x.classList.toggle("on", x.dataset.stab === activeTab));
            $$("[data-spane]", root).forEach((p) => (p.style.display = p.dataset.spane === activeTab ? "" : "none"));
          };
        });
        $$("[data-lay]", root).forEach((b) => {
          b.onclick = () => {
            s.ui = { ...(s.ui || {}), nav_layout: b.dataset.lay };
            $$("[data-lay]", root).forEach((x) => x.classList.toggle("sel", x.dataset.lay === b.dataset.lay));
            applyNavLayout(b.dataset.lay, false);
          };
        });
        $("#s-cancel", root).onclick = closeModal;
        $("#s-save", root).onclick = async () => {
          const saved = await api("/api/settings", { method: "PUT", body: collect() });
          state.SETTINGS = saved;
          applyNavLayout(saved.ui?.nav_layout || "top", false);
          if (state.onStatusRefresh) state.onStatusRefresh();
          toast("已儲存設定");
          closeModal();
        };
        $("#s-test", root).onclick = async () => {
          await api("/api/settings", { method: "PUT", body: collect() });
          $("#s-test-out", root).textContent = "測試中…";
          const h = await api("/api/health?llm_check=true");
          $("#s-test-out", root).textContent = (h.llm.ok ? "✓ " : "✗ ") + h.llm.detail;
        };
      },
    });
  };
  draw();
}

export async function openNewEpisodeModal(prefill = {}) {
  const [ch, stylesRes] = await Promise.all([api("/api/channel"), api("/api/styles")]);
  const styles = stylesRes.items || [];
  const defaultStyle = prefill.style_id || stylesRes.active_id || (styles[0]?.id ?? "");
  const urls = Array.isArray(prefill.source_urls) ? prefill.source_urls.join("\n") : (prefill.source_urls || "");

  openModal({
    title: "做一支新的",
    width: 600,
    bodyHtml: `
      <p class="sub" style="margin-bottom:12px">給題目就好，agent 會自動蒐集資料、給切角簡報，到需要你決定時放進審核區。</p>
      ${!ch.name ? `<div class="warn">還沒填頻道名稱，建議順便到「風格」頁補齊頻道定位。</div>` : ""}
      <label>題目</label>
      <input id="ne-topic" value="${esc(prefill.topic || "")}" placeholder="例如：黃仁勳回應 AI 泡沫">
      <div class="grid-2">
        <div>
          <label>格式</label>
          <select id="ne-format">
            <option value="short">短片（直式 30–90 秒）</option>
            <option value="long">長片（橫式 3–8 分鐘）</option>
          </select>
        </div>
        <div>
          <label>採用風格卡</label>
          <select id="ne-style">
            ${styles.map((st) => `<option value="${esc(st.id)}" ${st.id === defaultStyle ? "selected" : ""}>${esc(st.icon)} ${esc(st.name)}</option>`).join("")}
          </select>
        </div>
      </div>
      <label>參考連結（一行一個；官方公告、對標影片頁、社群討論）</label>
      <textarea id="ne-urls" placeholder="https://...">${esc(urls)}</textarea>
      <label>你的觀點與想強調的點（選填）</label>
      <textarea id="ne-notes" placeholder="身為觀眾，我最好奇的是…；這些不要講…">${esc(prefill.notes || "")}</textarea>`,
    footHtml: `<button type="button" class="btn" id="ne-cancel">取消</button><button type="button" class="btn primary" id="ne-go">開始製作</button>`,
    onMount: (root) => {
      $("#ne-format", root).value = prefill.format === "long" ? "long" : "short";
      $("#ne-topic", root).focus();
      $("#ne-cancel", root).onclick = closeModal;
      $("#ne-go", root).onclick = async () => {
        try {
          const ep = await api("/api/episodes", {
            method: "POST",
            body: {
              topic: $("#ne-topic", root).value,
              format: $("#ne-format", root).value,
              style_id: $("#ne-style", root).value || null,
              idea_id: prefill.idea_id || null,
              source_urls: $("#ne-urls", root).value.split("\n"),
              notes: $("#ne-notes", root).value,
            },
          });
          closeModal();
          toast("已交給 agent 開始處理");
          location.hash = `#/ep/${encodeURIComponent(ep.id)}`;
        } catch (e) {
          toast(e.message);
        }
      };
    },
  });
}

export function openAddMetricModal(episodes, preselectId, onSaved) {
  const today = new Date().toISOString().slice(0, 10);
  if (!episodes.length) {
    toast("請先建立至少一集內容再錄入數據");
    return;
  }
  openModal({
    title: "錄入成效數據",
    width: 580,
    bodyHtml: `
      <label>集數</label>
      <select id="am-ep">
        ${episodes.map((e) => `<option value="${esc(e.id)}" ${e.id === preselectId ? "selected" : ""}>${esc(e.package_choice?.title || e.topic)}</option>`).join("")}
      </select>
      <div class="grid-2">
        <div>
          <label>平台</label>
          <select id="am-platform">
            <option>YouTube</option><option>Instagram</option><option>Facebook</option>
            <option>TikTok</option><option>小紅書</option><option>Bilibili</option><option>X</option>
          </select>
        </div>
        <div><label>日期</label><input id="am-date" type="date" value="${today}"></div>
      </div>
      <div class="grid-2">
        <div><label>觀看數</label><input id="am-views" placeholder="例如 12500 或 1.2萬"></div>
        <div><label>平均觀看／完播</label><input id="am-watch_time" placeholder="例如 00:42 或 58%"></div>
        <div><label>新追蹤</label><input id="am-followers" placeholder="例如 180"></div>
        <div><label>按讚</label><input id="am-likes" placeholder="例如 640"></div>
        <div><label>收藏</label><input id="am-saves" placeholder="例如 320"></div>
        <div><label>留言</label><input id="am-comments" placeholder="例如 45"></div>
      </div>
      <label>備註</label>
      <input id="am-note" placeholder="例如：前 3 秒留存率不錯">`,
    footHtml: `<button type="button" class="btn" id="am-cancel">取消</button><button type="button" class="btn primary" id="am-save">儲存數據</button>`,
    onMount: (root) => {
      $("#am-cancel", root).onclick = closeModal;
      $("#am-save", root).onclick = async () => {
        const eid = $("#am-ep", root).value;
        const body = {};
        for (const k of ["platform", "date", "views", "watch_time", "followers", "likes", "saves", "comments", "note"]) {
          body[k] = $(`#am-${k}`, root).value;
        }
        try {
          await api(`/api/episodes/${encodeURIComponent(eid)}/metrics`, { method: "POST", body });
          closeModal();
          toast("已錄入成效數據");
          if (onSaved) onSaved();
        } catch (e) {
          toast(e.message);
        }
      };
    },
  });
}

export function openImportCsvModal(onSaved) {
  const sample = `標題,平台,日期,觀看,平均觀看,新追蹤,讚,收藏,留言,備註\naudio.cpp,YouTube,${new Date().toISOString().slice(0, 10)},15200,00:45,210,820,430,38,首週自然流量佳`;
  openModal({
    title: "匯入 CSV 成效數據",
    width: 620,
    bodyHtml: `
      <p class="muted" style="margin-top:0">支援欄位（中英文皆可）：<code>標題</code>（或集數ID）、<code>平台</code>、<code>日期</code>、<code>觀看</code>、<code>平均觀看</code>、<code>新追蹤</code>、<code>讚</code>、<code>收藏</code>、<code>留言</code>、<code>備註</code>。</p>
      <label>貼上 CSV 內容</label>
      <textarea id="csv-text" rows="8" placeholder="${esc(sample)}"></textarea>
      <div id="csv-res" class="muted" style="margin-top:8px"></div>`,
    footHtml: `<button type="button" class="btn" id="csv-cancel">關閉</button><button type="button" class="btn primary" id="csv-go">開始匯入</button>`,
    onMount: (root) => {
      $("#csv-cancel", root).onclick = closeModal;
      $("#csv-go", root).onclick = async () => {
        try {
          const res = await api("/api/insights/import-csv", { method: "POST", body: { csv: $("#csv-text", root).value } });
          const skipTxt = res.skipped?.length ? `；略過 ${res.skipped.length} 筆（${res.skipped.slice(0, 2).join("；")}）` : "";
          toast(`已匯入 ${res.imported} 筆${skipTxt}`);
          if (res.imported > 0) {
            closeModal();
            if (onSaved) onSaved();
          } else {
            $("#csv-res", root).textContent = `匯入 0 筆${skipTxt}`;
          }
        } catch (e) {
          toast(e.message);
        }
      };
    },
  });
}

export function openStyleEditorModal(style, onSaved) {
  const isEdit = Boolean(style && style.id && !style.asCopy);
  const cats = state.META?.style_categories || ["科技數碼", "新聞快評", "知識科普", "觀點深度", "生活工具"];
  const cur = style || { icon: "✨", category: cats[0], words: [], avoid: [] };

  openModal({
    title: isEdit ? `編輯風格卡：${cur.name}` : "新增風格卡",
    width: 640,
    bodyHtml: `
      <div class="grid-2">
        <div><label>風格名稱</label><input id="st-name" value="${esc(cur.name || "")}" placeholder="例如：犀利科技短評"></div>
        <div class="row">
          <div style="width:90px"><label>圖示</label><input id="st-icon" value="${esc(cur.icon || "✨")}"></div>
          <div class="grow"><label>分類</label><select id="st-cat">${cats.map((c) => `<option ${c === cur.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
        </div>
      </div>
      <label>一句話定位</label><input id="st-summary" value="${esc(cur.summary || "")}">
      <label>語氣與用詞習慣</label><textarea id="st-tone">${esc(cur.tone || "")}</textarea>
      <label>開頭方式</label><textarea id="st-opening">${esc(cur.opening || "")}</textarea>
      <div class="grid-2">
        <div><label>內容結構</label><textarea id="st-structure">${esc(cur.structure || "")}</textarea></div>
        <div><label>節奏與斷句</label><textarea id="st-pacing">${esc(cur.pacing || "")}</textarea></div>
      </div>
      <div class="grid-2">
        <div><label>常用詞（用頓號或逗號分隔）</label><input id="st-words" value="${esc((cur.words || []).join("、"))}"></div>
        <div><label>絕對避開（用頓號或逗號分隔）</label><input id="st-avoid" value="${esc((cur.avoid || []).join("、"))}"></div>
      </div>
      ${!isEdit ? `<label style="margin-top:12px"><input type="checkbox" id="st-act" style="width:auto;margin-right:6px" checked> 建立後直接設為目前使用中風格</label>` : ""}`,
    footHtml: `
      ${isEdit && !cur.preset ? `<button type="button" class="btn danger" id="st-del" style="margin-right:auto">刪除這張風格卡</button>` : ""}
      <button type="button" class="btn" id="st-cancel">取消</button>
      <button type="button" class="btn primary" id="st-save">儲存風格卡</button>`,
    onMount: (root) => {
      $("#st-cancel", root).onclick = closeModal;
      $("#st-del", root) && ($("#st-del", root).onclick = async () => {
        if (!confirm(`確定刪除「${cur.name}」？`)) return;
        try {
          await api(`/api/styles/${encodeURIComponent(cur.id)}`, { method: "DELETE" });
          closeModal();
          toast("已刪除風格卡");
          if (onSaved) onSaved();
        } catch (e) { toast(e.message); }
      });
      $("#st-save", root).onclick = async () => {
        const body = {
          name: $("#st-name", root).value,
          icon: $("#st-icon", root).value,
          category: $("#st-cat", root).value,
          summary: $("#st-summary", root).value,
          tone: $("#st-tone", root).value,
          opening: $("#st-opening", root).value,
          structure: $("#st-structure", root).value,
          pacing: $("#st-pacing", root).value,
          words: $("#st-words", root).value,
          avoid: $("#st-avoid", root).value,
        };
        try {
          if (isEdit) {
            await api(`/api/styles/${encodeURIComponent(cur.id)}`, { method: "PUT", body });
          } else {
            body.activate = $("#st-act", root)?.checked ?? true;
            await api("/api/styles", { method: "POST", body });
          }
          closeModal();
          toast("已儲存風格卡");
          if (onSaved) onSaved();
        } catch (e) { toast(e.message); }
      };
    },
  });
}

export function openExtractStyleModal(episodes, onSaved) {
  let tab = "text";
  const withScripts = episodes.filter((e) => ["critique", "assemble", "package", "review", "approved"].includes(e.stage));
  openModal({
    title: "從文字或既有講稿提煉風格卡",
    width: 600,
    bodyHtml: `
      <div class="seg" style="margin-bottom:12px">
        <button type="button" data-ex="text" class="on">貼上文章／講稿</button>
        <button type="button" data-ex="eps">從本機集數選取</button>
      </div>
      <div data-exp="text">
        <label>貼上 1～3 篇你寫過的講稿或文章</label>
        <textarea id="ex-text" rows="7" placeholder="貼上文字內容，越多越準確…"></textarea>
      </div>
      <div data-exp="eps" style="display:none">
        <label>勾選已產出講稿的集數</label>
        <div style="max-height:200px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;padding:8px">
          ${withScripts.length ? withScripts.map((e) => `<label style="margin:4px 0"><input type="checkbox" class="ex-ep" value="${esc(e.id)}" style="width:auto;margin-right:6px">${esc(e.package_choice?.title || e.topic)}</label>`).join("") : `<div class="muted">目前還沒有產出講稿的集數。</div>`}
        </div>
      </div>
      <label>風格名稱（選填，留空讓 AI 自動命名）</label>
      <input id="ex-name" placeholder="例如：我的口播風格">`,
    footHtml: `<button type="button" class="btn" id="ex-cancel">取消</button><button type="button" class="btn primary" id="ex-go">開始提煉並啟用</button>`,
    onMount: (root) => {
      $("#ex-cancel", root).onclick = closeModal;
      $$("[data-ex]", root).forEach((b) => {
        b.onclick = () => {
          tab = b.dataset.ex;
          $$("[data-ex]", root).forEach((x) => x.classList.toggle("on", x.dataset.ex === tab));
          $$("[data-exp]", root).forEach((p) => (p.style.display = p.dataset.exp === tab ? "" : "none"));
        };
      });
      $("#ex-go", root).onclick = async () => {
        const btn = $("#ex-go", root);
        btn.disabled = true;
        btn.textContent = "提煉中…";
        try {
          const epIds = $$(".ex-ep:checked", root).map((x) => x.value);
          await api("/api/styles/extract", {
            method: "POST",
            body: {
              text: tab === "text" ? $("#ex-text", root).value : "",
              episode_ids: tab === "eps" ? epIds : [],
              name: $("#ex-name", root).value,
            },
          });
          closeModal();
          toast("已提煉並設為使用中風格");
          if (onSaved) onSaved();
        } catch (e) {
          toast(e.message);
          btn.disabled = false;
          btn.textContent = "開始提煉並啟用";
        }
      };
    },
  });
}
