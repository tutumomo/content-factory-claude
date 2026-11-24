# NSFW 內容生成：設計文件

日期：2026-11-24
狀態：**提案，未實作**
分支：`tutumomo/nsfw-content-generation-proposal`（不併入主幹）
前置文件：`docs/PLAN-6-FEATURES-20261121.md`

## 摘要

本文件評估在內容工廠加入成人向（NSFW）內容生成能力所需的架構改動。

結論先講：這不是一個開關，是四個互相牽動的軸——**內容模式、分級、角色一致性、發布去向**。四個軸只要有一個沒接好，就會出現「生得出來但流程卡死」或「流程跑完但不敢發布」的半成品。

設計原則是**預設行為完全不變**：所有新欄位都有安全預設值，未開啟分級的集數走現行邏輯，`pytest tests` 的 57 個測試不需修改即應全綠。

## 開工前必須先定的事

有五件事會決定後面所有設計，沒定之前不建議動程式碼。

| # | 問題 | 為什麼卡住設計 | 建議預設 |
|---|---|---|---|
| 1 | 成片要發到哪裡 | 決定第 7 節發布分岔要做到什麼程度 | 本機成片，不自動上傳 |
| 2 | 由哪一組 LLM 寫稿 | 決定第 3 節路由清單的內容 | 成人集指定本機 OpenAI 相容端點 |
| 3 | 是否使用真人長相／音色 | 決定第 5 節角色系統是否需要「禁止真人」硬鎖 | 一律原創虛構角色 |
| 4 | 分級是逐集指定還是整頻道 | 決定欄位放 episode 還是 channel，或兩者 | 逐集指定，頻道只設上限 |
| 5 | 成人集與一般集的資料是否分開 | 決定第 8 節資料隔離的做法 | 分開（獨立 `CF_DATA`） |

## 1. 現況盤點

以下都是實際讀過程式碼確認的，不是推測。

### 1.1 已經可以直接用的部分

| 環節 | 位置 | 現況 |
|---|---|---|
| 生圖 | `app/comfy.py:18-58` | 四個 preset 的 CLIP 全是 uncensored 或 abliterated 版本；`visuals.lora` 的註解範例就是 `KREA2turboNSFW` |
| 生影片 | `app/h3video.py:57-100` | 本機 ComfyUI 節點，無內容過濾層 |
| 配音 | `app/store.py` `tts.voice_ref` | audio.cpp 支援音色克隆 |
| 多模型互審骨架 | `app/prompts.py:164-169` | `CRITICS` 是 dict，本來就能換表 |
| 來源鏈機制 | `app/sources.py:41` `PAID` | 已有「條件式移除來源」的先例，可照抄 |
| 離線測試台 | `tests/conftest.py` | LLM／ComfyUI／H3 全部有假服務，改動可以零成本測 |

### 1.2 會直接卡死的部分

| 問題 | 位置 | 症狀 |
|---|---|---|
| LLM 拒寫 | `app/llm.py:98` | 預設 `claude -p`。拒寫回傳的不是 JSON，`complete_json` 會重試一次再丟 `LLMError`，整集停在 `brief` |
| 沒有分級概念 | `app/store.py:820` `new_episode()` | episode 只有 `format`（long／short），沒有任何內容分級欄位 |
| 沒有分級概念（頻道） | `app/store.py:170` `DEFAULT_CHANNEL` | 只有 `taboo`（自由文字），程式沒有任何地方會讀它來限制生成 |
| 實拍素材不受控 | `app/sources.py:43` | `visuals` 鏈固定 `h3video → comfy → stock → slides`，成人集也會去搜 Pexels／Pixabay |
| 審稿角色不適用 | `app/prompts.py:164` | 「事實查核」對虛構敘事給低分，會讓 `critique_threshold` 永遠過不了 |
| 自動上傳無防護 | `app/main.py:832`、`app/youtube.py:270` | 只要核准就能上傳，沒有分級檢查 |
| 資料同目錄 | `app/store.py:19` | 所有集數在 `DATA/episodes/`（`app/store.py:20`）平鋪 |

### 1.3 順帶發現的既有問題

