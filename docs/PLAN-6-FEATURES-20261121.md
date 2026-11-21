# 六項功能落地計劃書

日期：2026-11-21
依據：`nexu-io/openmotion`、`tutumomo/MoneyPrinterTurbo`、`tutumomo/OpenMontage` 三份評估，取六項適用本項目（content-factory-claude）的功能。

## 通則

- 每項都是獨立開關，預設不改變現有行為；失敗一律 fallback 現行路徑，不阻塞生產。
- OpenMontage 為 AGPLv3：只借設計概念，不複製程式碼。
- 每項完成需：實跑一集（短片為主）、寫入 `output/verify.json` 對應檢查、更新 README、zh-TW commit。

---

## 1. 股票 B-roll 素材源

來源：MoneyPrinterTurbo（Pexels／Pixabay）、OpenMontage（Archive.org／NASA／Wikimedia，列第二階段）。

目標：畫面加入真動態素材，降低「字卡＋生圖」的單調感。

設計：

- `visuals.source` 新增 `stock`、`mix`。`mix`＝有素材關鍵詞就用素材，沒有則字卡。
- 新模組 `app/stock.py`：
  - `search(keyword, aspect) -> list[candidate]`；候選含平台、作者、授權、原始 URL、下載 URL。
  - 下載到 `data/stock/<sha1>.<ext>` 快取；重抓前先查快取。
  - 每段素材寫入 `assets/sources.json`（平台／作者／license／URL），供說明欄 credits。
- 講稿 `scene` 新增可選 `stock_query`（英文關鍵詞）；`app/prompts.py` 要求 agent 產出；缺省時取 `visual` 描述前段翻譯。
- `app/pipeline.py` `st_assemble` 畫面來源擴充：`clip_bgs[i]`（動態）與 `bgs[i]`（靜態）並存。
- `app/media.py` `scene_clip` 支援影片底：trim 到旁白長度、不足時 freeze 末幀；不做複雜剪輯。
- 金鑰只存環境變數名稱（`PEXELS_API_KEY`、`PIXABAY_API_KEY`），設定頁填名稱不填值。
- 免費授權素材不強制標註；CC 來源（第二階段）自動寫入說明欄 credits。

任務：

1. `app/stock.py`＋快取＋`sources.json`（0.5 天）
2. 設定頁 visuals 增素材開關與金鑰環境變數名（0.2 天）
3. pipeline 接動態底、`scene_clip` 影片支援（0.5 天）
4. 說明欄 credits 合併（0.2 天）

驗收：短片一集 ≥60% 畫面為真素材；`verify.json`「畫面來源」顯示素材比例；ffprobe 長度／解析度通過；`sources.json` 每段有來源。

---

## 2. slideshow-risk 指標

來源：OpenMontage（投影片感評分）。

目標：成片自檢多一項「畫面變化率」，攔 PPT 感。

設計：

- `app/media.py` 新增 `frame_diffs(video, step=2.0)`：每 step 秒抽一幀，灰階差分，回傳平均差異與「幾乎無變化」幀對比例。
- `verify_video` 新增檢查 `"畫面變化"`：變化比例低於門檻 → `ok:false`，但不退件，只警告並寫 log。
- 閾值設定 `pipeline.slideshow_risk_max`（預設 0.7）。
- 前端檢查清單顯示該項。

任務：

1. `frame_diffs()`（0.3 天）
2. `verify_video` 接入＋閾值設定（0.2 天）
3. 前端顯示（0.1 天）

驗收：純字卡集數觸發警告、素材或生圖集數不觸發；驗證階段增加 <10 秒。

---

## 3. storyboard 核准頁

來源：OpenMontage（Backlot 分鏡閘門）。

目標：組片（配音／生圖／合成）前先看分鏡，一鍵放行或退件，避免整支做完才發現方向錯。

設計：

- 新 stage `storyboard`，位置在 `critique` 與 `assemble` 之間；`pipeline.review_storyboard` 預設 true。
- `st_storyboard` 產出 `output/storyboard.json`：每 scene 的縮圖（Pillow 字卡或低解析生圖）、旁白、預估秒數（字數÷語速）、`sfx` 標籤、`stock_query`、`visual` 描述。
- API：`GET /api/episodes/{eid}/storyboard`、`POST /api/episodes/{eid}/storyboard/decision {approve, notes}`。
- worker 沿用 `wait()`：狀態「等你：看分鏡」。退件理由走現有 `reject` 寫回 `PREFERENCES.md`。
- 前端新增分鏡頁（卡片格線：縮圖＋旁白＋秒數；按鈕：核可／退回）。

任務：

1. 後端 stage＋API（0.5 天）
2. 前端分鏡頁（0.5 天）
3. 設定開關（0.1 天）

驗收：新集數在 assemble 前停下等待；核可後續跑；退件寫回品味紀錄。

---

## 4. 多平台發布包（TikTok／Instagram）

來源：MoneyPrinterTurbo（多平台發布）。

目標：短片除 YouTube 外，產出 TikTok／IG Reels 可直接上傳的包；第二階段才做 API 自動發文。

