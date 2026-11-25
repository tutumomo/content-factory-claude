# 內容工廠（Claude 版）

依 `~/.claude/skills/content-factory` 的 SOP 做成的網頁程式：agent 做苦工，你只在決策點出手：**選題、挑方向、挑標題與縮圖、退件、按核准**。

> 這個資料夾是 Claude 做的版本。Gemini（Antigravity）做的另一版在 `~/ai-content-factory`，兩者完全分開、互不共用檔案。

## 安裝

需要 Python 3.12+、ffmpeg（含 libass）、Noto Sans CJK 字型、`claude` CLI，以及 audio.cpp 伺服器。

```bash
git clone https://github.com/tutumomo/content-factory-claude.git ~/content-factory-claude
cd ~/content-factory-claude
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

## 啟動

```bash
~/content-factory-claude/run.sh
```

開 http://127.0.0.1:8770 。配音需要 audio.cpp 伺服器（:8090）在跑；沒在跑就先執行 `audiocpp-webui`。

## 流程（對應 SOP）

| 階段 | agent 做 | 你做 |
|---|---|---|
| 選題雷達 | 讀你貼的連結／筆記，抽候選 → 預篩 → 0–100 注意力評分 → 同事件聚類 → 依熱度排序（每則附一句依據） | 挑一個「做這個」 |
| 蒐集資料 | 抓參考連結內文，並核對材料是否支撐題目 | 來源不足時**補連結／補一手資訊**，或明確選擇繼續 |
| 方向簡報 | 3–4 個切入方向＋需求證清單 | **挑方向**、補觀點 |
| 寫講稿 | 依方向寫、拆成畫面（每畫面附 `stock_query` 實拍搜尋詞） | — |
| 多模型互審 | 事實查核／觀眾理解／節奏／AI 腔四個角色打分，未過門檻自動修（最多 3 輪） | 看講稿、可直接改字（可在設定關掉這個關卡） |
| 分鏡 | 產出每畫面的旁白、字卡與縮圖預覽，估每段秒數 | **看分鏡**，核准或退件重排（設定可關） |
| 配音／畫面／字幕 | audio.cpp Qwen3-TTS 配音、強制對齊做字幕、畫面三選一（Pexels／Pixabay 實拍、ComfyUI 生圖、Pillow 字卡）、每畫面墊音效、YuE2／Lyria 生成背景音樂、ffmpeg 合成＋音量正規化；也可改用 Remotion 渲染動畫版成片 | — |
| 自動檢查 | 實測長度、解析度、音量、長靜音、字幕對齊、語速、畫面來源、**畫面變化（抓簡報式輪播）**、音效、背景音樂、成片引擎 | — |
| 包裝 | 標題候選、縮圖候選、說明欄、IG 輪播圖卡、FB 貼文、shorts 發布包（TikTok／IG 說明文＋9:16 直式成片） | **挑標題、挑縮圖**、排程時間 |
| 成片審核 | — | 看成片 → **核准**或**退件**（一句理由） |
| 發布包 | 輸出到 `data/episodes/<id>/publish/`（shorts 另存 `publish/shorts/`） | 上傳到各平台 |
| 成效回收 | 從 YouTube Data API 自動抓觀看、讚、留言（每集每天一筆） | 其他平台數字手動填；按「從 YouTube 更新」 |

退件理由會被抽象成一條規則寫進「品味紀錄」，之後每一步都會遵守（SOP 原則 3）。

## 素材來源自動降級

本地生成服務沒開時不會卡住整集，會照順序往下一順位走（先素材庫、最後才是線上生成）。設定頁「來源鏈」可改順序，留空就依原本的單一來源設定自動排：

| 類別 | 預設順序 |
|---|---|
| 畫面 | h3video → comfy → stock → slides（`mix` 模式＝stock 先、剩下的才生圖） |
| 配音 | audiocpp → edge → gemini |
| 音樂 | audiocpp → openverse → lyria |
| 音效 | library → freesound |

- **開工前探測**：組裝開始時一次探測鏈上所有來源（每個 2–4 秒，結果快取約 30 秒），把「本集計畫」寫進 log 與 `output/verify.json`。
- **同集熔斷**：某來源連續失敗 2 次，這一集剩下的段落就不再試它。ComfyUI 逾時會呼叫 `/interrupt` 並從 `/queue` 刪掉那個 prompt，不讓 GPU 被佔著。
- **付費來源**（Lyria、Gemini TTS）預設不進鏈；勾「允許用付費來源」才會排在最後，而且一定先過月上限與單筆核准門檻，需要核准時直接退回免費選項，不會停下來等。
- **配音備援**：audio.cpp 沒開或 503 等到逾時（`tts.busy_wait_s`，預設 120 秒）就換 Edge TTS（免費、免金鑰，`pip install edge-tts`）；Edge 也失敗才輪到 Gemini TTS。Edge／Gemini 沒有強制對齊資料，字幕改用字數估時；音色與 Qwen3 不同，`verify.json` 的「配音來源」與集數頁都會標出來。
- **音效補檔**：組裝時音效庫缺標籤，有 `FREESOUND_API_KEY` 就當場從 Freesound 補。
- 每次降級都寫進 log 與 `verify.json`（`sources.badges`），集數頁顯示「畫面：ComfyUI 未開，改用實拍素材 8/10」這種標記。

## 設定

- **LLM**：預設 `claude -p`（用你本機 Claude Code 的登入）。也可換成 OpenAI 相容端點（LM Studio :1234、Strata :8081），或「示範模式」只測流程。API key 只填環境變數名稱。
- **配音**：audio.cpp `qwen3-tts-1.7b-customvoice`，聲音 `vivian`；字幕對齊 `qwen3-forced-aligner-0.6b`。設定頁的 TTS 模型改成下拉選單，清單自動讀取 audio.cpp 上已登記的語音模型（`tts`／`clon`／`vdes`）。**參考音色**下拉也從 audio.cpp 的 `/v1/audio/voices` 抓：內建聲音（vivian 等，只適用 Qwen3 CustomVoice）與伺服器 `voice_dir` 音色庫（搭配 clon 模型；qwen3 Base 沒參考文字時自動改用 speaker-embedding 模式）。audio.cpp 同時只載入一個模型，被別的程式佔用時會自動等待重試（最多 15 分鐘）。送進 TTS 的文字會先轉成簡體（OpenCC tw2sp，例如 軟體→软件），因為 audio.cpp 讀繁體字常讀錯；字幕仍用原文。逐段情緒預設關閉，避免同一支片聽起來像換人。
- **畫面**：預設 Pillow 字卡；可切 ComfyUI 生圖當底、文字疊在上面。設定頁「圖像模型組合」下拉自動偵測已安裝組合：Krea-2（NSFW 首選、最快，但寫中文字弱）、MiniMax-H3-Image（中文字、NSFW 都可以，6 步 turbo）、MOSS-Image（中文字、NSFW 都可以）、Qwen Image 2.1（中文字最強、NSFW 亦可以）。
- **音效**：每個畫面可指定一個標籤，從 `data/sfx` 音效庫挑；缺的用 MOSS-SoundEffect 在設定頁批次生成，或按「從 Freesound 補音效」從 Freesound 抓 CC0／CC BY 音效（金鑰環境變數 `FREESOUND_API_KEY`，只填名稱）。本機模型生成失敗且 `stock_fallback` 開啟時也會自動改抓 Freesound；授權與作者寫在音檔旁的 `.json`，CC BY 的出處自動附在說明欄。
- **背景音樂**：預設 YuE2 3B（audio.cpp）生成純音樂；設定頁可改 **Google Lyria 3**（Gemini API，`lyria-3-clip-preview` 固定 30 秒片段 $0.04/首、`lyria-3-pro-preview` 完整歌曲約 3 分鐘 $0.08/首；皆無免費額度，金鑰用環境變數名，音訊含 SynthID 浮水印，專案要有額度），或 **Openverse 授權曲庫**（免註冊免金鑰，聚合 Jamendo／Freesound 的 CC 音樂；預設只抓 CC0，也可放寬到 CC BY 並自動標註；匿名額度 20 次/分、200 次/日）。長度跟著成片（片段會 loop），講話時自動壓低（sidechain），結果依引擎／風格／長度快取在 `data/music`。講稿的 `music` 欄位可逐集指定風格。
- **實拍素材**：設定頁「畫面來源」可選字卡、ComfyUI、實拍素材（Pexels／Pixabay）或混用。API key 只填環境變數名稱；搜尋依講稿的 `stock_query`，優先挑接近 1080×1920 的直式片段，下載快取在 `data/stock/`，出處與授權自動附在說明欄。實拍片段用 `scale+crop` 補滿畫框，不會變形。
- **實拍素材不重複**：同一集不會重用同一支片段；30 天內別集用過的片段排到最後（`visuals.stock_recent_days`，紀錄在 `data/stock_usage.json`）。每個關鍵詞抓 15 支候選，同分時依集數打散，相似關鍵詞不會都落在同一支。較長的畫面會切成多個鏡頭（每鏡約 `visuals.stock_shot_seconds` 秒，預設 5，最多 `visuals.stock_max_shots` 鏡）；風格卡若來自參考影片，改用它量到的平均鏡頭長度。每個鏡頭從片段中段隨機起點開始。
- **AI 影片畫面**：「畫面來源」可選 **ComfyUI MiniMax-H3 生影片**。每個畫面用講稿的 `visual` 描述寫成 H3 提示詞（單一長鏡頭、禁止文字與對白），以 `MiniMaxH3ImageToVideo`（無參考圖＝文生影片）生成 2–15 秒、24 fps 的影片，並以 `VAEDecodeAudio` 同時生成環境音。預設配方是 **Pika H3 Flex**：`pika_h3_flex_fl2va_v1` LoRA ＋ `lcm` 取樣器 ＋ 官方六段 sigma 節點（`ManualSigmas`），6 步出片；設定頁「配方」可切回原生 25 步。**LoRA 走 MiniMax-H3-Turbo 的轉接器**：原生 `LoraLoaderModelOnly` 在這個 int8 基底每步約 13.5–17 秒（6 步 502 秒），Turbo 轉接器溫機時 6 步 130 秒、冷啟動 523 秒；同期原生 25 步冷啟動 622 秒；它的節點要求 LoRA 鍵名不含 `diffusion_model.` 前綴，所以用 `MiniMax H3/pika_h3_flex_fl2va_v1_noprefix.safetensors`（由原檔改名產生）。UNET、影片 VAE、音訊 VAE 另存本機 SSD 副本（檔名結尾 `_ssd`）：原檔在 gdrive，光是載入就要 150–380 秒。ffmpeg 循環補滿旁白長度，環境音依 `ambient_gain_db`（預設 -14 dB，≤ -60 靜音）墊在旁白下，再疊音效與音樂。frame 數依官方公式取 17k+5；模型、LoRA、sigma、畫素、單段秒數與逾時都在設定頁「MiniMax-H3 影片」區塊調整。失敗的段落自動退回字卡。
- **選題雷達**：把貼進來的連結／文字拆成候選，先做寬召回預篩（`PASS` 進評分、`BLOCK` 丟掉、`UNKNOWN` 留在清單標「待補」），再依事件份量、資訊增量、證據強度、共振面、可用性五軸算 0–100 注意力分數，最後把同一件事的多篇報導併成一組，依分數排序。每則都留一句給你看的評分依據；分數與聚類可在設定頁個別關掉，回到舊的一次掃描。抓網頁會先試一般 UA、失敗再換瀏覽器 UA 重試一次；仍抓不到（反爬挑戰、JS 空殼、正文太少）時，靈感頁會顯示失敗原因與下一步，不會只停在「掃描中」。
- **訂閱來源定時掃描**：在靈感頁填網站首頁或 RSS 網址（例如 `https://aihot.news/`），選每天／週一到週五／每週幾點，或每隔幾小時。時間以伺服器時區為準。每次會先找網站的 RSS／Atom，找不到才抓首頁上同站的文章連結；只把沒看過的新文章（每次最多 N 則，預設 10）交給雷達評分，做成「訂閱」卡片。模型呼叫失敗時這批文章不算看過，下次會重試。伺服器停機期間錯過的排程，重啟後只補跑一次。設定存在 `data/watch.json`。
- **來源求證**：抓完連結後比對題目與筆記，列出材料沒有支持的主張（`gaps`）。材料不足時，**智能體先自己上網搜尋一輪**（`source_auto_search`，預設開）：有裝 Claude CLI 就用它的 WebSearch 依題目、筆記與缺口挑一手網頁（約 30 秒，不論主模型是哪家），沒裝或失敗時退到免金鑰的 Bing、再退維基百科；最多留 `source_search_max`（預設 3）個可讀網頁，標成「智能體自動搜尋」寫進 `sources.md`，試過的網址會記住，重跑時不重抓死連結。搜尋只送題目、筆記與缺口，不送其他資料。自動搜尋後仍沒有可讀的一手來源、筆記也不足時，預設停在「補來源」閘門（閘門會顯示已搜尋過什麼），不會再回報假的 `ok`；你可以補連結重抓、補一手資訊，或按「來源不足也繼續」讓講稿標註需求證。`source_gate` 可關掉，只標示不擋。
- **標題與說明欄**：套自足標題規則（不點開也知道主體與動作、保留原文類型、不把舊發布寫成今天推出）與答案前置摘要規則（第一句就是可引用的結論），並保留模型／產品／版本號原文。標題候選會附上長度、只有版本號或只有 teaser 的檢查結果。
- **分鏡閘門**：預設開啟。講稿審完先進分鏡站產 `output/storyboard.json` 與縮圖，你按核准才開始配音與出片；退件會帶一句理由回講稿重排。
- **畫面變化檢查**：`slideshow_risk_max`（預設 0.7）比對相鄰畫面的灰階差異，靜止比例超過門檻就在「畫面變化」一項標紅，提示這種成片像簡報輪播。
- **雲端預算閘**：Lyria 這類付費 API 每筆在呼叫前先記帳（`data/cost/ledger.jsonl`）。低於單筆門檻直接放行，超過就讓集數停在「核准花費」等你按，累計超過月上限直接拒絕。核准與用量都是逐集記帳。
- **內建風格卡**：37 張，分 12 類（科技數碼、新聞快評、知識科普、觀點深度、生活工具、敘事紀實、動畫手繪、極簡圖表、商業廣告、復古懷舊、電影質感、社群短影音）。最早的 5 張在 `app/store.py`（id 與內容不改），其餘在 `app/style_presets.py`，id 規則是 `preset-<類別>-<名稱>`，上線後不改名。新卡多一欄「畫面方向」（`visual`：鏡頭、光線、色調、材質、模板偏好），會跟著風格卡注入提示詞，讓講稿寫每個畫面的 `visual` 與挑 `bigtype|papercut|corkboard|clean` 模板時有依據。舊的 `styles.json` 讀取時會自動補上缺少的內建卡，已改過的內容與使用中的卡不變；集數指定的風格卡不存在時，退回使用中的卡。
- **參考影片風格分析**：風格頁「從參考影片分析」貼 YouTube／Shorts／Reels 連結（或本機影片路徑），用 yt-dlp 抓下來後量剪點節奏、鏡頭長度分佈與畫面統計，再交給 LLM 寫成風格卡。只做大綱分析，不下載成片保存。分鏡表列出每個鏡頭的實際秒數。
- **YouTube 連結沒有字幕時**（影片本身沒字幕，或 YouTube 回 HTTP 429 擋字幕）：只下載音軌，轉成 16 kHz WAV 後交給本機 audio.cpp `qwen3-asr-1-7b-q8-0` 轉文字，結果快取在 `data/yt_asr/<影片ID>.txt`。設定在 `youtube.asr_fallback`／`asr_model`／`asr_max_minutes`（預設 30 分鐘以上不轉）／`asr_busy_wait_s`。audio.cpp 同時只載入一個模型，會跟配音排隊。
- **成片引擎**：`ffmpeg`（燒字幕）或 `remotion`（React 動畫：Ken Burns、標題與重點逐條進場、浮動字幕條）。Remotion 的實拍／H3 畫面直接播放影片（`render.remotion_video`，預設開），不再只取一張靜態畫格。Remotion 音軌仍由 ffmpeg 準備後再合成，失敗會自動退回 ffmpeg。Remotion 專案在 `remotion/`，第一次用要先 `npm install`。
- **成效自動回收**：集數頁貼一次 YouTube 網址（手動上傳的也適用），之後按「從 YouTube 同步」就會把當天的觀看、讚、留言寫進成效紀錄；同一天重抓會覆蓋當天那一筆，不會重複。復盤頁的「從 YouTube 更新」會一次更新所有已連結影片的集數。YouTube Data API 不提供平均觀看時間與新追蹤，這兩欄仍手動填。
- **官方 H3 提示詞技能**：MiniMax 官方的 9 個 H3 skill（`h3-prompt-writing` 與 8 個風格生成器）放在 `.claude/skills/`，Claude 在專案內可直接引用；`h3-prompt-writing/references/base-en.txt` 是 T2VA／I2VA／FL2VA／L2VA 的三段式欄位規範，`app/h3video.py` 的提示詞模板照這份寫。
- **GPU**：LM Studio、Strata、ComfyUI 共用同一塊記憶體，不要同時載入大模型。

