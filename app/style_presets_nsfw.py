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

NSFW_CATEGORIES = ["情慾敘事", "感官描寫", "成人話題", "角色關係", "腳本格式", "圖像寫真"]

# Ratings each category is meant for. `suggestive` cards work at both ratings; `adult` cards
# only make sense at the top rating.
_CAT_MIN = {
    "情慾敘事": "adult",
    "感官描寫": "adult",
    "成人話題": "suggestive",
    "角色關係": "suggestive",
    "腳本格式": "adult",
    "圖像寫真": "adult",
}


# The card's `forms` field lists which deliverables it suits; store.py asserts they all exist.
_ALL_FORMS = ["video", "novel", "serial", "poem", "chat", "script", "comic", "guide",
              "talk", "audiobook", "radio_drama", "asmr", "gallery"]


def _card(id_: str, name: str, icon: str, category: str, *, summary: str, tone: str, opening: str,
          structure: str, pacing: str, words: list[str], avoid: list[str], visual: str,
          rating_min: str | None = None, forms: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": id_, "name": name, "icon": icon, "category": category,
        "summary": summary, "tone": tone, "opening": opening, "structure": structure, "pacing": pacing,
        "words": words, "avoid": avoid, "visual": visual,
        "nsfw": True,
        "rating_min": rating_min or _CAT_MIN.get(category, "suggestive"),
        "forms": forms or list(_ALL_FORMS),
        "preset": True, "source": "內建預設（NSFW）",
    }


