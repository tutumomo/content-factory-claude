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
| 選題雷達 | 讀你貼的連結／筆記，整理候選題目 | 挑一個「做這個」 |
| 蒐集資料 | 抓參考連結內文 | — |
| 方向簡報 | 3–4 個切入方向＋需求證清單 | **挑方向**、補觀點 |
| 寫講稿 | 依方向寫、拆成畫面（每畫面附 `stock_query` 實拍搜尋詞） | — |
| 多模型互審 | 事實查核／觀眾理解／節奏／AI 腔四個角色打分，未過門檻自動修（最多 3 輪） | 看講稿、可直接改字（可在設定關掉這個關卡） |
| 分鏡 | 產出每畫面的旁白、字卡與縮圖預覽，估每段秒數 | **看分鏡**，核准或退件重排（設定可關） |
| 配音／畫面／字幕 | audio.cpp Qwen3-TTS 配音、強制對齊做字幕、畫面三選一（Pexels／Pixabay 實拍、ComfyUI 生圖、Pillow 字卡）、每畫面墊音效、YuE2／Lyria 生成背景音樂、ffmpeg 合成＋音量正規化；也可改用 Remotion 渲染動畫版成片 | — |
| 自動檢查 | 實測長度、解析度、音量、長靜音、字幕對齊、語速、畫面來源、**畫面變化（抓簡報式輪播）**、音效、背景音樂、成片引擎 | — |
| 包裝 | 標題候選、縮圖候選、說明欄、IG 輪播圖卡、FB 貼文、shorts 發布包（TikTok／IG 說明文＋9:16 直式成片） | **挑標題、挑縮圖**、排程時間 |
| 成片審核 | — | 看成片 → **核准**或**退件**（一句理由） |
| 發布包 | 輸出到 `data/episodes/<id>/publish/`（shorts 另存 `publish/shorts/`） | 上傳到各平台 |
| 成效回收 | — | 填各平台數字 |

退件理由會被抽象成一條規則寫進「品味紀錄」，之後每一步都會遵守（SOP 原則 3）。

## 設定

