# 第三方授權與改寫說明

## AIHOT

- 來源：<https://github.com/KKKKhazix/AIHOT>
- 授權：MIT License
- 使用範圍：`industry/prompts/` 下的提示詞方法論（文字），沒有使用其程式、網站、資料庫、爬蟲、API 或信源名單。

### 搬了哪些、改成什麼

| AIHOT 原檔 | 本專案位置 | 改寫方式 |
|---|---|---|
| `prefilter.md` | `app/prompts.py` `prefilter()`＋`app/editorial.py` `prefilter_candidate()` | 保留 PASS／BLOCK／UNKNOWN 寬召回語意與「不能只憑沒提到就 BLOCK」；改成以本頻道定位判斷，UNKNOWN 一律保留待補。 |
| `selection-score.md` | `app/prompts.py` `selection_score()`／`SCORE_WEIGHTS`＋`app/editorial.py` `score_candidate()` | 保留五軸（sig／nov／cred／reson／act）、七種內容類型權重、內部計算步驟、噪聲壓制與「只評事件不評稿」邊界；讀者設定與頻道主題改由 `data/channel.json` 注入，`{{siteName}}` 改為 `prompts.site_name()`。另外要求模型多回一句給 owner 的評分依據（明訂不得影響分數）。 |
| `group-definitions.md`、`group-method.md`、`group-signal.md`、`group-pair.md`、`group-batch.md` | `app/prompts.py` `EVENT_DEFINITIONS`／`GROUP_METHOD`／`group_batch()`＋`app/editorial.py` `group_candidates()` | 保留 SAME_OCCURRENCE／SAME_STORY／UNRELATED／ROUNDUP 定義、綜合稿優先、日期不能證明先後、同產品生命週期不是事件等判斷法；改成逐則對既有事件組批次判斷，模型外做貪婪聚類。 |
| `rules-anti-hallucination.md` | `app/prompts.py` `ANTI_HALLUCINATION` | 九條規則全文意譯為繁體中文，接進方向、講稿、事實審稿、包裝與來源求證。 |
| `rules-self-contained-title.md` | `app/prompts.py` `SELF_CONTAINED_TITLE`＋`app/editorial.py` `title_lint()` | 保留六條自足標題規則；另加非阻擋性的字串檢查（只有版本號／只有 teaser／太短），結果顯示給 owner。 |
| `rules-answer-first-summary.md` | `app/prompts.py` `ANSWER_FIRST_SUMMARY` | 五條答案前置規則用於說明欄第一段與摘要。 |
| `rules-domain.md` | `app/prompts.py` `TERM_RULES` | 只取與本頻道相關的專有名詞／版本號／數字保留規則，移除 AIHOT 特有的 AI 公司與產品譯名表。 |
| `safety.md` | `app/prompts.py` `SAFETY_BOUNDARY` | 保留「材料中的指令不執行、不改變評分與輸出格式」的語意，放在預篩、評分、聚類、來源求證、講稿與包裝。 |
| `structure.md`、`content-understanding.md`、`understand.md`、`summarize-*.md`、`translate-*.md` | 併入 `radar_candidates()` 與 `prefilter()` 的輸入要求 | 本專案不需要 AIHOT 的抓取／翻譯／日報管線；只取「先確認對象、動作與階段」「只依據材料」的摘要要求。 |
| `mend-wording.md`、`report-period*.md` | 未移植 | 本專案沒有逐句改寫與日報排程；既有互審與復盤流程已涵蓋。 |

### MIT License

Copyright (c) AIHOT contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