`store._norm_style()`（`app/store.py:653-669`）用固定 key 清單重建風格卡，因此 `video_analysis.analyze()` 寫入的 `visual_notes`（`app/video_analysis.py:75`）在存入時就被丟掉了。`pipeline._shot_seconds()`（`app/pipeline.py:445`）讀得到卻永遠讀不到值，一路 fallback 到 `stock_shot_seconds`。

實測：

```
$ CF_DATA=$(mktemp -d) .venv/bin/python -c "
from app import store
c = store.create_style({'name':'t','visual_notes':{'avg_shot_seconds':3.0}}, activate=False)
print('visual_notes read back:', 'visual_notes' in store.get_style(c['id']))"
visual_notes read back: False
```

本文件第 5 節的角色卡會走同一條 `_norm_style` 路徑，如果照現況加欄位會踩同一個坑。修法（在 `_norm_style` 加 `visual_notes` 與新欄位）應排在角色卡之前。

## 2. 法律與平台紅線

這節不是免責聲明，是會直接改變設計的硬約束。

### 2.1 兩條絕對紅線

**未成年，零容忍。** 台灣《兒童及少年性剝削防制條例》2023 年修法後，把 AI 生成、電腦合成的虛擬兒少性影像納入「性影像」定義，製造、散布、持有都有刑責。也就是說「只是想畫但沒散布」也在處罰範圍內。

設計上這代表：

- 不能靠「提示詞寫 18+」當作防線；模型會忽略這類字樣。
- 角色卡必須有 `adult_attested: true` 的明確宣告，沒有這個欄位的角色不得用於 `rating != general`。缺欄位時拒絕，不是給預設 `true`。
- 角色卡不得有年齡欄位。任何數字看起來像年齡的一律不寫。
- 需要一道**失敗即中止**的檢查，不是警告、不是退回、不是重試。詳見 4.3。

**真人，需本人在場同意。** 台灣《刑法》第 319 條之 4（2023 年增訂）規定，以電腦合成或其他科技方法製作他人不實性影像且未經同意、足生損害者，可處 3 年以下有期徒刑；意圖散布或實際散布提高至 5 年。這條是「未經同意」＋「科技製作」，AI 合成完全落在裡面。

設計上這代表：

- 角色系統需要「禁止真人」的硬鎖：不接受照片作為參考圖，除非該角色檔有 `model_release: <檔案路徑>` 欄位。
- `tts.voice_ref` 在成人集應限制為 audio.cpp 內建音色庫，不接受任意音檔。現行設計可以複製任何人的聲音，這在有性內容的語境下是最容易出事的組合。
- `h3video` 以圖片當首幀的能力同理。

### 2.2 平台約束

| 平台 | 成人內容 | 自動化的問題 |
|---|---|---|
| YouTube | 禁止（社群規範：性內容）；年齡限制≠允許 | Data API 沒有 18+ 的可寫欄位，`contentDetails.contentRating.ytRating` 寫入會被忽略或拒絕。只能在 Studio 手動勾 |
| Instagram／Facebook | 禁止 | 同上 |
| TikTok | 禁止 | 同上 |

結論：**成人集的自動上傳必須在程式層擋掉**，不能做成「設定了就能傳」。這不是保守，是因為 API 沒有對應欄位，傳上去就是違規上架，風險落在帳號。

### 2.3 金流與廣告

成人內容在廣告與支付上屬高風險類別。這不在程式範圍，但會決定這條產品線值不值得做——如果目標是變現，這一步會先卡住。

## 3. 資料模型：三個欄位

### 3.1 欄位定義

```python
# app/store.py DEFAULT_CHANNEL 新增
"max_rating": "general",       # 頻道上限：這台機器最多做到哪一級

# app/store.py new_episode() 新增
"mode": "news",                # news | narrative
"rating": "general",           # general | suggestive | adult
"characters": [],              # 角色卡 id 清單，narrative + adult 才需要
```

兩個軸正交，但有一個組合要拒絕：

| | `general` | `suggestive` | `adult` |
|---|---|---|---|
| `news` | 現行行為 | 可（訪談、議題） | **拒絕**：新聞不需要，也最容易出事 |
| `narrative` | 可 | 可 | 目標場景 |

