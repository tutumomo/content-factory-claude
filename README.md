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
| 寫講稿 | 依方向寫、拆成畫面 | — |
| 多模型互審 | 事實查核／觀眾理解／節奏／AI 腔四個角色打分，未過門檻自動修（最多 3 輪） | 看講稿、可直接改字（可在設定關掉這個關卡） |
| 配音／畫面／字幕 | audio.cpp Qwen3-TTS 配音、強制對齊做字幕、Pillow 字卡或 ComfyUI 生圖當底、每畫面墊音效、YuE2 生成背景音樂、ffmpeg 合成＋音量正規化；也可改用 Remotion 渲染動畫版成片 | — |
| 自動檢查 | 實測長度、解析度、音量、長靜音、字幕對齊、語速、畫面來源、音效、背景音樂、成片引擎 | — |
| 包裝 | 標題候選、縮圖候選、說明欄、IG 輪播圖卡、FB 貼文 | **挑標題、挑縮圖**、排程時間 |
| 成片審核 | — | 看成片 → **核准**或**退件**（一句理由） |
| 發布包 | 輸出到 `data/episodes/<id>/publish/` | 上傳到各平台 |
| 成效回收 | — | 填各平台數字 |

退件理由會被抽象成一條規則寫進「品味紀錄」，之後每一步都會遵守（SOP 原則 3）。

## 設定

- **LLM**：預設 `claude -p`（用你本機 Claude Code 的登入）。也可換成 OpenAI 相容端點（LM Studio :1234、Strata :8081），或「示範模式」只測流程。API key 只填環境變數名稱。
- **配音**：audio.cpp `qwen3-tts-1.7b-customvoice`，聲音 `vivian`；字幕對齊 `qwen3-forced-aligner-0.6b`。audio.cpp 同時只載入一個模型，被別的程式佔用時會自動等待重試（最多 15 分鐘）。
- **畫面**：預設 Pillow 字卡；可切 ComfyUI（Krea-2）生底圖、文字疊在上面。
- **音效**：每個畫面可指定一個標籤，從 `data/sfx` 音效庫挑；缺的用 MOSS-SoundEffect 在設定頁批次生成。
- **背景音樂**：YuE2 3B（audio.cpp）生成純音樂，長度跟著成片，講話時自動壓低（sidechain），結果依風格／長度／seed 快取在 `data/music`。講稿的 `music` 欄位可逐集指定風格。
- **成片引擎**：`ffmpeg`（燒字幕）或 `remotion`（React 動畫：Ken Burns、標題與重點逐條進場、浮動字幕條）。Remotion 音軌仍由 ffmpeg 準備後再合成，失敗會自動退回 ffmpeg。Remotion 專案在 `remotion/`，第一次用要先 `npm install`。
- **GPU**：LM Studio、Strata、ComfyUI 共用同一塊記憶體，不要同時載入大模型。

## 沒做的事

- **沒有自動上傳到 YouTube／IG／FB**：需要各平台 OAuth 與 API 審核。目前輸出發布包（影片、縮圖、字幕、說明欄、輪播圖卡、`metadata.json`），由你手動上傳或交給排程工具。
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
app/comfy.py     ComfyUI（Krea-2）生圖
app/video.py     Remotion 渲染：組 props、呼叫 remotion CLI
app/render.py    畫面、縮圖、輪播圖卡
remotion/        Remotion 專案（Episode 組合：動畫排版與字幕）
static/          網頁介面
data/            頻道定位、設定、品味紀錄、雷達、每一集的檔案
```