## 內容模式與分級

每一集帶兩個欄位：**內容模式**（`mode`）與**分級**（`rating`）。未指定時是 `news` ＋ `general`，行為與以前完全一樣。

| mode | rating | 意思 |
|---|---|---|
| `news` | `general` | 新聞：查證事實、有來源、有防幻覺規則。預設 |
| `news` | `suggestive` | 新聞但帶暗示性主題 |
| `narrative` | `general`／`suggestive`／`adult` | 虛構敘事：不做來源求證，改用敘事規則 |
| `fiction` | `general`／`suggestive`／`adult` | 自由創作：完全從零編，可以自由發明世界觀 |

建集當下就會擋下不合法的組合：`mode=news` ＋ `rating=adult` 會回 400 並說明「成人向必須是虛構敘事」。

**創作模式不查證。** `narrative` 與 `fiction` 兩者都直接跳過來源求證與來源閘門：不會停下來跟你要連結，也不會因為「資料不足」擋住。有給連結就當參考資料收進 `sources.md`，沒給就從零開始。`news` 的行為完全沒變。

### 成品形態（form）

同一個題材可以做成完全不同的東西，`form` 決定跑哪幾站、交付什麼：

| form | 成品 | 配音 | 畫面 |
|---|---|---|---|
| `video` | 影片（預設） | ✓ | ✓ |
| `novel` | 純文字小說（`novel.txt`＋`manuscript.md`） | ✗ | ✗ |
| `audiobook` | MP3 小說（`audiobook.mp3`＋`chapters.json`＋文字稿） | ✓ | ✗ |
| `gallery` | 圖片集（`image_*.jpg`＋`captions.json`＋`gallery.md`） | ✗ | ✓ |
| `talk` | 話題評論（口播影片＋`script.txt`） | ✓ | ✗ |