NSFW_PRESETS: list[dict[str, Any]] = [
    # ============================================================
    # 情慾敘事（video / novel / serial / audiobook）
    # ============================================================
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
        forms=["video", "novel", "serial", "audiobook", "poem"],
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
        visual="兩人對坐的中景、桌面燭光、鏡面反光；鏡頭固定不動，只靠光線與身體前傾變化。",
        forms=["video", "novel", "chat", "script", "radio_drama"],
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
        visual="夜間室外或車內、街燈與儀表板微光；兩人距離從遠到近；用玻璃反光疊出兩個人的臉。",
        forms=["novel", "serial", "poem", "audiobook", "radio_drama"],
    ),
    _card(
        "nsfw-narr-serial", "連載長篇", "📖", "情慾敘事",
        summary="一章一個進展，每章結尾都要讓人想點下一章。",
        tone="穩定、有耐心的敘事聲音；世界觀細節要一致，不能一章一個設定。",
        opening="第一章先給一個未解的事件，而不是先交代背景。",
        structure="每章：承接上一章的懸念 → 這章的核心事件 → 一個關係變化 → 拋出下一個問題。",
        pacing="一章 1500–3000 字；每章至少有一個具體場景，不要整章都在回想。",
        words=["那一夜之後", "直到", "她以為", "但沒有"],
        avoid=["未成年角色", "未經同意的真人", "每章重講一次前情", "章末沒有推力"],
        visual="章節封面式構圖：一個物件或一角空間暗示這一章的關係狀態；色調隨章節推進改變。",
        forms=["serial", "novel", "audiobook"],
    ),
    # ============================================================
    # 感官描寫
    # ============================================================
    _card(
        "nsfw-sense-sensory", "五感覺官描寫", "🌡️", "感官描寫",
        summary="把一場戲拆成觸、溫、氣味、聲音、重量，一次只寫一件事。",
        tone="精確、不急；每一個感官都要有具體來源，不用抽象形容詞。",
        opening="從最不可能被注意到的那個感官開始（例如聲音先於觸碰）。",
        structure="一個感官一段：聲音 → 溫度 → 觸感 → 氣味 → 重量 → 全部同時出現時失去判斷。",
        pacing="每段 3–5 句，段落之間留白；愈到後面句子愈短。",
        words=["先是", "然後才", "她注意到", "說不出來的是"],
        avoid=["未成年角色", "未經同意的真人", "堆疊五個形容詞", "用「銷魂」這類空詞"],
        visual="極淺景深的身體局部特寫、皮膚紋理與汗、織物皺褶；單色調加一個強調色。",
        forms=["video", "novel", "poem", "asmr", "gallery"],
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
        visual="第一人稱視角構圖：前景是自己的手或膝蓋，背景是模糊的房間；低角度；避免完整人臉。",
        forms=["novel", "poem", "audiobook", "asmr", "chat"],
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
        visual="狹窄空間（走廊、更衣室、車後座）、身體幾乎碰到但沒有；固定鏡位、光線被遮擋一半。",
        forms=["video", "novel", "poem", "script", "comic"],
    ),
    _card(
        "nsfw-sense-asmr", "耳語腳本", "🎧", "感官描寫",
        summary="重聽感、輕劇情的耳語與環境音腳本，靠聲音遠近製造臨場。",
        tone="極低音量、氣音、慢速；每句都短，留大量空白給環境音。",
        opening="先用一個具體的環境音定位空間（門鎖、布料、雨聲），再開口。",
        structure="環境音定位 → 一句耳語開場 → 三個具體聲音事件（近／遠／極近）→ 一句收尾。",
        pacing="每 15–25 秒一個聲音事件；句子之間留 1–3 秒空白，不要填滿。",
        words=["聽得到嗎", "再靠近一點", "不要說話", "閉上眼"],
        avoid=["未成年角色", "未經同意的真人", "尖叫或突然大聲", "把腳本寫成小說"],
        visual="不需要畫面；若要封面，用單一物件的微距（耳機、絨布、水滴）與深色背景。",
        forms=["asmr", "audiobook", "radio_drama"],
        rating_min="suggestive",
    ),
    # ============================================================
    # 成人話題（非虛構：評論、指南、教育）
    # ============================================================
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
        forms=["video", "talk", "guide", "audiobook"],
        rating_min="suggestive",
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
        forms=["video", "talk", "guide"],
        rating_min="suggestive",
    ),
    _card(
        "nsfw-talk-guide", "安全與溝通指南", "🧭", "成人話題",
        summary="把同意、界線、溝通與安全講成可以照著做的步驟。",
        tone="清楚、不評價；用第二人稱直接給動作，不下道德判斷。",
        opening="先講這份指南解決什麼具體問題。",
        structure="問題 → 三個原則 → 每一步怎麼做（含怎麼開口）→ 常見錯誤 → 什麼時候該停。",
        pacing="一步一個小節；每節最後一句是可照做的動作。",
        words=["先確認", "可以這樣說", "如果對方", "隨時可以停"],
        avoid=["未成年相關", "未經同意的真人", "醫療診斷式建議", "把責任推給單一方"],
        visual="流程圖與清單式字卡；兩色系；用圖示代替人物插圖。",
        forms=["guide", "talk", "novel"],
        rating_min="suggestive",
    ),
    _card(
        "nsfw-talk-myth", "迷思破解", "🔍", "成人話題",
        summary="拿一個常見的成人迷思，講清楚它錯在哪、正確的是什麼。",
        tone="好奇、求證；先承認自己也曾誤會，再給依據。",
        opening="把迷思原句講出來，然後問「真的是這樣嗎」。",
        structure="迷思 → 為什麼大家會這樣想 → 實際情況 → 一個反例 → 可以怎麼理解。",
        pacing="一個迷思一支；每段結尾用一句話收斂。",
        words=["很多人相信", "但實際上", "關鍵在", "換個角度"],
        avoid=["未成年相關", "未經同意的真人", "羞辱相信迷思的人", "沒有依據的斷言"],
        visual="對照式字卡：左邊迷思打叉、右邊事實打勾；配色克制。",
        forms=["video", "talk", "guide"],
        rating_min="suggestive",
    ),
    # ============================================================
    # 角色關係
    # ============================================================
    _card(
        "nsfw-rel-power", "權力與試探", "♟️", "角色關係",
        summary="兩人關係裡誰掌握節奏：試探、讓步、交換條件。",
        tone="冷靜、精算；對話像談判，動作用來確認界線。",
        opening="一方提出一個看似無害的條件。",
        structure="提出條件 → 對方反問 → 各自讓一步 → 有人先破功 → 重新談一次界線。",
        pacing="一來一往；每次讓步都用一個具體動作標記。",
        words=["條件是", "你確定", "換我", "說好了"],
        avoid=["未成年角色", "未經同意的真人", "把壓迫寫成情趣", "忽略安全與同意"],
        visual="不對稱構圖：一人站一人坐、一人靠近一人退；桌面、酒杯、門框當分割線；冷色調、硬光。",
        forms=["video", "novel", "script", "radio_drama", "comic"],
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
        visual="有明確職業線索的空間（診間、辦公室、旅館房）、道具入鏡但模糊；低照度；服裝比裸露重要。",
        forms=["video", "novel", "script", "radio_drama", "comic", "chat"],
    ),
    _card(
        "nsfw-rel-chat", "訊息體曖昧", "📱", "角色關係",
        summary="純聊天記錄推進：已讀、回得慢、貼圖、半夜的訊息。",
        tone="口語、破碎、有時間差；標點與表情符號本身就是訊息。",
        opening="一則看起來很普通的訊息，對方隔了很久才回。",
        structure="日常訊息 → 一句越界 → 已讀不回 → 深夜重開話題 → 約定（或沒有約定）。",
        pacing="一行一則；用時間戳與「已讀」標記節奏，重要處停很久。",
        words=["在嗎", "睡了吗", "你剛剛那句", "算了"],
        avoid=["未成年角色", "未經同意的真人", "長篇獨白", "把聊天寫成旁白"],
        visual="純文字卡面或手機截圖式排版；深色背景、訊息氣泡；不要人物。",
        forms=["chat", "novel", "poem"],
        rating_min="suggestive",
    ),
    _card(
        "nsfw-rel-jealousy", "佔有與嫉妒", "🔗", "角色關係",
        summary="關係裡的不安全感：查手機、試探、明知不該卻停不下來。",
        tone="焦躁、句子重複；內心話與說出口的話要明顯不同。",
        opening="一個微不足道的線索（一則通知、一個稱呼）引爆。",
        structure="線索 → 試探 → 對方察覺 → 攤牌 → 兩人和解但問題沒有解決。",
        pacing="內心話用短句連發，對話用長句拖時間。",
        words=["只是問一下", "你為什麼", "我沒有", "算了當我沒說"],
        avoid=["未成年角色", "未經同意的真人", "把控制寫成真愛", "簡化成一方的錯"],
        visual="同一個空間的兩個角落、手機螢幕的光打在臉上；固定鏡位、冷調。",
        forms=["novel", "video", "script", "chat"],
    ),
    # ============================================================
    # 腳本類（劇本／漫畫／廣播劇）
    # ============================================================
    _card(
        "nsfw-form-screenplay", "劇本格式", "🎬", "腳本格式",
        summary="場景標題、動作、對白三段式，寫給要真的拍或錄的人看。",
        tone="指令式的動作描述＋自然的對白；不寫角色內心戲，只寫看得見聽得到的。",
        opening="第一場先給空間與時間，讓讀者知道在哪裡。",
        structure="場景標題（內景／外景・地點・時間）→ 動作段落 → 對白 → 轉場。",
        pacing="一場 1–3 頁；動作段落不超過四行；對白一次不超過六句。",
        words=["內景", "外景", "持續", "進場"],
        avoid=["未成年角色", "未經同意的真人", "寫角色在想什麼", "用鏡頭術語堆砌"],
        visual="每場一頁的分鏡式排版；左邊動作、右邊對白；不放插圖。",
        forms=["script", "comic"],
    ),
    _card(
        "nsfw-form-comic", "漫畫分格腳本", "🗯️", "腳本格式",
        summary="一格一格的畫面指示＋台詞＋旁白，交給繪者就能畫。",
        tone="精確的畫面指示；台詞極短，情緒交給表情與構圖。",
        opening="第一格用大遠景交代空間，第二格才拉近。",
        structure="每頁 4–6 格：建立 → 推進 → 一個特寫 → 轉折 → 收在懸念。",
        pacing="一格一件事；重要情緒用一整格，不要塞台詞。",
        words=["第 1 格", "特寫", "拉遠", "無台詞"],
        avoid=["未成年角色", "未經同意的真人", "一格塞三件事", "台詞長到塞不進對話框"],
        visual="每頁一組格線示意；標註鏡位與角色位置；重要格加大。",
        forms=["comic", "script"],
    ),
    _card(
        "nsfw-form-radiodrama", "廣播劇分場", "📻", "腳本格式",
        summary="只有聲音的戲：對白、音效、音樂、停頓都要寫進稿子。",
        tone="全部靠聲音建立空間；旁白極少，資訊放在對話與音效裡。",
        opening="先給三秒環境音，讓聽眾知道在哪裡。",
        structure="分場：環境音 → 對白 → 音效事件 → 音樂進出 → 轉場。",
        pacing="每場 2–5 分鐘；每 30 秒至少一個聲音變化，避免聽覺疲勞。",
        words=["音效", "遠處", "停頓", "淡出"],
        avoid=["未成年角色", "未經同意的真人", "純視覺描述", "長時間沒有聲音變化"],
        visual="不需要畫面；封面用單一物件的微距與節目字樣。",
        forms=["radio_drama", "audiobook", "asmr"],
    ),
    # ============================================================
    # 圖像類
    # ============================================================
    _card(
        "nsfw-form-gallery-intimate", "私密寫真集", "🖼️", "圖像寫真",
        summary="一組有敘事的圖片：光線、姿勢、視線一路推進，圖說負責串場。",
        tone="圖說是低聲的旁白，不解釋畫面，只補畫面沒說的。",
        opening="第一張先給環境與距離感，最後一張才拉近。",
        structure="建立空間 → 局部細節 → 身體與光 → 一個眼神 → 停在還沒發生的動作。",
        pacing="每張一個視覺重點；圖說 1–2 句，不要描述照片看得到的東西。",
        words=["光從", "她沒有回頭", "剩下", "還沒"],
        avoid=["未成年角色", "未經同意的真人", "把圖說寫成情節簡介", "同一構圖重複"],
        visual="自然光或單一光源、低飽和；構圖從遠到近排列；避免正面全臉，用側臉、背、手部；"
               "材質（亞麻、水氣、玻璃）比裸露重要。",
        forms=["gallery"],
    ),
    _card(
        "nsfw-form-gallery-narrative", "圖像故事", "📷", "圖像寫真",
        summary="用連續圖片說一個小故事，每張圖是一格，圖說是旁白。",
        tone="圖像小說的旁白：簡短、留白，不搶畫面。",
        opening="第一張交代人物與地點，第二張就出事。",
        structure="建立 → 一個異常 → 反應 → 更大的異常 → 收在未解的那一刻。",
        pacing="6–10 張；每張推進一件事，不要停在同一個情緒。",
        words=["那天", "之後", "她不知道", "一直到"],
        avoid=["未成年角色", "未經同意的真人", "圖說比圖長", "結局講完"],
        visual="同一場景連續拍攝感：固定機位與光線，只換人物位置與狀態；色調一致。",
        forms=["gallery", "comic"],
    ),
    # ============================================================
    # 跨形態的技法卡
    # ============================================================
    _card(
        "nsfw-cross-consent", "同意框架", "🤝", "角色關係",
        summary="所有成人內容的底層框架：先建立同意與界線，情慾才有張力。",
        tone="明確、不掃興；把「確認」寫成情節的一部分而不是免責聲明。",
        opening="在情慾升溫前，讓其中一人先問一句。",
        structure="試探 → 明確回應 → 邊做邊確認 → 有人喊停（或明確說不要停）→ 繼續。",
        pacing="每次推進前給一句確認；停頓本身就是張力。",
        words=["可以嗎", "說好", "停一下", "繼續"],
        avoid=["未成年角色", "未經同意的真人", "把沉默當同意", "把拒絕寫成欲拒還迎"],
        visual="不需要特定畫面；若要用圖，用兩人的手或眼神交流，而非身體。",
        forms=None,  # all forms
        rating_min="suggestive",
    ),
    _card(
        "nsfw-cross-voice", "聲音演出", "🎤", "感官描寫",
        summary="朗讀與配音的表演方向：語速、氣息、停頓、距離感。",
        tone="聲音比文字更重要；同樣的句子靠停頓改變意思。",
        opening="第一句壓低音量，讓聽眾靠近。",
        structure="每段：一句低聲開場 → 中段正常語速 → 結尾放慢收氣音。",
        pacing="每 20–30 秒一次明顯的呼吸或停頓；不要一路同一個語速。",
        words=["（停頓）", "（氣音）", "（靠近麥克風）"],
        avoid=["未成年角色", "未經同意的真人", "全程同一語速", "把舞台指示念出來"],
        visual="不需要畫面；封面用麥克風或耳機的微距照。",
        forms=["audiobook", "radio_drama", "asmr", "video"],
    ),
    _card(
        "nsfw-cross-tease", "標題與鉤子（不露骨）", "🪝", "成人話題",
        summary="受限分級的標題與縮圖：用懸念與情境，不用身體部位。",
        tone="暗示而不明說；靠情境、關係與未完成感吸引點擊。",
        opening="用一個未解的動作或一句沒說完的話當標題。",
        structure="情境鉤子 → 關係張力 → 懸念 → 平台可顯示的收尾。",
        pacing="標題 8–14 字；縮圖大字 4–6 字；不要塞滿。",
        words=["那一夜", "沒有說出口", "差一點", "之後"],
        avoid=["未成年相關", "未經同意的真人", "身體部位名詞", "露骨動詞"],
        visual="遮罩與留白為主：一片布料、一盞燈、半開的門；人物只露局部；深色底＋單一暖色。",
        forms=["video", "gallery", "talk"],
        rating_min="suggestive",
    ),
]