`mode` 決定提示詞骨架與審稿角色；`rating` 決定來源鏈、輸出與發布。分開的理由是「虛構但全年齡」和「新聞但成人」是兩種不同需求，用一個欄位表達不了。

### 3.2 驗證點

`new_episode()` 進來就驗：

```python
if mode == "news" and rating == "adult":
    raise ValueError("news 模式不支援 adult 分級")
if rating != "general" and not characters and mode == "narrative":
    raise ValueError("成人敘事需要至少一個原創角色卡")
```

上限檢查放在 `new_episode()` 與 `POST /api/episodes`（`app/main.py:463`）兩處——後者是 API 入口，前者是內部呼叫（靈感頁、排程）的入口。

### 3.3 前端

`openNewEpisodeModal()`（`static/modals.js:612`）加兩個選單。分級只在頻道上限允許時才顯示成人選項，避免誤點。

分鏡頁與集數頁要顯示分級徽章，讓「這集是什麼」在任何一頁都看得出來。

## 4. 提示詞與 LLM

### 4.1 提示詞分層

現行 `base_system()`（`app/prompts.py:74`）把頻道定位、風格卡、品味紀錄串起來。改成四層：

```
base_system(style_id)
├── 頻道定位            （現行，不變）
├── 風格卡              （現行，不變）
├── 內容模式區塊        （新增：mode 決定）
└── 品味紀錄            （現行，不變）
```

`mode == "news"` 時的模式區塊回傳現行的 `ANTI_HALLUCINATION`（`app/prompts.py:21`），行為零變化。

`mode == "narrative"` 時換成另一組規則：虛構連貫、角色一致、時間線自洽、允許合理想像但不假借真實人物或機構。`ANTI_HALLUCINATION` 的「每個產品名都要在原文找到」在虛構題材上完全不適用，必須換掉。

**`SAFETY_BOUNDARY`（`app/prompts.py:18`）兩個模式都要保留。** 這是防 prompt injection 的，成人素材更容易夾帶奇怪的指令文字，反而更需要。

`rating` 另外注入一段短規則：描述尺度、可寫與不可寫的界線。這段規則本身不該把具體內容寫進 system prompt，寫的是「可接受的敘事範圍」與「必須省略的處理方式」。

### 4.2 LLM 路由

`llm.complete()`（`app/llm.py:98`）現在只有一個 provider。加一層路由：

```python
# app/store.py DEFAULT_SETTINGS["llm"] 新增
"task_routes": {},             # {"script": "openai", "critique_fact": "openai"}；空 = 全部用主 provider
"refusal_markers": [...],      # 拒寫句型；命中就換 provider 重試
```

`llm.complete()` 依 `task` 查路由，找不到就用主 provider。成人集在建集時把 `script`／`critique_*`／`package` 指到本機端點，新聞集完全不用改設定。

### 4.3 拒寫偵測與 pre-flight

現在的失敗模式很糟：Claude 拒寫 → `complete_json` 重試一次 → 第二次也被拒 → `LLMError` → 整集 `status=error`，而且錯誤訊息是「模型回覆不是合法 JSON」，完全看不出真正原因。

三件事要做：

1. **區分拒寫與格式錯誤。** 新增 `llm.Refused(LLMError)`，在 `_claude_cli()` 與 `_openai()` 回傳後比對 `refusal_markers`（例如「I can't help」「無法協助」「I'm not able to」）。命中就拋 `Refused`，不進重試迴圈。
2. **pre-flight 探測。** 比照 `sources.start()`（`app/sources.py:397`）的做法：`brief` 之前先送一句無害的測試句，確認 provider 願意寫這類題材。省下「跑完 brief 才發現寫不了」的時間。結果快取在一集的生命週期內。
3. **失敗要講清楚。** `_worker()`（`app/pipeline.py:50`）的錯誤處理要認得 `Refused`，訊息寫成「目前 LLM 不願撰寫這個分級的內容，請在設定頁改路由」並附上建議動作，而不是丟一段 traceback。

### 4.4 未成年硬檢查

這一段單獨寫，因為它是唯一「失敗即中止」的檢查。

```python
# app/editorial.py 新增
def rating_guard(ep: dict, scr: dict | None = None) -> list[str]:
    """回傳命中項；非空就整集中止。"""
```