非影片形態不會跑分鏡，也不會渲染影片。審稿角色也跟著換：文字形態看「文字質地／情節連貫／閱讀推力」，MP3 小說再加一個「聽感」。

**頻道上限**：風格頁「頻道基本定位」有「分級上限」，預設「一般」。要建受限分級的集數，先把上限調高；超出上限的建集請求會被拒絕並說明原因。

**分級會擋住什麼**

- **畫面來源**：`suggestive`／`adult` 的集數，畫面來源鏈會排除免費實拍素材（Pexels／Pixabay 的授權不涵蓋這個用途）。排除掉哪一個會寫進集數的來源計畫（`verify.json` 的 `sources.plan`）與 `分級` 檢查；若受限來源真的被用到，那項檢查會是失敗。
- **自動上傳**：`suggestive`／`adult` 的集數**不支援自動上傳** YouTube。YouTube Data API 沒有可寫的 18+ 欄位（`contentDetails.contentRating.ytRating` 寫入會被忽略或拒絕），而且平台規範禁止這類內容——設年齡限制不等於允許上架。擋截在 API 入口與上傳工作階段兩處，訊息說得出原因。
- **發布包**：受限分級的發布包只有影片、字幕、縮圖、`metadata.json`（含 `contentRating` 與 AI 生成揭露）與 `CHECKLIST.md`（合規檢查清單）。沒有 IG 輪播圖卡、沒有 Facebook 貼文、沒有 shorts 平台文案。
- **核准**：受限分級的集數核准時要送出與集數分級相符的分級確認（`confirm_rating`），確認會記在集數的 `approvals`。