第一階段（發布包）：

- 每集 `output/publish/` 增 `shorts/` 專版（9:16 已符合則直接複用）、`caption_tiktok.txt`、`caption_ig.txt`（平台字數限制、hashtags 分開）。
- 包裝頁顯示各平台文案與檔案。

第二階段（API 自動發文）：

- `app/tiktok.py`（TikTok Content Posting API）、`app/instagram.py`（Meta Graph API Reels），沿用 `app/youtube.py` 的 OAuth 模式。
- Token 存 `data/secrets/`（gitignore、mode 600）。
- 一律私人／草稿上傳；按核准才發（沿用 `approve` 閘）。

任務：

1. shorts 專版＋平台文案（0.5 天）
2. 發布包頁擴充（0.3 天）
3. 〔第二階段〕TikTok API（1–2 天＋審核等待）
4. 〔第二階段〕IG Graph API（1–2 天＋審核等待）

驗收：第一階段每集產出兩平台 mp4＋caption；第二階段一鍵私人上傳成功。

---

## 5. 參考影片風格分析

來源：OpenMotion（參考片拆解、Motion.md）、OpenMontage（參考片→概念）。

目標：貼一支參考片，抽出節奏、剪接密度、字幕樣式、配色，變成可套用風格與分鏡建議。

設計：

- `POST /api/styles/from-video {url|path}`：
  - 下載（yt-dlp）或本機檔；
  - `ffmpeg scdet` 找切點 → 平均鏡頭長、cut 密度分布；
  - 抽幀（每鏡一張）＋音訊能量；
  - LLM 看抽幀＋統計，輸出風格 JSON：節奏（平均鏡頭秒數／快慢分布）、字幕位置與樣式、主色、轉場類型、建議 sfx 密度。
- 產出 `shotlist.md`（OpenMotion Motion.md 概念）：鏡頭序、時長、內容摘要，供講稿分鏡參考。
- 結果存為新風格，**不自動套用**；風格頁可預覽與「套用」。

任務：

1. `app/video_analysis.py`（下載、scdet、抽幀、音訊能量）（0.5 天）
2. 提示詞與輸出 schema（0.3 天）
3. 風格頁匯入＋預覽（0.4 天）

驗收：一支 YouTube 參考片產生含平均鏡頭長、cut 密度、主色、字幕位置建議；可套用為新風格且不覆蓋既有風格。

---

## 6. 雲端花費預算閘

來源：OpenMontage（budget caps、核准門檻）。

目標：Lyria 與未來雲端生圖／T2V 有月上限、單筆核准、完整帳本。

設計：

- 設定 `cost`：`monthly_cap_usd`、`per_call_approval_usd`、各 provider 單價（`lyria-3-clip-preview` 0.04／首、`lyria-3-pro-preview` 0.08／首）。
- `app/cost.py`：`check(provider, usd) -> allow | need_approval | deny`；`record(provider, units, usd, episode)` 寫 `data/cost/ledger.jsonl`；`month_sum()`。
- `music.lyria_generate` 呼叫前檢查、成功後記帳；未來雲端圖片／T2V 同樣接入。
- 需核准時集數暫停於「等你：核准花費」；`POST /api/episodes/{eid}/cost/approve` 放行。
- UI：設定頁預算欄位；復盤頁顯示本月累計。

任務：

1. `cost.py`＋ledger（0.3 天）
2. Lyria 接入（0.1 天）
3. 核准流程（0.3 天）
4. UI（0.3 天）

驗收：Lyria 生成寫入帳本；設 $0.10 上限後第二次呼叫被擋並要求核准；核准後放行且帳本續記。

---

## 排程與依賴

建議順序（風險低、見效快優先）：

1. slideshow-risk（第 2 項）——最便宜。
2. storyboard 核准頁（第 3 項）——流程升級。
3. 股票 B-roll（第 1 項）——工作量最大，可與 2／3 並行。
4. 預算閘（第 6 項）。
5. 多平台發布包第一階段（第 4 項）。
6. 參考影片風格分析（第 5 項）；TikTok／IG API 第二階段另議。

總估：約 6–7 個工作天，不含 TikTok／IG API 審核與素材金鑰申請等待。

里程碑：

- M1（第 1 天）：slideshow-risk＋storyboard。
- M2（第 2–3 天）：stock B-roll。
- M3（第 4 天）：預算閘。
- M4（第 5 天）：多平台發布包第一階段。
- M5（第 6–7 天）：參考影片風格分析。

## 風險

- 股票素材 API 速率限制與授權變動：一律快取＋記錄來源，缺就 fallback 字卡。
- 動態素材與字幕／音效同步：只做 trim／freeze，不做複雜剪輯。
- OpenMontage AGPLv3：不抄程式碼。
- TikTok／IG API 審核不可控：先交付發布包。
- 單價寫錯：單價集中一處、ledger 記錄公式與 units。

## 驗收通則

每項完成條件：自測通過、實跑一集、`verify.json` 有對應檢查、README 更新、commit 並推送 `origin main`。