檢查點三個：

| 檢查點 | 位置 | 檢查對象 |
|---|---|---|
| 角色卡載入 | 新的 `app/characters.py` | `adult_attested` 必須為 `True` |
| 講稿驗證 | `pipeline._validate_script()`（`app/pipeline.py:308`） | 全部 `narration` / `headline` |
| 畫面提示 | `pipeline._comfy()` / `_h3()` 組 prompt 前 | `visual` 描述 |

實作上用兩層：一個詞表（確定性、快、不會被模型說服）＋ 一次 LLM 判定（抓詞表漏掉的迂迴說法）。任一层命中就中止。

中止的方式：`store.update_episode(eid, status="error", error=...)`，**不進閘門**。理由是不能讓使用者手動「接受風險後繼續」，這條線沒有繼續的選項。

### 4.5 審稿角色

`CRITICS`（`app/prompts.py:164`）改成依模式選表：

```python
CRITICS = {...}                      # 現行四角色，news 用
CRITICS_NARRATIVE = {
    "boundary":  ("界線與分級", ...),  # 未成年／真人／非自願，命中直接 0 分
    "coherence": ("情節連貫", ...),    # 前後因果、角色動機、時間線
    "tension":   ("情慾節奏", ...),    # 鋪陳與留白、不流於流水帳
    "ai_voice":  ("AI 腔獵人", ...),   # 沿用現行定義
}
```

`st_critique()`（`app/pipeline.py:331`）依 `ep["mode"]` 取表。`boundary` 角色回 0 分時要**直接中止**，不能只讓 `critique_threshold` 卡住後進入「使用者決定」閘門。

`GET /api/meta`（`app/main.py:61`）的 `critics` 改成依模式分組，`static/views/episode.js:38` 的審稿表跟著調整。

## 5. 畫面來源

### 5.1 分級過濾

`sources.chain()`（`app/sources.py:116`）加一個 `rating` 參數，比照現行 `PAID` 的寫法：

```python
RESTRICTED = {"stock": {"suggestive", "adult"}}   # 這些分級不能用這個來源
```

`rating in RESTRICTED[src]` 就從鏈裡移除。成人集的畫面鏈變成 `h3video → comfy → slides`。

`sources.start()` 與 `visual_batches()` 都要帶上分級；`verify.json` 的 `sources.plan` 會自然反映出「stock 不在鏈裡」，集數頁的徽章也就會顯示正確。

移除時要寫 log，明確寫「分級限制，不使用實拍素材」而不是靜默消失——使用者需要知道為什麼畫面變少。

### 5.2 Negative prompt

`app/comfy.py:116` 目前 negative 走 `ConditioningZeroOut`，等於空的負面提示，只在 prompt 字串尾端硬塞 `absolutely no text, no letters, no watermark`。成人生圖對 negative 的依賴比一般生圖重（人體結構、構圖、服裝殘留），這個缺口會直接反映在出圖品質。

改動：

```python
# app/store.py DEFAULT_SETTINGS["visuals"] 新增
"negative": "",                # 空 = 維持現行 ConditioningZeroOut
```

`_graph()`（`app/comfy.py:108`）在 `negative` 非空時改掛一個真的 `CLIPTextEncode`，接 `KSampler` 的 `negative`。`qwen21` 分支（`app/comfy.py:130-136`）已有自己的 negative 欄位，一併接。

### 5.3 每集各自的模型組合

`comfy.cfg()`（`app/comfy.py:69`）與 `h3video.cfg()`（`app/h3video.py:26`）只讀全域 settings，`pipeline._comfy()`／`_h3()`（`app/pipeline.py:517-540`）也沒有把 episode 傳進去。

要讓「新聞集用 Krea-2、成人集用 MOSS」可行，得把 cfg 當參數下傳：

```
comfy.generate(prompt, size, out, seed=None, cfg=None)
h3video.generate(desc, size, seconds, out, i=0, seed=None, cfg=None)
```

`cfg=None` 時維持讀全域，所有現有呼叫端不用改。episode 有覆寫時才傳。

### 5.4 角色一致性