**各模式的審稿角色不同**：新聞是「事實查核／觀眾理解／節奏／AI 腔獵人」；敘事是「界線與分級／情節連貫／情慾節奏／AI 腔獵人」。界線與分級給 0 分會直接中止這集（進錯誤狀態，不進閘門）。各模式的角色組可從 `GET /api/meta` 的 `critics_by_mode` 取得。

**Provider 分流與拒寫**：預設用 `claude -p`。成人向題材常被雲端模型拒寫，這時回報的是「模型拒絕寫這個題材」而不是「輸出不是合法 JSON」。設定頁的 `llm.task_routes` 可以把某個任務改派給別的 provider（例如本機 OpenAI 相容端點），例如 `{"script": "openai", "critique_boundary": "openai"}`。

**成人向風格卡。** 內建 10 張 NSFW 風格卡（情慾敘事／感官描寫／成人話題／角色關係），收在 `app/style_presets_nsfw.py`。每張卡帶 `rating_min`（最低適用分級）與 `forms`（適用形態），而且**受頻道上限管制**：頻道上限是「一般」時，這些卡完全不會出現在清單裡，不只是藏起來。每張卡的 `avoid` 都寫死三條硬線：未成年角色、未經同意的真人、把強迫寫成浪漫。

**角色卡（`data/characters.json`）**：一張卡一個角色，帶固定外觀描述與穩定的種子偏移，讓同一個角色在每個畫面看起來是同一人。兩條硬規則寫在 `app/characters.py`：

