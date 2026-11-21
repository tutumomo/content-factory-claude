import { $, $$, api, applyNavLayout, closeModal, esc, getNavLayout, openModal, state, toast } from "./lib.js?v=20261121g";

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
      ["visual", "畫面與音效"],
      ["youtube", "YouTube"],
    ];
    const yt = s.youtube || {};
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
          <div><label>TTS 模型 id</label><select id="t-model"><option value="${esc(s.tts.model)}" selected>${esc(s.tts.model)}</option></select></div>
          <div><label>參考音色</label><select id="t-voice"><option value="${esc(s.tts.voice || "")}" selected>${esc(s.tts.voice || "（模型預設）")}</option></select></div>
        </div>
        <div class="muted" style="margin-top:4px">內建聲音（vivian…）只適用 Qwen3 CustomVoice；參考音色庫來自 audio.cpp 的 voice_dir，要搭配 clon 模型（qwen3 Base、IndexTTS2.5 等）。留空＝模型預設。</div>
        <div class="row" style="margin-top:4px"><button type="button" class="btn" id="t-models-refresh">重新讀取模型清單</button><span class="muted" id="t-models-out"></span><span class="muted">清單來自 audio.cpp 已下載的語音模型</span></div>
        <label>語氣指示</label>
        <input id="t-instruct" value="${esc(s.tts.instruct)}">
        <label>參考音檔路徑（單一檔案，優先於上方參考音色；index-tts2.5、zonos3-mini 必填；qwen3 模型可留空）</label>
        <input id="t-voice_ref" value="${esc(s.tts.voice_ref || "")}" placeholder="/home/altos/…/ref.wav">
        <div class="grid-2">
          <div><label>情緒示範文字（index-tts2.5 用）</label><input id="t-emotion" value="${esc(s.tts.emotion || "")}"></div>
          <div><label>情緒強度 0–1</label><input id="t-emotion_alpha" type="number" min="0" max="1" step="0.1" value="${s.tts.emotion_alpha ?? 1}"></div>
        </div>
        <label style="margin-top:0"><input type="checkbox" id="t-convert_simplified" style="width:auto;margin-right:6px" ${s.tts?.convert_simplified !== false ? "checked" : ""}> 送 TTS 前先把繁體轉簡體（audio.cpp 讀繁體字常出錯；字幕仍用原文）</label>
        <label style="margin-top:0"><input type="checkbox" id="t-per_scene_emotion" style="width:auto;margin-right:6px" ${s.tts?.per_scene_emotion ? "checked" : ""}> 每段套用講稿情緒（qwen3 的語氣指令會讓聲音聽起來像換人，想固定同一個聲音就關掉）</label>
        <label>字幕對齊模型 id（留空改用字數估算）</label>
        <input id="t-align_model" value="${esc(s.tts.align_model)}">
      </div>
      <div data-spane="pipeline" style="${activeTab === "pipeline" ? "" : "display:none"}">
        <label style="margin-top:0"><input type="checkbox" id="p-review_script" style="width:auto;margin-right:6px" ${s.pipeline.review_script ? "checked" : ""}> 講稿定稿前先給我看（初期建議開著；穩定後可關掉放手）</label>
        <label style="margin-top:0"><input type="checkbox" id="p-review_storyboard" style="width:auto;margin-right:6px" ${s.pipeline.review_storyboard !== false ? "checked" : ""}> 配音與生圖前先看分鏡（縮圖＋旁白＋預估秒數，便宜又早攔錯）</label>
        <div class="grid-2">
          <div><label>審稿通過門檻（每個角色至少幾分）</label><input id="p-critique_threshold" type="number" min="1" max="10" value="${s.pipeline.critique_threshold}"></div>
          <div><label>最多修稿幾輪</label><input id="p-critique_max_rounds" type="number" min="1" max="6" value="${s.pipeline.critique_max_rounds}"></div>
          <div><label>標題候選數</label><input id="p-title_count" type="number" min="2" max="12" value="${s.pipeline.title_count}"></div>
          <div><label>縮圖候選數</label><input id="p-thumbnail_count" type="number" min="2" max="8" value="${s.pipeline.thumbnail_count}"></div>
          <div><label>雷達每次至少幾條</label><input id="p-radar_min" type="number" min="3" max="12" value="${s.pipeline.radar_min}"></div>
          <div><label>雷達每次最多幾條</label><input id="p-radar_max" type="number" min="3" max="12" value="${s.pipeline.radar_max}"></div>
          <div><label>畫面變化警告門檻（0–1，越高越寬鬆）</label><input id="p-slideshow_risk_max" type="number" min="0" max="1" step="0.05" value="${s.pipeline.slideshow_risk_max ?? 0.7}"></div>
          <div><label>雲端花費月上限（美元）</label><input id="p-cost_cap" type="number" min="0" step="0.5" value="${s.cost?.monthly_cap_usd ?? 10}"></div>
          <div><label>單筆花費核准門檻（美元，超過先問你）</label><input id="p-cost_gate" type="number" min="0" step="0.1" value="${s.cost?.per_call_approval_usd ?? 0.5}"></div>
        </div>
        <div class="muted" style="margin-top:6px">本月已用：<span id="p-cost-spent">讀取中…</span>（Lyria 每首 $0.04／$0.08；帳本 data/cost/ledger.jsonl）</div>
      </div>
      <div data-spane="visual" style="${activeTab === "visual" ? "" : "display:none"}">
        <label>畫面來源</label>
        <select id="v-source">
          <option value="slides" ${(s.visuals?.source || "slides") === "slides" ? "selected" : ""}>設計字卡（Pillow，快、穩、不吃 GPU）</option>
          <option value="comfy" ${s.visuals?.source === "comfy" ? "selected" : ""}>ComfyUI 生圖當底（文字疊在上面）</option>
          <option value="stock" ${s.visuals?.source === "stock" ? "selected" : ""}>免費實拍素材（Pexels／Pixabay，真動態畫面）</option>
          <option value="mix" ${s.visuals?.source === "mix" ? "selected" : ""}>混合：有素材用素材，其餘生圖／字卡</option>
          <option value="h3video" ${s.visuals?.source === "h3video" ? "selected" : ""}>ComfyUI MiniMax-H3 生影片（每段一段 AI 動態畫面，文字疊上去）</option>
        </select>
        <div class="grid-2">
          <div><label>Pexels 金鑰環境變數名稱（只填名稱，免費申請）</label><input id="v-pexels_key_env" value="${esc(s.visuals?.pexels_key_env || "PEXELS_API_KEY")}"></div>
          <div><label>Pixabay 金鑰環境變數名稱</label><input id="v-pixabay_key_env" value="${esc(s.visuals?.pixabay_key_env || "PIXABAY_API_KEY")}"></div>
        </div>
        <div class="row" style="margin-top:4px"><button type="button" class="btn" id="v-stock-check">檢查素材來源</button><span class="muted" id="v-stock-out"></span></div>
        <label>ComfyUI 位址</label>
        <input id="v-comfy_url" value="${esc(s.visuals?.comfy_url || "http://127.0.0.1:8188")}">
        <label>圖像模型組合（自動偵測已安裝；套用會蓋掉 UNET／CLIP／VAE／步數／CFG）</label>
        <select id="v-preset"><option value="">（維持下面的手動設定）</option></select>
        <div class="muted" id="v-preset-note" style="margin-top:4px"></div>
        <div class="grid-2">
          <div><label>UNET</label><input id="v-unet" value="${esc(s.visuals?.unet || "")}"></div>
          <div><label>CLIP（type 固定 krea2）</label><input id="v-clip" value="${esc(s.visuals?.clip || "")}"></div>
          <div><label>VAE</label><input id="v-vae" value="${esc(s.visuals?.vae || "")}"></div>
          <div><label>LoRA（留空不用）</label><input id="v-lora" value="${esc(s.visuals?.lora || "")}"></div>
          <div><label>步數</label><input id="v-steps" type="number" min="1" max="30" value="${s.visuals?.steps ?? 8}"></div>
          <div><label>CFG</label><input id="v-cfg" type="number" min="1" max="10" step="0.1" value="${s.visuals?.cfg ?? 1}"></div>
        </div>
        <label>生圖風格提示（英文，接在每個畫面描述後面）</label>
        <input id="v-style_hint" value="${esc(s.visuals?.style_hint || "")}">
        <div class="grid-2">
          <div><label>單張逾時（秒）</label><input id="v-timeout_s" type="number" min="60" max="3600" value="${s.visuals?.timeout_s ?? 600}"></div>
          <div style="display:flex;align-items:flex-end"><label style="margin:0"><input type="checkbox" id="v-free_after" style="width:auto;margin-right:6px" ${s.visuals?.free_after !== false ? "checked" : ""}> 生完圖釋放 ComfyUI 模型（把 GPU 還給別的工作）</label></div>
        </div>
        <div class="row" style="margin-top:10px"><button type="button" class="btn" id="v-health">測試 ComfyUI 連線</button><span class="muted" id="v-health-out"></span></div>
        <div class="warn" style="margin-top:10px">ComfyUI、LM Studio、Strata 共用同一塊 GPU 記憶體。生圖那一段時間不要把兩個大模型同時開著。</div>
        <h2 style="margin-top:18px">MiniMax-H3 影片（畫面來源選 h3video 時使用）</h2>
        <label style="margin-top:0"><input type="checkbox" id="h-enabled" style="width:auto;margin-right:6px" ${s.h3video?.enabled !== false ? "checked" : ""}> 啟用 H3 影片</label>
        <div class="grid-2">
          <div><label>UNET</label><input id="h-unet" value="${esc(s.h3video?.unet || "")}"></div>
          <div><label>CLIP</label><input id="h-clip" value="${esc(s.h3video?.clip || "")}"></div>
          <div><label>VAE（影片用，不是生圖那顆）</label><input id="h-vae" value="${esc(s.h3video?.vae || "")}"></div>
          <div><label>音訊 VAE（H3 同時生環境音）</label><input id="h-audio_vae" value="${esc(s.h3video?.audio_vae || "")}"></div>
          <div><label>環境音音量（相對旁白 dB；≤ -60 靜音）</label><input id="h-ambient_gain_db" type="number" min="-60" max="0" value="${s.h3video?.ambient_gain_db ?? -14}"></div>
          <div><label>取樣器</label><input id="h-sampler" value="${esc(s.h3video?.sampler || "res_multistep")}"></div>
          <div><label>步數</label><input id="h-steps" type="number" min="1" max="50" value="${s.h3video?.steps ?? 25}"></div>
          <div><label>單段最長秒數</label><input id="h-max_seconds" type="number" min="2" max="15" value="${s.h3video?.max_seconds ?? 6}"></div>
          <div><label>生成畫素（百萬；0.4 ≈ 650×650）</label><input id="h-megapixels" type="number" min="0.15" max="1.2" step="0.05" value="${s.h3video?.megapixels ?? 0.4}"></div>
          <div><label>單段逾時（秒）</label><input id="h-timeout_s" type="number" min="120" max="7200" value="${s.h3video?.timeout_s ?? 1800}"></div>
        </div>
        <label>影片風格提示（英文，接在畫面描述前面）</label>
        <input id="h-style_hint" value="${esc(s.h3video?.style_hint || "")}">
        <div class="muted" style="margin-top:6px">H3 每段 2–15 秒、24 fps；旁白比影片長時影片會循環補滿。H3 會同時生成環境音，墊在旁白下面（循環時一起循環），再疊音效與音樂。生每段都要重載 32B 文字編碼器，很吃時間，段數多就先少跑幾段試。</div>
        <h2 style="margin-top:18px">音效</h2>
        <label style="margin-top:0"><input type="checkbox" id="x-enabled" style="width:auto;margin-right:6px" ${s.sfx?.enabled !== false ? "checked" : ""}> 每個畫面開頭墊一個音效（講稿有指定才放）</label>
        <div class="grid-2">
          <div><label>音效音量（相對旁白，dB）</label><input id="x-gain_db" type="number" min="-40" max="0" value="${s.sfx?.gain_db ?? -16}"></div>
          <div><label>音效庫資料夾（留空 = data/sfx）</label><input id="x-library_dir" value="${esc(s.sfx?.library_dir || "")}"></div>
        </div>
        <label>音效模型（留空 = 內建 MOSS-SoundEffect-v2）</label>
        <input id="x-model_path" value="${esc(s.sfx?.model_path || "")}">
        <div class="card" style="margin:12px 0 0" id="x-lib"><span class="muted">讀取音效庫…</span></div>
        <div class="row" style="margin-top:10px">
          <button type="button" class="btn primary" id="x-build">生成缺的音效（本機模型）</button>
          <button type="button" class="btn" id="x-import">從資料夾匯入</button>
          <span class="muted" id="x-out"></span>
        </div>
        <div class="muted" style="margin-top:8px">檔名規則：<code>標籤__備註.wav</code>，例如 <code>whoosh__1.wav</code>。沒有對應音效的畫面只留旁白，不會自動猜。</div>
        <h2 style="margin-top:18px">背景音樂</h2>
        <label style="margin-top:0"><input type="checkbox" id="m-enabled" style="width:auto;margin-right:6px" ${s.music?.enabled !== false ? "checked" : ""}> 成片墊一層生成的純音樂（無人聲）</label>
        <label>音樂引擎</label>
        <select id="m-provider">
          <option value="audiocpp" ${(s.music?.provider || "audiocpp") === "audiocpp" ? "selected" : ""}>audio.cpp YuE2 3B（本機 GPU）</option>
          <option value="lyria" ${s.music?.provider === "lyria" ? "selected" : ""}>Google Lyria 3（Gemini API，雲端）</option>
        </select>
        <div id="m-ac" style="${s.music?.provider === "lyria" ? "display:none" : ""}">
          <div class="grid-2" style="margin-top:8px">
            <div><label>音樂模型（自動讀取 audio.cpp 已安裝的音樂生成模型）</label><select id="m-model"><option value="${esc(s.music?.model || "yue2")}" selected>${esc(s.music?.model || "yue2")}</option></select></div>
            <div><label>seed</label><input id="m-seed" type="number" value="${s.music?.seed ?? 1234}"></div>
          </div>
          <div class="row" style="margin-top:4px"><button type="button" class="btn" id="m-models-refresh">重新讀取模型清單</button><span class="muted" id="m-models-out"></span></div>
        </div>
        <div id="m-ly" style="${s.music?.provider === "lyria" ? "" : "display:none"}">
          <div class="grid-2" style="margin-top:8px">
            <div><label>Lyria 模型</label><select id="m-lyria_model">${[["lyria-3-clip-preview", "Lyria 3 Clip（固定 30 秒，成片時 loop，$0.04/首）"], ["lyria-3-pro-preview", "Lyria 3 Pro（完整歌曲約 3 分鐘，$0.08/首）"]].map(([v, l]) => `<option value="${v}" ${v === (s.music?.lyria_model || "lyria-3-clip-preview") ? "selected" : ""}>${l}</option>`).join("")}${![["lyria-3-clip-preview"], ["lyria-3-pro-preview"]].some(([v]) => v === s.music?.lyria_model) && s.music?.lyria_model ? `<option value="${esc(s.music.lyria_model)}" selected>${esc(s.music.lyria_model)}（舊版，建議改選 Clip 或 Pro）</option>` : ""}</select></div>
            <div><label>API 金鑰環境變數名稱</label><input id="m-lyria_key_env" value="${esc(s.music?.lyria_key_env || "GEMINI_API_KEY")}"></div>
          </div>
          <div class="muted" style="margin-top:4px">走 Gemini API（generativelanguage.googleapis.com）；金鑰需有額度、專案未達月上限。Lyria 音訊含 SynthID 浮水印。</div>
        </div>
        <label>預設風格（英文；留空 = 內建 lo-fi。講稿的 music 欄位優先）</label>
        <input id="m-style" value="${esc(s.music?.style || "")}">
        <div class="grid-2">
          <div><label>音樂音量（相對旁白，dB）</label><input id="m-gain_db" type="number" min="-40" max="0" value="${s.music?.gain_db ?? -20}"></div>
          <div style="display:flex;align-items:flex-end"><label style="margin:0"><input type="checkbox" id="m-duck" style="width:auto;margin-right:6px" ${s.music?.duck !== false ? "checked" : ""}> 旁白講話時自動壓低音樂</label></div>
        </div>
        <div class="row" style="margin-top:10px"><button type="button" class="btn" id="m-preview">試聽 20 秒</button><span class="muted" id="m-out"></span></div>
        <div id="m-player" style="margin-top:8px"></div>
        <h2 style="margin-top:18px">成片引擎</h2>
        <select id="r-engine">
          <option value="ffmpeg" ${(s.render?.engine || "ffmpeg") === "ffmpeg" ? "selected" : ""}>ffmpeg（燒字幕，快、穩）</option>
          <option value="remotion" ${s.render?.engine === "remotion" ? "selected" : ""}>Remotion（React 動態排版與轉場）</option>
        </select>
        <div class="muted" style="margin-top:6px">Remotion 模式用同一份講稿、畫面與時間軸渲染動畫版成片；失敗且勾了 fallback 時自動退回 ffmpeg。<span id="r-out"></span></div>
        <label style="margin-top:8px"><input type="checkbox" id="r-fallback_ffmpeg" style="width:auto;margin-right:6px" ${s.render?.fallback_ffmpeg !== false ? "checked" : ""}> Remotion 失敗時自動退回 ffmpeg</label>
      </div>
      <div data-spane="youtube" style="${activeTab === "youtube" ? "" : "display:none"}">
        <div class="card" style="margin:0 0 12px" id="yt-box"><span class="muted">讀取登入狀態…</span></div>
        <label>Google OAuth 用戶端檔（Desktop 類型 client_secret_*.json）</label>
        <select id="y-client_file"><option value="${esc(yt.client_file || "")}">${esc(yt.client_file || "自動偵測")}</option></select>
        <div class="grid-2">
          <div><label>上傳後的公開狀態</label><select id="y-privacy">${[["private", "私人（建議，先在 Studio 檢查）"], ["unlisted", "不公開"], ["public", "公開"]].map(([v, l]) => `<option value="${v}" ${v === (yt.privacy || "private") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div><label>影片類別</label><select id="y-category_id">${[["28", "科學與技術"], ["27", "教育"], ["25", "新聞與政治"], ["22", "人物與網誌"], ["24", "娛樂"]].map(([v, l]) => `<option value="${v}" ${v === String(yt.category_id || "28") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        </div>
        <label style="margin-top:10px"><input type="checkbox" id="y-made_for_kids" style="width:auto;margin-right:6px" ${yt.made_for_kids ? "checked" : ""}> 這是為兒童打造的內容</label>
        <div class="muted" style="margin-top:8px">有設排期的集數會以「私人 + 預定發布時間」上傳，時間到 YouTube 自動公開。</div>
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
          for (const k of ["base_url", "model", "voice", "instruct", "voice_ref", "emotion"]) {
            s.tts[k] = $(`#t-${k}`, root).value;
          }
          s.tts.emotion_alpha = +$("#t-emotion_alpha", root).value;
          s.tts.per_scene_emotion = $("#t-per_scene_emotion", root).checked;
          s.tts.convert_simplified = $("#t-convert_simplified", root).checked;
          s.youtube = { ...(s.youtube || {}), client_file: $("#y-client_file", root).value,
            privacy: $("#y-privacy", root).value, category_id: $("#y-category_id", root).value,
            made_for_kids: $("#y-made_for_kids", root).checked };
          s.pipeline.review_script = $("#p-review_script", root).checked;
          s.pipeline.review_storyboard = $("#p-review_storyboard", root).checked;
          for (const k of ["critique_threshold", "critique_max_rounds", "title_count", "thumbnail_count", "radar_min", "radar_max"]) {
            s.pipeline[k] = +$(`#p-${k}`, root).value;
          }
          s.pipeline.slideshow_risk_max = +$("#p-slideshow_risk_max", root).value;
          s.cost = { ...(s.cost || {}) };
          s.cost.monthly_cap_usd = +$("#p-cost_cap", root).value;
          s.cost.per_call_approval_usd = +$("#p-cost_gate", root).value;
          s.visuals = { ...(s.visuals || {}) };
          for (const k of ["source", "comfy_url", "unet", "clip", "vae", "lora", "style_hint", "pexels_key_env", "pixabay_key_env"]) {
            s.visuals[k] = $(`#v-${k}`, root).value;
          }
          for (const k of ["steps", "cfg", "timeout_s"]) s.visuals[k] = +$(`#v-${k}`, root).value;
          s.visuals.free_after = $("#v-free_after", root).checked;
          s.h3video = { ...(s.h3video || {}) };
          for (const k of ["unet", "clip", "vae", "audio_vae", "sampler", "style_hint"]) s.h3video[k] = $(`#h-${k}`, root).value;
          for (const k of ["steps", "max_seconds", "megapixels", "timeout_s", "ambient_gain_db"]) s.h3video[k] = +$(`#h-${k}`, root).value;
          s.h3video.enabled = $("#h-enabled", root).checked;
          s.sfx = { ...(s.sfx || {}) };
          for (const k of ["library_dir", "model_path"]) s.sfx[k] = $(`#x-${k}`, root).value;
          s.sfx.gain_db = +$("#x-gain_db", root).value;
          s.sfx.enabled = $("#x-enabled", root).checked;
          s.music = { ...(s.music || {}) };
          for (const k of ["provider", "model", "style", "lyria_model", "lyria_key_env"]) s.music[k] = $(`#m-${k}`, root).value;
          s.music.gain_db = +$("#m-gain_db", root).value;
          s.music.seed = +$("#m-seed", root).value;
          s.music.enabled = $("#m-enabled", root).checked;
          s.music.duck = $("#m-duck", root).checked;
          s.render = { ...(s.render || {}), engine: $("#r-engine", root).value,
            fallback_ffmpeg: $("#r-fallback_ffmpeg", root).checked };
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
        setupYouTubePane(root, s, collect);
        setupTtsModels(root, s);
        setupVisualPane(root, s, collect);
        api("/api/cost").then((c) => {
          const el = $("#p-cost-spent", root);
          if (el) el.textContent = `$${(c.spent_usd ?? 0).toFixed(2)}／$${(c.monthly_cap_usd ?? 0).toFixed(2)}`;
        }).catch(() => {});
      },
    });
  };
  draw();
}