- **LLM**：預設 `claude -p`（用你本機 Claude Code 的登入）。也可換成 OpenAI 相容端點（LM Studio :1234、Strata :8081），或「示範模式」只測流程。API key 只填環境變數名稱。
- **配音**：audio.cpp `qwen3-tts-1.7b-customvoice`，聲音 `vivian`；字幕對齊 `qwen3-forced-aligner-0.6b`。設定頁的 TTS 模型改成下拉選單，清單自動讀取 audio.cpp 上已登記的語音模型（`tts`／`clon`／`vdes`）。**參考音色**下拉也從 audio.cpp 的 `/v1/audio/voices` 抓：內建聲音（vivian 等，只適用 Qwen3 CustomVoice）與伺服器 `voice_dir` 音色庫（搭配 clon 模型；qwen3 Base 沒參考文字時自動改用 speaker-embedding 模式）。audio.cpp 同時只載入一個模型，被別的程式佔用時會自動等待重試（最多 15 分鐘）。送進 TTS 的文字會先轉成簡體（OpenCC tw2sp，例如 軟體→软件），因為 audio.cpp 讀繁體字常讀錯；字幕仍用原文。逐段情緒預設關閉，避免同一支片聽起來像換人。
- **畫面**：預設 Pillow 字卡；可切 ComfyUI 生圖當底、文字疊在上面。設定頁「圖像模型組合」下拉自動偵測已安裝組合：Krea-2（NSFW 首選、最快，但寫中文字弱）、MiniMax-H3-Image（中文字、NSFW 都可以，6 步 turbo）、MOSS-Image（中文字、NSFW 都可以）、Qwen Image 2.1（中文字最強、NSFW 亦可以）。
- **音效**：每個畫面可指定一個標籤，從 `data/sfx` 音效庫挑；缺的用 MOSS-SoundEffect 在設定頁批次生成，或按「從 Freesound 補音效」從 Freesound 抓 CC0／CC BY 音效（金鑰環境變數 `FREESOUND_API_KEY`，只填名稱）。本機模型生成失敗且 `stock_fallback` 開啟時也會自動改抓 Freesound；授權與作者寫在音檔旁的 `.json`，CC BY 的出處自動附在說明欄。
- **背景音樂**：預設 YuE2 3B（audio.cpp）生成純音樂；設定頁可改 **Google Lyria 3**（Gemini API，`lyria-3-clip-preview` 固定 30 秒片段 $0.04/首、`lyria-3-pro-preview` 完整歌曲約 3 分鐘 $0.08/首；皆無免費額度，金鑰用環境變數名，音訊含 SynthID 浮水印，專案要有額度），或 **Openverse 授權曲庫**（免註冊免金鑰，聚合 Jamendo／Freesound 的 CC 音樂；預設只抓 CC0，也可放寬到 CC BY 並自動標註；匿名額度 20 次/分、200 次/日）。長度跟著成片（片段會 loop），講話時自動壓低（sidechain），結果依引擎／風格／長度快取在 `data/music`。講稿的 `music` 欄位可逐集指定風格。
- **實拍素材**：設定頁「畫面來源」可選字卡、ComfyUI、實拍素材（Pexels／Pixabay）或混用。API key 只填環境變數名稱；搜尋依講稿的 `stock_query`，優先挑接近 1080×1920 的直式片段，下載快取在 `data/stock/`，出處與授權自動附在說明欄。實拍片段用 `scale+crop` 補滿畫框，不會變形。
- **AI 影片畫面**：「畫面來源」可選 **ComfyUI MiniMax-H3 生影片**。每個畫面用講稿的 `visual` 描述寫成 H3 提示詞（單一長鏡頭、禁止文字與對白），以 `MiniMaxH3ImageToVideo`（無參考圖＝文生影片）生成 2–15 秒、24 fps 的影片，並以 `VAEDecodeAudio` 同時生成環境音。預設配方是 **Pika H3 Flex**：`pika_h3_flex_fl2va_v1` LoRA ＋ `lcm` 取樣器 ＋ 官方六段 sigma 節點（`ManualSigmas`），6 步出片；設定頁「配方」可切回原生 25 步。**LoRA 走 MiniMax-H3-Turbo 的轉接器**：原生 `LoraLoaderModelOnly` 在這個 int8 基底每步約 13.5–17 秒（6 步 502 秒），Turbo 轉接器溫機時 6 步 130 秒、冷啟動 523 秒；同期原生 25 步冷啟動 622 秒；它的節點要求 LoRA 鍵名不含 `diffusion_model.` 前綴，所以用 `MiniMax H3/pika_h3_flex_fl2va_v1_noprefix.safetensors`（由原檔改名產生）。UNET、影片 VAE、音訊 VAE 另存本機 SSD 副本（檔名結尾 `_ssd`）：原檔在 gdrive，光是載入就要 150–380 秒。ffmpeg 循環補滿旁白長度，環境音依 `ambient_gain_db`（預設 -14 dB，≤ -60 靜音）墊在旁白下，再疊音效與音樂。frame 數依官方公式取 17k+5；模型、LoRA、sigma、畫素、單段秒數與逾時都在設定頁「MiniMax-H3 影片」區塊調整。失敗的段落自動退回字卡。
- **分鏡閘門**：預設開啟。講稿審完先進分鏡站產 `output/storyboard.json` 與縮圖，你按核准才開始配音與出片；退件會帶一句理由回講稿重排。
- **畫面變化檢查**：`slideshow_risk_max`（預設 0.7）比對相鄰畫面的灰階差異，靜止比例超過門檻就在「畫面變化」一項標紅，提示這種成片像簡報輪播。
- **雲端預算閘**：Lyria 這類付費 API 每筆在呼叫前先記帳（`data/cost/ledger.jsonl`）。低於單筆門檻直接放行，超過就讓集數停在「核准花費」等你按，累計超過月上限直接拒絕。核准與用量都是逐集記帳。
- **參考影片風格分析**：風格頁「從參考影片分析」貼 YouTube／Shorts／Reels 連結（或本機影片路徑），用 yt-dlp 抓下來後量剪點節奏、鏡頭長度分佈與畫面統計，再交給 LLM 寫成風格卡。只做大綱分析，不下載成片保存。
- **成片引擎**：`ffmpeg`（燒字幕）或 `remotion`（React 動畫：Ken Burns、標題與重點逐條進場、浮動字幕條）。Remotion 音軌仍由 ffmpeg 準備後再合成，失敗會自動退回 ffmpeg。Remotion 專案在 `remotion/`，第一次用要先 `npm install`。
- **官方 H3 提示詞技能**：MiniMax 官方的 9 個 H3 skill（`h3-prompt-writing` 與 8 個風格生成器）放在 `.claude/skills/`，Claude 在專案內可直接引用；`h3-prompt-writing/references/base-en.txt` 是 T2VA／I2VA／FL2VA／L2VA 的三段式欄位規範，`app/h3video.py` 的提示詞模板照這份寫。
- **GPU**：LM Studio、Strata、ComfyUI 共用同一塊記憶體，不要同時載入大模型。

## 沒做的事

- **沒有自動上傳到 YouTube／IG／FB**：需要各平台 OAuth 與 API 審核。目前輸出發布包（影片、縮圖、字幕、說明欄、輪播圖卡、shorts 直式成片與平台說明文、`metadata.json`），由你手動上傳或交給排程工具。TikTok／IG 直發列為第二階段。
- 選題雷達不會自己爬平台熱門榜，需要你貼線索。
- 畫面預設是設計過的文字卡片；勾 ComfyUI 才會生圖。

## 檔案

```
app/main.py      API 與路由
app/pipeline.py  SOP 各階段、背景 worker、你的決策
app/prompts.py   各任務提示詞（JSON 輸出）
app/llm.py       Claude CLI / OpenAI 相容 / 示範模式
app/media.py     TTS、對齊、字幕、ffmpeg、實測檢查
app/music.py     YuE2 背景音樂生成與混音（含 ducking）
app/sfx.py       音效庫、標籤、MOSS-SoundEffect 批量生成
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
