"""Built-in style cards for restricted (NSFW) content.

Kept apart from `style_presets.py` so the general-purpose card list stays clean, and so the
`nsfw` flag is one obvious place to look. These cards differ from the general set in three ways:

* every card carries `rating_min`, the lowest rating it is meant for, so the UI can hide or warn
  about cards that do not fit the episode's rating;
* `visual` describes an image direction for an adult scene rather than a product shot;
* `avoid` encodes the hard lines (minors, real people without consent, non-consent framed as
  romance) so the model is told what not to do, not only what to do.

The cards are writing guidance, not content: they describe *how* to write a scene. The model
still has to respect the episode's rating note and the boundary critic.
"""
from __future__ import annotations

from typing import Any

NSFW_CATEGORIES = ["情慾敘事", "感官描寫", "成人話題", "角色關係"]

# Ratings each category is meant for. `suggestive` cards work at both ratings; `adult` cards
# only make sense at the top rating.
_CAT_MIN = {"情慾敘事": "adult", "感官描寫": "adult", "成人話題": "suggestive", "角色關係": "suggestive"}


def _card(id_: str, name: str, icon: str, category: str, *, summary: str, tone: str, opening: str,
          structure: str, pacing: str, words: list[str], avoid: list[str], visual: str,
          rating_min: str | None = None, forms: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": id_, "name": name, "icon": icon, "category": category,
        "summary": summary, "tone": tone, "opening": opening, "structure": structure, "pacing": pacing,
        "words": words, "avoid": avoid, "visual": visual,
        "nsfw": True,
        "rating_min": rating_min or _CAT_MIN.get(category, "suggestive"),
        "forms": forms or ["video", "novel", "audiobook", "gallery", "talk"],
        "preset": True, "source": "內建預設（NSFW）",
    }