/** One-click Google sign-in: opens the consent popup, resolves with /api/youtube/status when it closes. */
export function loginGoogle() {
  return new Promise((resolve) => {
    const w = window.open("/api/youtube/login", "yt-login", "width=520,height=680");
    if (!w) { toast("瀏覽器擋住了登入視窗，請允許彈出視窗"); api("/api/youtube/status").then(resolve); return; }
    let finished = false;
    const done = async () => {
      if (finished) return;
      finished = true;
      window.removeEventListener("message", onMsg);
      clearInterval(timer);
      const st = await api("/api/youtube/status");
      if (st.logged_in) toast("Google 登入完成");
      resolve(st);
    };
    const onMsg = (e) => { if (e.origin === location.origin && e.data?.type === "youtube-login") done(); };
    window.addEventListener("message", onMsg);
    const timer = setInterval(() => { if (w.closed) done(); }, 1000);
  });
}

async function setupTtsModels(root, s) {
  const sel = $("#t-model", root);
  const out = $("#t-models-out", root);
  const options = (keep, rows) => rows.map((m) =>
    `<option value="${esc(m.id)}" ${m.id === keep ? "selected" : ""}>${esc(m.id)}（${esc(m.family || m.task || "")}${m.loaded ? "・已載入" : ""}）</option>`).join("");

  const load = async () => {
    const keep = sel.value || s.tts.model || "";
    out.textContent = "讀取模型清單…";
    try {
      const base = $("#t-base_url", root)?.value || s.tts.base_url;
      const res = await api(`/api/tts/models?base_url=${encodeURIComponent(base)}`);
      const rows = res.models || [];
      sel.innerHTML = options(keep, rows);
      if (keep && !rows.some((m) => m.id === keep)) {
        sel.insertAdjacentHTML("afterbegin", `<option value="${esc(keep)}" selected>${esc(keep)}（伺服器上沒有這個 id）</option>`);
      }
      if (!rows.length) sel.innerHTML = `<option value="${esc(keep)}" selected>${esc(keep)}</option>`;
      fillVoices(root, s, res);
      out.textContent = res.ok
        ? `已讀到 ${rows.length} 個語音模型、${(res.voices || []).length} 個參考音色`
        : (res.detail || "伺服器上沒有語音模型");
    } catch (e) {
      sel.innerHTML = `<option value="${esc(keep)}" selected>${esc(keep)}</option>`;
      out.textContent = `讀不到模型清單：${e.message}（保留原本的 id）`;
    }
  };

  $("#t-models-refresh", root).onclick = load;
  await load();
}