這是目前最大的結構缺口。每個 scene 的 `visual` 是獨立的一句話，跨畫面、跨集都沒有「同一個角色」的概念，模型每次都會畫出不同的人。

新增 `app/characters.py`：

```json
// data/characters/<id>.json
{
  "id": "ch-xxxx",
  "name": "角色代號",
  "adult_attested": true,
  "model_release": "",
  "description": "固定不變的外觀描述片段（英文，注入每個 prompt）",
  "negative": "這個角色不該出現的特徵",
  "ref_image": "",
  "lora": "",
  "lora_strength": 0.8,
  "seed_base": 12345
}
```

`description` 是關鍵：它在每個 scene 的 prompt 前面原樣貼上，是跨畫面一致性的主要手段。`seed_base` 讓同一角色的種子固定偏移，配合描述片段能明顯提升穩定度。`ref_image` 與 `lora` 是進階選項，需要對應的 ComfyUI 節點；本機目前沒裝 IPAdapter 類節點，這一層先做描述注入即可。

兩個硬規則寫在載入時：

- `adult_attested is not True` → 不得用於 `rating != general`
- `model_release` 為空時，`ref_image` 必須為空（不允許拿真人照片當參考）

講稿端也要配合：`SCRIPT_SHAPE`（`app/prompts.py:128`）的 `scenes[]` 需要新增 `characters: []` 欄位，標明這個畫面有誰。`_validate_script()` 驗證每個 id 都存在於 episode 的 `characters` 清單。

## 6. 核准與稽核

### 6.1 兩段核准

`approve`（`app/pipeline.py:1131`）現在是一鍵。成人集改成兩段：

```
POST /api/episodes/{eid}/approve   {confirm_rating: "adult"}
```

`confirm_rating` 必須與 `ep["rating"]` 完全相同，否則 400。這不是安全機制（擋不住有心人），是防止誤點——分級標籤一旦寫錯，後面所有輸出都跟著錯。

`store.update_episode` 要記下 `approvals` 陣列：`[{gate, at, rating, confirm_rating}]`，讓「誰在什麼時候按了什麼」有紀錄。

### 6.2 生成清單

`st_assemble()` 收尾時（`app/pipeline.py:774` 附近）寫一份 `assets/manifest.json`：

```json
{
  "rating": "adult",
  "models": [{"kind": "comfy", "unet": "...", "clip": "...", "lora": "...", "lora_sha256": "..."}],
  "characters": ["ch-xxxx"],
  "scenes": [{"index": 0, "prompt_sha256": "...", "seed": 1234}],
  "llm": {"provider": "openai", "model": "..."}
}
```

用途是重現與下架。真的需要撤下一支片時，沒有這份清單就找不到當初用什麼條件生成的。

### 6.3 verify.json

`媒體檢查` 那一組加一項：

```json
"分級": {"ok": true, "value": "adult；來源鏈已排除實拍素材；角色 2 個已宣告成年"}
```

`ok` 在分級與實際使用的來源不一致時為 false（例如 `rating=adult` 卻出現 `stock`，代表過濾邏輯有洞）。這是回歸防護，不是給使用者看的。

## 7. 發布

### 7.1 輸出分岔

`st_approved()`（`app/pipeline.py:869`）依分級分岔：

| | `general` / `suggestive` | `adult` |
|---|---|---|
| `video.mp4` | ✓ | ✓ |
| `subtitles.srt` | ✓ | ✓ |
| `thumbnail.jpg` | ✓ | ✓ |
| `metadata.json` | ✓ | ✓（多 `contentRating` 與 AI 生成揭露） |
| IG 輪播卡片 | ✓ | ✗ |
| `fb_post` | ✓ | ✗ |
| `shorts/caption_*.txt` | ✓ | ✗ |
| `CHECKLIST.md` | ✗ | ✓（平台合規檢查、下架流程） |

`st_package()`（`app/pipeline.py:813`）的 LLM 產出也要跟著分岔：成人集不要求 `carousel` 與 `fb_post`，改成要求一份簡短的 `distribution_notes`。

縮圖維持現行 Pillow 大字卡（`app/render.py:319`），不用生圖。這反而是對的：平台對縮圖的尺度要求比影片本身嚴格。

### 7.2 上傳擋板