NSFW_PRESETS: list[dict[str, Any]] = [
    # ---------- 情慾敘事 ----------
    _card(
        "nsfw-narr-slowburn", "慢熱情慾敘事", "🕯️", "情慾敘事",
        summary="從日常細節一路鋪陳到臨界點，張力靠等待而不是靠露骨。",
        tone="克制、感官精準；用具體的觸感、氣味、溫度取代形容詞堆疊。",
        opening="從一個不相關的日常動作切入（收傘、脫鞋、倒水），暗示後面的失控。",
        structure="日常情境 → 一次擦身或誤觸 → 兩人都裝作沒事 → 第二次靠近時界線鬆動 → 停在還沒說破的那一刻。",
        pacing="長句寫感官、短句寫決定；每個段落結尾留一個沒說出口的念頭。",
        words=["手指停在", "沒有立刻", "差一點", "她沒有退開"],
        avoid=["未成年角色", "未經同意的真人", "把強迫寫成浪漫", "器官清單式描寫", "突然跳到結論"],
        visual="低照度室內、單一暖光源、淺景深、布料與皮膚的質感特寫；避免正面全臉特寫，用肩膀、"
               "頸側、手腕與手指交代情緒；色調偏暖但保留陰影。",
    ),
    _card(
        "nsfw-narr-dialogue", "對話驅動情慾", "💬", "情慾敘事",
        summary="整場戲靠對話推進：試探、讓步、說破，動作極少。",
        tone="口語、帶停頓與語病；真正的意思都藏在沒說完的半句裡。",
        opening="一句聽起來很普通、但語境不對的問句。",
        structure="表面話題 → 一句越界的試探 → 對方沒有否認 → 兩人開始講條件 → 有人先鬆口。",
        pacing="短句連發，一個來回一個段落；用沉默與停頓標記權力翻轉。",
        words=["你是認真的嗎", "如果我說", "這樣算不算", "先說好"],
        avoid=["未成年角色", "未經同意的真人", "說教式收尾", "旁白解釋角色心情"],
        visual="兩人對坐的中景、桌面燭光、鏡面反光；鏡頭固定不動，只靠光線與身體前傾變化；"
               "避免誇張表情，靠眼神與手部動作。",
        forms=["video", "novel", "audiobook"],
    ),
    _card(
        "nsfw-narr-reunion", "重逢與舊關係", "🪞", "情慾敘事",
        summary="多年後再見，兩人都知道會發生什麼，戲在「要不要」而不是「會不會」。",
        tone="懷舊、帶點疲憊；回憶用現在式寫，當下用短句寫。",
        opening="在一個不該遇見的地方遇見。",
        structure="重逢 → 交換近況（都在避重就輕）→ 一個共同的記憶被提起 → 舊習慣回來 → 決定不說破。",
        pacing="現在與回憶交錯；回憶段落用長句，當下用短句切開。",
        words=["你還是", "以前你", "我以為", "沒有變"],
        avoid=["未成年角色", "未經同意的真人", "把遺憾寫成怨懟", "一次講完所有前情"],
        visual="夜間室外或車內、街燈與儀表板微光；兩人距離從遠到近；用玻璃反光疊出兩個人的臉；"
               "色調偏冷，只有皮膚是暖的。",
    ),
    # ---------- 感官描寫 ----------
    _card(
        "nsfw-sense-sensory", "五感覺官描寫", "🌡️", "感官描寫",
        summary="把一場戲拆成觸、溫、氣味、聲音、重量，一次只寫一件事。",
        tone="精確、不急；每一個感官都要有具體來源，不用抽象形容詞。",
        opening="從最不可能被注意到的那個感官開始（例如聲音先於觸碰）。",
        structure="一個感官一段：聲音 → 溫度 → 觸感 → 氣味 → 重量 → 全部同時出現時失去判斷。",
        pacing="每段 3–5 句，段落之間留白；愈到後面句子愈短。",
        words=["先是", "然後才", "她注意到", "說不出來的是"],
        avoid=["未成年角色", "未經同意的真人", "堆疊五個形容詞", "用「銷魂」這類空詞"],
        visual="極淺景深的身體局部特寫、皮膚紋理與汗、織物皺褶；單色調加一個強調色；"
               "光線從側後方來，讓輪廓清楚但表情模糊。",
    ),
    _card(
        "nsfw-sense-pov", "第二人稱視角", "👁️", "感官描寫",
        summary="用「你」把讀者放進場景，適合聲音作品與短文。",
        tone="低聲、貼近；句子短，動詞多於形容詞。",
        opening="一句直接對讀者說話的指令或提問。",
        structure="建立空間 → 一個感官細節 → 一個選擇 → 選擇之後的後果 → 停在還沒結束的地方。",
        pacing="一句一行；每 3–4 行給一個可以「呼吸」的停頓。",
        words=["你會發現", "如果你願意", "現在", "不要睜開眼"],
        avoid=["未成年角色", "未經同意的真人", "強迫語氣", "對讀者說教"],
        visual="第一人稱視角構圖：前景是自己的手或膝蓋，背景是模糊的房間；"
               "淺景深、低角度；避免出現完整人臉。",
        forms=["novel", "audiobook"],
    ),
    _card(
        "nsfw-sense-tension", "壓抑與臨界", "🫧", "感官描寫",
        summary="整段都在差一點的地方停住，張力來自沒做的事。",
        tone="緊繃、句子被截斷；大量停頓與否定句。",
        opening="描述一個「應該要發生但沒有發生」的動作。",
        structure="接近 → 停住 → 找理由離開 → 又回來 → 再一次停住 → 這次沒有停。",
        pacing="節奏愈走愈慢，句子愈來愈短；最後一段只留三句。",
        words=["差一點", "本來要", "又收回", "這次沒有"],
        avoid=["未成年角色", "未經同意的真人", "用暴力製造張力", "最後草草收尾"],
        visual="狹窄空間（走廊、更衣室、車後座）、身體幾乎碰到但沒有；固定鏡位、只靠呼吸與姿勢變化；"
               "光線被遮擋一半。",
    ),
    # ---------- 成人話題 ----------
    _card(
        "nsfw-talk-frank", "直白成人話題", "🎙️", "成人話題",
        summary="把成人議題當正經題目談：經驗、誤解、安全與界線，不迴避也不獵奇。",
        tone="直接、不裝害羞；用日常語言講清楚，不用委婉詞堆疊。",
        opening="直接把爭點講出來，並說明為什麼值得談。",
        structure="爭點 → 常見誤解 → 實際經驗或資料 → 不同意見 → 我的立場 → 給聽眾的具體建議。",
        pacing="一段一個論點；重要處放慢，用例子收束。",
        words=["說白一點", "很多人以為", "實際上是", "我的立場是"],
        avoid=["未成年相關", "未經同意的真人隱私", "把個案當通則", "獵奇化描述", "沒有依據的醫學建議"],
        visual="字卡為主：大字標語＋單色底；關鍵句用強調色；人物畫面用側面或手部，避免正面特寫。",
        forms=["video", "talk", "audiobook"],
    ),
    _card(
        "nsfw-talk-review", "作品評論與推薦", "📚", "成人話題",
        summary="評論成人向作品（小說、漫畫、影音），談技法與體驗，不爆雷不獵奇。",
        tone="像書評：具體、有品味判斷，說得出好在哪裡、差在哪裡。",
        opening="先給結論：這部適合誰、不適合誰。",
        structure="結論 → 作品定位 → 兩個具體技法觀察 → 一個明顯缺點 → 誰該看、從哪開始。",
        pacing="每個觀察一個段落，先講證據再講評價。",
        words=["技術上", "值得注意的是", "可惜的是", "如果你在意"],
        avoid=["未成年相關作品", "未經同意散布的內容", "逐格描述情節", "無依據的排名"],
        visual="書封或畫面局部的抽象特寫、模糊處理；字卡排版乾淨；避免直接使用作品畫面。",
        forms=["video", "talk", "novel"],
    ),
    # ---------- 角色關係 ----------
    _card(
        "nsfw-rel-power", "權力與試探", "♟️", "角色關係",
        summary="兩人關係裡誰掌握節奏：試探、讓步、交換條件。",
        tone="冷靜、精算；對話像談判，動作用來確認界線。",
        opening="一方提出一個看似無害的條件。",
        structure="提出條件 → 對方反問 → 各自讓一步 → 有人先破功 → 重新談一次界線。",
        pacing="一來一往；每次讓步都用一個具體動作標記。",
        words=["條件是", "你確定", "換我", "說好了"],
        avoid=["未成年角色", "未經同意的真人", "把壓迫寫成情趣", "忽略安全與同意"],
        visual="不對稱構圖：一人站一人坐、一人靠近一人退；桌面、酒杯、門框當分割線；"
               "冷色調、硬光、明顯陰影。",
    ),
    _card(
        "nsfw-rel-roleplay", "角色扮演與設定", "🎭", "角色關係",
        summary="用虛構身分（醫師、上司、陌生人）建立情境，重點是設定而非裸露。",
        tone="入戲、認真對待設定；世界觀細節要一致。",
        opening="先用一句話建立設定（時間、地點、兩人正在扮演什麼）。",
        structure="建立設定 → 進入角色 → 一個打破角色的瞬間 → 決定要不要繼續演 → 收在角色裡。",
        pacing="設定段落慢、進入角色後加快；打破角色的那一刻用短句。",
        words=["照規矩", "現在起", "你可以叫我", "先出去"],
        avoid=["未成年角色", "冒用真實人物或名人", "未經同意的真人", "把非自願寫成浪漫"],
        visual="有明確職業線索的空間（診間、辦公室、旅館房）、道具入鏡但模糊；"
               "固定鏡位、低照度；服裝比裸露重要。",
    ),
]