function fillVoices(root, s, res) {
  const vsel = $("#t-voice", root);
  if (!vsel) return;
  const cur = vsel.value || s.tts?.voice || "";
  const opt = (v) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(v)}</option>`;
  vsel.innerHTML = `<option value="" ${cur ? "" : "selected"}>（模型預設）</option>`
    + `<optgroup label="內建聲音（Qwen3 CustomVoice）">${(res.builtin || []).map(opt).join("")}</optgroup>`
    + ((res.voices || []).length ? `<optgroup label="參考音色庫">${res.voices.map(opt).join("")}</optgroup>` : "");
  if (cur && ![...vsel.options].some((o) => o.value === cur)) {
    vsel.insertAdjacentHTML("beforeend", `<optgroup label="目前設定">${opt(cur)}</optgroup>`);
  }
}

async function setupYouTubePane(root, s, collect) {
  const box = $("#yt-box", root);
  const sel = $("#y-client_file", root);
  api("/api/youtube/clients").then((files) => {
    const cur = s.youtube?.client_file || "";
    sel.innerHTML = `<option value="">自動偵測${files[0] ? `（${esc(files[0].project_id)}）` : ""}</option>` +
      files.map((f) => `<option value="${esc(f.path)}" ${f.path === cur ? "selected" : ""}>${esc(f.project_id)}｜${esc(f.path.split("/").pop().slice(0, 40))}</option>`).join("") +
      (cur && !files.some((f) => f.path === cur) ? `<option value="${esc(cur)}" selected>${esc(cur)}</option>` : "");
  }).catch(() => {});

  const render = (st) => {
    if (st.logged_in) {
      const ch = st.channel;
      box.innerHTML = `<div class="row"><span class="grow">✓ 已登入 Google ${ch ? `・頻道 <b>${esc(ch.title)}</b>` : `・<span style="color:var(--bad)">此帳號沒有 YouTube 頻道</span>`}
        <div class="muted">Cloud 專案：${esc(st.project_id || "")}</div>${st.channel_error ? `<div class="muted" style="color:var(--bad)">${esc(st.channel_error)}</div>` : ""}</span>
        <button type="button" class="btn" id="yt-relogin">換帳號</button><button type="button" class="btn danger" id="yt-logout">登出</button></div>`;
    } else {
      box.innerHTML = `<div class="row"><span class="grow">尚未登入 Google 帳號
        ${st.client?.ok ? "" : `<div class="muted" style="color:var(--bad)">${esc(st.client?.error || "")}</div>`}</span>
        <button type="button" class="btn primary" id="yt-login" ${st.client?.ok ? "" : "disabled"}>用 Google 帳號登入</button></div>`;
    }
    const login = $("#yt-login", box) || $("#yt-relogin", box);
    if (login) login.onclick = () => startLogin();
    const out = $("#yt-logout", box);
    if (out) out.onclick = async () => { render(await api("/api/youtube/logout", { method: "POST" })); toast("已登出 Google"); };
  };

  const startLogin = async () => {
    await api("/api/settings", { method: "PUT", body: collect() }); // use the client file currently picked
    box.innerHTML = `<span class="muted">請在跳出的 Google 視窗選帳號並同意授權…</span>`;
    render(await loginGoogle());
  };

  try { render(await api("/api/youtube/status")); } catch (e) { box.textContent = e.message; }
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

export function openVideoStyleModal(onSaved) {
  openModal({
    title: "從參考影片分析節奏",
    bodyHtml: `<p class="sub" style="margin-bottom:12px">貼一支參考影片（YouTube／Shorts／Reels 連結或本機路徑）。用 ffmpeg 量切點、鏡頭長度與音量，再請 LLM 產出風格卡；只新增，不會自動套用。</p>
      <label>參考影片網址或本機路徑</label><input id="rv-url" placeholder="https://www.youtube.com/watch?v=…">
      <label>風格名稱（選填，留空讓 AI 命名）</label><input id="rv-name">
      <div class="muted" id="rv-out" style="margin-top:8px"></div>`,
    footHtml: `<button type="button" class="btn" id="rv-cancel">取消</button><button type="button" class="btn primary" id="rv-go">開始分析</button>`,
    width: 560,
    onMount: (root) => {
      $("#rv-cancel", root).onclick = closeModal;
      $("#rv-go", root).onclick = async () => {
        const url = $("#rv-url", root).value.trim();
        if (!url) return toast("請貼影片網址或路徑");
        const btn = $("#rv-go", root);
        btn.disabled = true;
        btn.textContent = "分析中…";
        $("#rv-out", root).textContent = "下載與量測中（長片可能要幾分鐘）…";
        try {
          const r = await api("/api/styles/from-video", { method: "POST", body: { url, name: $("#rv-name", root).value } });
          const s = r.stats || {};
          $("#rv-out", root).textContent =
            `✓ 已建立風格「${r.style?.name || ""}」：${s.cuts} 個切點、平均鏡頭 ${s.avg_shot} 秒、每分鐘 ${s.cut_density_per_min} 刀`;
          toast("已新增風格卡（未自動套用）");
          if (onSaved) onSaved();
          btn.disabled = false;
          btn.textContent = "再分析一支";
        } catch (e) {
          $("#rv-out", root).textContent = "✗ " + e.message;
          btn.disabled = false;
          btn.textContent = "開始分析";
        }
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

async function setupVisualPane(root, s, collect) {
  const out = $("#x-out", root);
  const lib = $("#x-lib", root);
  const renderLib = (st) => {
    const tags = (st.tags || []).map((t) => `<span class="pill" style="${t.count ? "" : "opacity:.45"}">${esc(t.label)} ${t.count}</span>`).join(" ");
    const b = st.build || {};
    lib.innerHTML = `<div class="row"><b class="grow">音效庫：${st.total} 個檔</b><span class="muted">${esc(st.dir)}</span></div>
      <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">${tags}</div>
      ${b.running ? `<div class="muted" style="margin-top:8px">生成中 ${b.done}/${b.total}（${esc(b.current)}）…</div>` : ""}
      <div class="muted" style="margin-top:8px">模型：${st.model.ok ? "✓ 在" : "✗ 找不到"} <code>${esc(st.model.path)}</code>${st.model.cli ? "" : "・缺 audiocpp_cli"}</div>`;
  };
  const load = async () => {
    try { renderLib(await api("/api/sfx")); } catch (e) { lib.textContent = e.message; }
  };
  load();
  const presetSel = $("#v-preset", root);
  const presetNote = $("#v-preset-note", root);
  api("/api/visuals/presets").then((res) => {
    const cur = s.visuals?.unet || "";
    for (const p of res.presets || []) {
      presetSel.insertAdjacentHTML("beforeend",
        `<option value="${esc(p.id)}">${esc(p.label)}${p.installed ? "" : "（未安裝）"}${(p.unet || "") === cur ? "・目前" : ""}</option>`);
    }
    const apply = () => {
      const p = (res.presets || []).find((x) => x.id === presetSel.value);
      if (!p) { presetNote.textContent = ""; return; }
      $("#v-unet", root).value = p.unet;
      $("#v-clip", root).value = p.clip;
      $("#v-vae", root).value = p.vae;
      $("#v-steps", root).value = p.steps;
      $("#v-cfg", root).value = p.cfg;
      s.visuals = { ...(s.visuals || {}), clip_type: p.clip_type, encode: p.encode || "", sampler: p.sampler };
      if (p.timeout_s) $("#v-timeout_s", root).value = p.timeout_s;
      presetNote.textContent = (p.installed ? "" : `✗ 檔案缺：${p.missing.join("、")}　`) + p.note;
    };
    presetSel.onchange = apply;
    const matched = (res.presets || []).find((x) => x.unet === cur);
    if (matched) { presetSel.value = matched.id; apply(); }
  }).catch(() => {});
  $("#v-stock-check", root).onclick = async () => {
    const out = $("#v-stock-out", root);
    out.textContent = "檢查中…";
    await api("/api/settings", { method: "PUT", body: collect() });
    const st = await api("/api/stock").catch((e) => ({ detail: e.message }));
    out.textContent = (st.providers?.length ? "✓ " : "✗ ") + (st.detail || "") +
      (st.cached ? `・已快取 ${st.cached} 段` : "");
  };
  $("#v-health", root).onclick = async () => {
    $("#v-health-out", root).textContent = "測試中…";
    await api("/api/settings", { method: "PUT", body: collect() });
    const h = await api("/api/visuals/health").catch((e) => ({ ok: false, detail: e.message }));
    $("#v-health-out", root).textContent = (h.ok ? "✓ " : "✗ ") + h.detail;
  };
  $("#x-build", root).onclick = async () => {
    await api("/api/settings", { method: "PUT", body: collect() });
    const r = await api("/api/sfx/build", { method: "POST", body: {} }).catch((e) => ({ started: false, error: e.message }));
    if (!r.started) return toast(r.error || "無法開始");
    out.textContent = "開始生成，一個一個跑（第一次載模型約一分鐘）…";
    const t = setInterval(async () => {
      const st = await api("/api/sfx").catch(() => null);
      if (!st) return;
      renderLib(st);
      if (!st.build.running) { clearInterval(t); out.textContent = "生成結束"; }
    }, 4000);
  };
  $("#x-import", root).onclick = async () => {
    const folder = prompt("要匯入的音效資料夾（絕對路徑）：");
    if (!folder) return;
    const r = await api("/api/sfx/import", { method: "POST", body: { folder } }).catch((e) => ({ error: e.message }));
    if (r.error) return toast(r.error);
    toast(`匯入 ${r.copied.length} 個`);
    load();
  };
  const mout = $("#m-out", root);
  const musicModel = $("#m-model", root);
  const musicModelsOut = $("#m-models-out", root);
  const syncMusicPane = () => {
    const lyria = $("#m-provider", root).value === "lyria";
    $("#m-ac", root).style.display = lyria ? "none" : "";
    $("#m-ly", root).style.display = lyria ? "" : "none";
  };
  const loadMusicModels = async () => {
    const keep = musicModel.value || s.music?.model || "";
    musicModelsOut.textContent = "讀取模型清單…";
    try {
      const st = await api("/api/music");
      const rows = st.available || [];
      const selected = rows.some((m) => m.id === keep)
        ? keep : (rows.some((m) => m.id === st.model) ? st.model : keep);
      musicModel.innerHTML = rows.map((m) =>
        `<option value="${esc(m.id)}" ${m.id === selected ? "selected" : ""}>${esc(m.id)}（${esc(m.family || "")}${m.loaded ? "・已載入" : ""}）</option>`).join("");
      if (selected && !rows.some((m) => m.id === selected)) {
        musicModel.insertAdjacentHTML("afterbegin", `<option value="${esc(selected)}" selected>${esc(selected)}（伺服器上沒有這個 id）</option>`);
      }
      if (!rows.length) musicModel.innerHTML = `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
      musicModelsOut.textContent = st.ok ? `已讀到 ${rows.length} 個音樂生成模型` : (st.detail || "伺服器上沒有音樂生成模型");
      mout.textContent = (st.ok ? "✓ " : "✗ ") + st.detail + (st.cached?.length ? `・已快取 ${st.cached.length} 首` : "");
    } catch (e) {
      musicModel.innerHTML = `<option value="${esc(keep)}" selected>${esc(keep)}</option>`;
      musicModelsOut.textContent = `讀不到模型清單：${e.message}（保留原本的 id）`;
      mout.textContent = e.message;
    }
  };
  $("#m-provider", root).onchange = syncMusicPane;
  $("#m-models-refresh", root).onclick = loadMusicModels;
  syncMusicPane();
  loadMusicModels();
  api("/api/render/remotion").then((st) => {
    $("#r-out", root).textContent = (st.ok ? " ✓ 已安裝" : " ✗ " + st.detail);
  }).catch(() => {});
  $("#m-preview", root).onclick = async () => {
    mout.textContent = "生成試聽…（Lyria Clip 固定 30 秒；YuE2 第一次要載模型）";
    $("#m-player", root).innerHTML = "";
    await api("/api/settings", { method: "PUT", body: collect() });
    const r = await api("/api/music/preview", { method: "POST", body: { seconds: 20, style: $("#m-style", root).value } })
      .catch((e) => ({ error: e.message }));
    if (r.error) { mout.textContent = "✗ " + r.error; return; }
    mout.textContent = `✓ ${r.duration} 秒，平均 ${r.mean_db} dB`;
    $("#m-player", root).innerHTML = `<audio controls autoplay src="${r.url}" style="width:100%"></audio>`;
  };
}