- 非 `general` 分級用到的角色，`adult_attested` 必須明確為 `true`；缺欄位或為 `false` 一律拒絕（不會預設為真）。
- 用了真人照片（`ref_image`）就必須附同意文件（`model_release`）；沒有同意文件就拒絕。

## 測試

一套測試、一個入口。`tests/conftest.py` 會把 `CF_DATA` 指到暫存目錄，並替換掉所有會碰網路或 GPU 的服務（TTS／對齊、素材庫、ComfyUI、H3、音樂、Remotion、LLM），所以不需要開任何本機服務，也不會寫到正式的 `data/`。

```bash
.venv/bin/python -m pytest tests -q        # 全部測試（建議）
.venv/bin/python -m unittest discover -s tests -t . -v   # 只跑 unittest 風格的模組
```

`pytest` 是四套測試的聯集：`tests/test_editorial.py`（雷達預篩／評分／聚類／求證）、`tests/test_sources.py`（來源鏈與降級）、`tests/test_smoke.py`（mock LLM、假服務、真 ffmpeg 的端到端矩陣與閘門回歸）、`tests/test_ratings.py`（mode／rating、來源鏈分級過濾、拒寫辨識、角色卡、負面提示、發布包分岔與稽核軌跡）。`unittest discover` 不會收集 `test_smoke.py` 這種 pytest 函式式測試，只用來跑前兩套；新測試請一律用 pytest 撰寫，並放進 `pytest tests` 會收集到的檔案。