`POST /api/episodes/{eid}/youtube`（`app/main.py:832`）與 `youtube._upload()`（`app/youtube.py:270`）兩處都要擋：

```python
if ep.get("rating") != "general":
    raise HTTPException(409, "成人分級內容不支援自動上傳：YouTube 沒有可寫的年齡限制欄位，"
                             "且平台規範禁止這類內容。發布包請手動處理。")
```

兩處都要，因為 `pipeline.enqueue("youtube_upload", ...)` 可以從別的地方觸發。

## 8. 資料隔離

推薦獨立實例，不是子目錄：

```bash
CF_DATA=~/content-factory-adult ./run.sh
```

理由：

- `data/` 底下所有東西都會被備份、被 `grep`、被螢幕分享時的檔案總管看到。用子目錄只是把問題換個位置。
- `_FILES_ROOTS`（`app/main.py:848`）的白名單是以 `DATA` 為根判斷的，獨立實例天然隔離。
- 風險是兩份設定、兩份風格卡、兩份品味紀錄。可接受——這本來就是兩個頻道。

獨立實例下的設定同步：把共用的風格卡與品味紀錄用 `docs/` 之外的方式匯出匯入，或者接受兩邊各自演化。

## 9. 分階段任務

估時以「熟悉這個 codebase 的人」為準。

### 第一階段：骨架（約 1 天）

目標：分級欄位存在、來源鏈會過濾、上傳會擋、測試綠。

1. `store.py`：`DEFAULT_CHANNEL.max_rating`、`new_episode()` 的 `mode`／`rating`／`characters`、`_norm_style` 保留 `visual_notes`（修 1.3 的既有問題）。（0.2 天）
2. `sources.py`：`RESTRICTED` 與 `chain(kind, rating)`，`start()`／`overview()`／`visual_batches()` 帶分級。（0.2 天）
3. `main.py`／`modals.js`：建集表單與 API 驗證。（0.2 天）
4. `youtube.py`／`main.py`：上傳擋板。（0.1 天）
5. `verify.json` 的「分級」檢查。（0.1 天）
6. 測試：`test_sources.py` 加三條（成人集鏈不含 stock、`news+adult` 被拒、上傳被擋）。（0.2 天）

驗收：`new_episode(mode="news", rating="adult")` 拋錯；成人集的 `sources.plan` 不含 `stock`；`POST /youtube` 對成人集回 409；`pytest tests` 全綠。

### 第二階段：LLM（約 1 天）

1. `llm.py`：`task_routes`、`Refused`、拒寫偵測。（0.3 天）
2. `pipeline.py`：pre-flight 探測、`Refused` 的錯誤訊息。（0.2 天）
3. `prompts.py`：`mode="narrative"` 的模式區塊。（0.3 天）
4. 測試：mock provider 回拒寫句，驗證錯誤不被誤判成 JSON 錯誤。（0.2 天）

驗收：路由指到不可用的 provider 時，錯誤訊息說得出原因與下一步；narrative 模式下 `brief` 產出的方向不含事實查核字樣。

### 第三階段：畫面（約 1.5 天）

1. `characters.py` ＋ `data/characters/` ＋ API。（0.4 天）
2. `_comfy()`／`_h3()` 注入角色描述與 `negative`。（0.3 天）
3. `comfy.py`：真的 negative 節點、per-call cfg。（0.3 天）
4. `prompts.py`／`_validate_script()`：`scenes[].characters`。（0.2 天）
5. 測試：角色卡缺 `adult_attested` 被拒；`negative` 非空時 graph 有兩個 `CLIPTextEncode`。（0.3 天）

驗收：同一角色的兩個畫面用同一個 `seed_base` 偏移與同一段描述；關閉 `visuals.negative` 時 graph 與現行完全一致。

### 第四階段：審稿、發布、稽核（約 1 天）

1. `CRITICS_NARRATIVE` 與 `st_critique` 分派。（0.3 天）
2. `st_package`／`st_approved` 的輸出分岔。（0.3 天）
3. 兩段核准與 `approvals` 紀錄。（0.2 天）
4. `manifest.json`。（0.2 天）

驗收：`boundary` 回 0 分時集數進 `error` 而非閘門；成人集的 `publish/` 只有影片、字幕、縮圖、metadata、CHECKLIST。

**合計約 4.5 天**，不含實跑調參與法務評估。

### 建議實作順序

第一階段 → 第二階段 → 第三階段 → 第四階段。第一階段先做的理由是：它單獨就有價值（分級欄位與上傳擋板在本功能不做完整的情況下也該有），而且它是唯一能靠現有測試台完整驗證的一段。

## 10. 風險

| 風險 | 影響 | 對策 |
|---|---|---|
| uncensored CLIP 被替換 | `comfy.PRESETS` 的檔名失效，生圖全掛 | `presets()` 已有 `installed` 偵測，啟動時檢查並在集數頁示警 |
| 模型忽略分級約束 | 產出超出預期尺度 | `boundary` 審稿角色＋人工終審；不依賴 prompt 字串本身 |
| 誤判 `adult_attested` 的預設值 | 最嚴重的一條 | 缺欄位＝拒絕，不是預設 `true` |
| LLM 路由指到雲端 | 成人題材送進第三方 API，可能違反對方條款 | 路由目標限定本機端點，雲端 provider 不列入可選清單 |
| 平台政策變動 | 現在擋得住，未來不一定 | 上傳擋板是程式層硬擋，不隨設定開關 |
| 獨立 `CF_DATA` 造成設定不一致 | 兩邊風格卡分岔 | 接受；或用匯出匯入定期同步 |
| ComfyUI 共用 GPU | 成人集與新聞集同時跑會互相踢模型 | 現行 `visuals.free_after` 已處理，不需新增 |

## 11. 明確不做的事

- **不做自動上傳到成人平台。** 需要各站 API 與審核，且多數不接受自動化上傳。
- **不做真人換臉或聲音複製。** 即使有 `model_release` 欄位的設計，第一版也不開放照片當參考圖。這條線的風險與收益不成比例。
- **不在應用內訓練 LoRA。** 這是獨立的工作流，混進 pipeline 只會讓相依變複雜。
- **不做自動分級分類器。** 分級由使用者指定，程式只負責驗證與阻擋，不猜。
- **不改動新聞模式的任何現行行為。** `mode="news"`、`rating="general"` 的執行路徑必須與現在逐位元一致，這是第一階段的驗收條件。

## 12. 驗收通則

比照 `docs/PLAN-6-FEATURES-20261121.md`：

- `pytest tests` 全綠，新測試一律用 pytest 撰寫。
- 實跑一集短片；`verify.json` 有對應檢查。
- 未開分級的集數行為不變（第一階段必須逐項確認）。
- README 補上分級欄位與上傳限制的說明。
- commit 訊息用繁體中文，描述改動內容而非過程。

## 附錄：改動檔案清單

| 檔案 | 改動 |
|---|---|
| `app/store.py` | `max_rating`、`mode`／`rating`／`characters`、`_norm_style` 補欄位、`llm.task_routes`、`visuals.negative` |
| `app/sources.py` | `RESTRICTED`、`chain(kind, rating)`、`start()`／`overview()` 帶分級 |
| `app/llm.py` | `task_routes`、`Refused`、拒寫偵測 |
| `app/prompts.py` | 模式區塊、`CRITICS_NARRATIVE`、`SCRIPT_SHAPE` 的 `characters` |
| `app/pipeline.py` | pre-flight、`st_critique` 分派、`_comfy`／`_h3` 注入、`st_package`／`st_approved` 分岔、`approve` 兩段、`manifest.json` |
| `app/comfy.py` | 真 negative 節點、per-call cfg |
| `app/h3video.py` | per-call cfg |
| `app/editorial.py` | `rating_guard()` |
| `app/characters.py` | 新增 |
| `app/main.py` | 建集驗證、`/api/meta` 分模式、上傳擋板、角色 API |
| `app/youtube.py` | 上傳擋板（第二道） |
| `static/modals.js` | 建集表單兩個選單、分級徽章 |
| `static/views/episode.js` | 審稿表分模式、兩段核准 |
| `tests/test_sources.py` | 三條鏈與擋板測試 |
| `tests/test_ratings.py` | 新增：分級驗證、`rating_guard`、manifest |