## 沒做的事

- **沒有自動上傳到 YouTube／IG／FB**：需要各平台 OAuth 與 API 審核。目前輸出發布包（影片、縮圖、字幕、說明欄、輪播圖卡、shorts 直式成片與平台說明文、`metadata.json`），由你手動上傳或交給排程工具。TikTok／IG 直發列為第二階段。
- 選題雷達不會自己爬平台熱門榜；手動掃描需要你貼線索，訂閱來源只掃你加入的網站。它會替你預篩、評分與聚類，但不會自己去找新網站。
- 畫面預設是設計過的文字卡片；勾 ComfyUI 才會生圖。

## 檔案

```
app/main.py      API 與路由
app/pipeline.py  SOP 各階段、背景 worker、你的決策
app/prompts.py   各任務提示詞（JSON 輸出；含改寫自 AIHOT 的編輯規則）
app/editorial.py 選題預篩、注意力評分、同事件聚類、來源求證與標題檢查
app/llm.py       Claude CLI / OpenAI 相容 / 示範模式
app/media.py     TTS、對齊、字幕、ffmpeg、實測檢查
app/music.py     YuE2 背景音樂生成與混音（含 ducking）
app/sfx.py       音效庫、標籤、MOSS-SoundEffect 批量生成
app/sources.py   來源鏈、開工探測、同集熔斷、配音降級
app/comfy.py     ComfyUI（Krea-2／H3-Image／MOSS／Qwen 2.1）生圖
app/h3video.py   ComfyUI MiniMax-H3 文生影片（畫面來源＝h3video）
app/stock.py     實拍素材（Pexels／Pixabay）搜尋、下載、快取、出處
app/cost.py      雲端 API 記帳與預算閘（單筆門檻＋月上限）
app/video_analysis.py  參考影片下載、剪點節奏與畫面統計
app/video.py     Remotion 渲染：組 props、呼叫 remotion CLI
app/render.py    畫面、縮圖、輪播圖卡
remotion/        Remotion 專案（Episode 組合：動畫排版與字幕）
static/          網頁介面
data/            頻道定位、設定、品味紀錄、雷達、每一集的檔案
```

## 致謝

- 選題預篩、事件注意力評分、同事件聚類、防幻覺／自足標題／答案前置摘要等提示詞方法論，改寫自 [KKKKhazix/AIHOT](https://github.com/KKKKhazix/AIHOT)（MIT 授權）。本專案只移植 `industry/prompts/` 的文字方法論並改寫成繁體中文、接上自己的設定與流程，沒有使用它的網站、資料庫、爬蟲或信源名單。授權全文與逐項改動見 [`THIRD_PARTY.md`](THIRD_PARTY.md)。
