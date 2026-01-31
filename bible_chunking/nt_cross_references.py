"""
NT → OT Supplementary Cross-References

Contains well-known New Testament quotations and allusions to the Old Testament
that are not annotated in the original Markdown source files.

Each entry maps a source pericope (NT) to a target pericope (OT) with
verse-level granularity.
"""

from dataclasses import dataclass


@dataclass
class SupplementaryCrossRef:
    source_pericope_id: str   # e.g. "1pe:2:0"
    target_pericope_id: str   # e.g. "isa:28:2"
    source_verses: str        # verse(s) in source pericope, e.g. "6"
    target_verses: str        # verse(s) in target pericope, e.g. "16"
    ref_type: str             # "quotation" | "allusion"
    description: str          # brief description


# ---------------------------------------------------------------------------
# Master list of NT → OT cross-references
#
# Organised by NT book in canonical order.
# target_pericope_id uses *chapter-level* placeholder (book:chapter:0)
# because the exact pericope index depends on parsing. The pipeline's
# resolve_pericope_id() will look up the real pericope that contains the
# target verse.
# ---------------------------------------------------------------------------

SUPPLEMENTARY_CROSS_REFS: list[SupplementaryCrossRef] = [
    # ===================================================================
    # Matthew (mat)
    # ===================================================================
    # Mat 1 — Virgin birth
    SupplementaryCrossRef("mat:1:2", "isa:7:0", "22-23", "14", "quotation",
                          "童女懷孕生子"),
    # Mat 2 — Birth in Bethlehem
    SupplementaryCrossRef("mat:2:0", "mic:5:0", "6", "2", "quotation",
                          "伯利恆出君王"),
    # Mat 2 — Out of Egypt
    SupplementaryCrossRef("mat:2:2", "hos:11:0", "15", "1", "quotation",
                          "從埃及召出我的兒子"),
    # Mat 2 — Slaughter of innocents
    SupplementaryCrossRef("mat:2:3", "jer:31:2", "18", "15", "quotation",
                          "拉結為兒女哀哭"),
    # Mat 3 — Voice in the wilderness
    SupplementaryCrossRef("mat:3:0", "isa:40:0", "3", "3", "quotation",
                          "在曠野有人聲喊著說"),
    # Mat 4 — Temptation quotations
    SupplementaryCrossRef("mat:4:0", "deu:8:0", "4", "3", "quotation",
                          "人活著不是單靠食物"),
    SupplementaryCrossRef("mat:4:0", "deu:6:0", "7", "16", "quotation",
                          "不可試探主你的神"),
    SupplementaryCrossRef("mat:4:0", "deu:6:0", "10", "13", "quotation",
                          "當拜主你的神單要事奉他"),
    # Mat 4 — Great light in Galilee
    SupplementaryCrossRef("mat:4:1", "isa:9:0", "15-16", "1-2", "quotation",
                          "在黑暗中的百姓看見了大光"),
    # Mat 8 — He took our infirmities
    SupplementaryCrossRef("mat:8:1", "isa:53:0", "17", "4", "quotation",
                          "他代替我們的軟弱"),
    # Mat 11 — Messenger before
    SupplementaryCrossRef("mat:11:0", "mal:3:0", "10", "1", "quotation",
                          "我差遣我的使者在你前面"),
    # Mat 12 — My servant
    SupplementaryCrossRef("mat:12:2", "isa:42:0", "18-21", "1-4", "quotation",
                          "看哪我的僕人"),
    # Mat 13 — Speak in parables
    SupplementaryCrossRef("mat:13:2", "psa:78:0", "35", "2", "quotation",
                          "我要開口用比喻"),
    # Mat 21 — Triumphal entry
    SupplementaryCrossRef("mat:21:0", "zec:9:0", "5", "9", "quotation",
                          "你的王騎著驢來"),
    SupplementaryCrossRef("mat:21:0", "isa:62:0", "5", "11", "allusion",
                          "你的拯救者來了"),
    # Mat 21 — Rejected stone
    SupplementaryCrossRef("mat:21:3", "psa:118:0", "42", "22-23", "quotation",
                          "匠人所棄的石頭已作了房角石"),
    # Mat 22 — Greatest commandment
    SupplementaryCrossRef("mat:22:3", "deu:6:0", "37", "5", "quotation",
                          "你要盡心盡性盡意愛主你的神"),
    SupplementaryCrossRef("mat:22:3", "lev:19:0", "39", "18", "quotation",
                          "愛人如己"),
    # Mat 26-27 — Passion
    SupplementaryCrossRef("mat:26:3", "zec:13:0", "31", "7", "quotation",
                          "擊打牧人羊就分散"),
    SupplementaryCrossRef("mat:27:1", "zec:11:0", "9", "12-13", "quotation",
                          "三十塊錢"),
    SupplementaryCrossRef("mat:27:4", "psa:22:0", "46", "1", "quotation",
                          "我的神為什麼離棄我"),

    # ===================================================================
    # Mark (mrk)
    # ===================================================================
    SupplementaryCrossRef("mrk:1:0", "isa:40:0", "3", "3", "quotation",
                          "在曠野有人聲喊著說"),
    SupplementaryCrossRef("mrk:1:0", "mal:3:0", "2", "1", "quotation",
                          "差遣使者在你前面"),
    SupplementaryCrossRef("mrk:12:1", "psa:118:0", "10-11", "22-23", "quotation",
                          "匠人所棄的石頭"),
    SupplementaryCrossRef("mrk:12:3", "deu:6:0", "29-30", "4-5", "quotation",
                          "你要盡心愛主你的神"),
    SupplementaryCrossRef("mrk:15:3", "psa:22:0", "34", "1", "quotation",
                          "我的神為什麼離棄我"),

    # ===================================================================
    # Luke (luk)
    # ===================================================================
    SupplementaryCrossRef("luk:1:5", "mal:4:0", "17", "5-6", "allusion",
                          "以利亞的心志能力"),
    SupplementaryCrossRef("luk:3:0", "isa:40:0", "4-6", "3-5", "quotation",
                          "在曠野有人聲喊著說"),
    SupplementaryCrossRef("luk:4:2", "isa:61:0", "18-19", "1-2", "quotation",
                          "主的靈在我身上因為他膏了我"),
    SupplementaryCrossRef("luk:20:2", "psa:118:0", "17", "22", "quotation",
                          "匠人所棄的石頭"),
    SupplementaryCrossRef("luk:22:5", "isa:53:0", "37", "12", "quotation",
                          "他被列在罪犯之中"),

    # ===================================================================
    # John (jhn)
    # ===================================================================
    SupplementaryCrossRef("jhn:1:0", "gen:1:0", "1-3", "1", "allusion",
                          "太初有道（起初神創造）"),
    SupplementaryCrossRef("jhn:2:2", "psa:69:0", "17", "9", "quotation",
                          "我為你的殿心裏焦急"),
    SupplementaryCrossRef("jhn:6:3", "psa:78:0", "31", "24", "quotation",
                          "他從天上賜下糧食給他們吃"),
    SupplementaryCrossRef("jhn:10:2", "psa:82:0", "34", "6", "quotation",
                          "我曾說你們是神"),
    SupplementaryCrossRef("jhn:12:2", "isa:53:0", "38", "1", "quotation",
                          "主啊誰信我們所傳的"),
    SupplementaryCrossRef("jhn:12:2", "isa:6:0", "40", "10", "quotation",
                          "使他們瞎了眼硬了心"),
    SupplementaryCrossRef("jhn:12:3", "zec:9:0", "15", "9", "quotation",
                          "你的王騎著驢駒來"),
    SupplementaryCrossRef("jhn:19:3", "psa:22:0", "24", "18", "quotation",
                          "他們分了我的外衣"),
    SupplementaryCrossRef("jhn:19:3", "zec:12:0", "37", "10", "quotation",
                          "他們要仰望自己所扎的人"),

    # ===================================================================
    # Acts (act)
    # ===================================================================
    SupplementaryCrossRef("act:2:1", "jol:2:0", "17-21", "28-32", "quotation",
                          "以後我要將我的靈澆灌"),
    SupplementaryCrossRef("act:2:1", "psa:16:0", "25-28", "8-11", "quotation",
                          "你必不將我的靈魂撇在陰間"),
    SupplementaryCrossRef("act:2:2", "psa:110:0", "34-35", "1", "quotation",
                          "主對我主說你坐在我的右邊"),
    SupplementaryCrossRef("act:4:0", "psa:118:0", "11", "22", "quotation",
                          "匠人所棄的石頭已作了房角石"),
    SupplementaryCrossRef("act:8:3", "isa:53:0", "32-33", "7-8", "quotation",
                          "他像羊被牽到宰殺之地"),
    SupplementaryCrossRef("act:13:2", "psa:2:0", "33", "7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("act:13:2", "isa:55:0", "34", "3", "quotation",
                          "我必將所應許大衛那聖潔可靠的恩典賜給你們"),
    SupplementaryCrossRef("act:13:2", "psa:16:0", "35", "10", "quotation",
                          "你必不叫你的聖者見朽壞"),
    SupplementaryCrossRef("act:15:1", "amo:9:0", "16-17", "11-12", "quotation",
                          "重新修造大衛倒塌的帳幕"),

    # ===================================================================
    # Romans (rom)
    # ===================================================================
    SupplementaryCrossRef("rom:1:1", "hab:2:0", "17", "4", "quotation",
                          "義人必因信得生"),
    SupplementaryCrossRef("rom:3:2", "psa:14:0", "10-12", "1-3", "quotation",
                          "沒有義人連一個也沒有"),
    SupplementaryCrossRef("rom:3:2", "psa:5:0", "13", "9", "quotation",
                          "他們的喉嚨是敞開的墳墓"),
    SupplementaryCrossRef("rom:3:2", "psa:140:0", "13", "3", "quotation",
                          "嘴唇裏有虺蛇的毒氣"),
    SupplementaryCrossRef("rom:3:2", "psa:10:0", "14", "7", "quotation",
                          "他們滿口是咒罵苦毒"),
    SupplementaryCrossRef("rom:3:2", "isa:59:0", "15-17", "7-8", "quotation",
                          "殺人流血他們的腳飛跑"),
    SupplementaryCrossRef("rom:3:2", "psa:36:0", "18", "1", "quotation",
                          "他眼中不怕神"),
    SupplementaryCrossRef("rom:4:0", "gen:15:0", "3", "6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("rom:4:0", "psa:32:0", "7-8", "1-2", "quotation",
                          "得赦免其過的人是有福的"),
    SupplementaryCrossRef("rom:8:3", "psa:44:0", "36", "22", "quotation",
                          "為你的緣故我們終日被殺"),
    SupplementaryCrossRef("rom:9:1", "gen:21:0", "7", "12", "allusion",
                          "從以撒生的才要稱為你的後裔"),
    SupplementaryCrossRef("rom:9:2", "exo:33:0", "15", "19", "quotation",
                          "我要憐憫誰就憐憫誰"),
    SupplementaryCrossRef("rom:9:2", "exo:9:0", "17", "16", "quotation",
                          "我將你興起來特要在你身上彰顯我的權能"),
    SupplementaryCrossRef("rom:9:3", "isa:28:0", "33", "16", "quotation",
                          "在錫安放一塊絆腳石"),
    SupplementaryCrossRef("rom:9:3", "isa:8:0", "33", "14", "quotation",
                          "作了絆腳的石頭跌人的磐石"),
    SupplementaryCrossRef("rom:10:0", "deu:30:0", "6-8", "12-14", "quotation",
                          "這道離你不遠"),
    SupplementaryCrossRef("rom:10:0", "isa:28:0", "11", "16", "quotation",
                          "信靠他的人必不至於羞愧"),
    SupplementaryCrossRef("rom:10:0", "jol:2:0", "13", "32", "quotation",
                          "凡求告主名的就必得救"),
    SupplementaryCrossRef("rom:10:1", "isa:52:0", "15", "7", "quotation",
                          "報福音傳喜信的人的腳蹤何等佳美"),
    SupplementaryCrossRef("rom:10:1", "isa:53:0", "16", "1", "quotation",
                          "主啊誰信我們所傳的呢"),
    SupplementaryCrossRef("rom:11:0", "1ki:19:0", "3-4", "10,18", "quotation",
                          "我為自己留下七千人"),
    SupplementaryCrossRef("rom:11:1", "isa:29:0", "8", "10", "quotation",
                          "神給他們昏迷的心"),
    SupplementaryCrossRef("rom:11:1", "psa:69:0", "9-10", "22-23", "quotation",
                          "願他們的筵席變為網羅"),
    SupplementaryCrossRef("rom:11:2", "isa:59:0", "26-27", "20-21", "quotation",
                          "必有一位救主從錫安出來"),
    SupplementaryCrossRef("rom:15:1", "psa:69:0", "3", "9", "quotation",
                          "辱罵你人的辱罵都落在我身上"),
    SupplementaryCrossRef("rom:15:1", "isa:11:0", "12", "10", "quotation",
                          "耶西的根要興起來"),

    # ===================================================================
    # 1 Corinthians (1co)
    # ===================================================================
    SupplementaryCrossRef("1co:1:1", "isa:29:0", "19", "14", "quotation",
                          "我要滅絕智慧人的智慧"),
    SupplementaryCrossRef("1co:3:1", "job:5:0", "19", "13", "quotation",
                          "他叫有智慧的中了自己的詭計"),
    SupplementaryCrossRef("1co:3:1", "psa:94:0", "20", "11", "quotation",
                          "主知道智慧人的意念是虛妄的"),
    SupplementaryCrossRef("1co:10:0", "exo:32:0", "7", "6", "quotation",
                          "百姓坐下吃喝起來玩耍"),
    SupplementaryCrossRef("1co:15:3", "isa:25:0", "54", "8", "quotation",
                          "死被得勝吞滅了"),
    SupplementaryCrossRef("1co:15:3", "hos:13:0", "55", "14", "quotation",
                          "死啊你得勝的權勢在哪裏"),

    # ===================================================================
    # 2 Corinthians (2co)
    # ===================================================================
    SupplementaryCrossRef("2co:4:0", "gen:1:0", "6", "3", "allusion",
                          "那吩咐光從黑暗裏照出來的神"),
    SupplementaryCrossRef("2co:6:1", "isa:49:0", "2", "8", "quotation",
                          "在悅納的時候我應允了你"),
    SupplementaryCrossRef("2co:6:2", "lev:26:0", "16", "12", "quotation",
                          "我要在他們中間居住"),

    # ===================================================================
    # Galatians (gal)
    # ===================================================================
    SupplementaryCrossRef("gal:3:1", "gen:15:0", "6", "6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("gal:3:1", "gen:12:0", "8", "3", "quotation",
                          "萬國都必因你得福"),
    SupplementaryCrossRef("gal:3:1", "deu:27:0", "10", "26", "quotation",
                          "凡不常照律法書上所記一切之事去行的就被咒詛"),
    SupplementaryCrossRef("gal:3:1", "hab:2:0", "11", "4", "quotation",
                          "義人必因信得生"),
    SupplementaryCrossRef("gal:3:1", "deu:21:0", "13", "23", "quotation",
                          "凡掛在木頭上都是被咒詛的"),
    SupplementaryCrossRef("gal:4:2", "gen:21:0", "30", "10", "quotation",
                          "把使女和她兒子趕出去"),

    # ===================================================================
    # Ephesians (eph)
    # ===================================================================
    SupplementaryCrossRef("eph:4:0", "psa:68:0", "8", "18", "quotation",
                          "他升上高天擄掠了仇敵"),
    SupplementaryCrossRef("eph:5:3", "gen:2:0", "31", "24", "quotation",
                          "人要離開父母與妻子連合二人成為一體"),
    SupplementaryCrossRef("eph:6:0", "exo:20:0", "2-3", "12", "quotation",
                          "要孝敬父母使你得福在世長壽"),

    # ===================================================================
    # Philippians (php)
    # ===================================================================
    SupplementaryCrossRef("php:2:0", "isa:45:0", "10-11", "23", "quotation",
                          "萬膝都要跪拜萬口都要宣認"),

    # ===================================================================
    # Hebrews (heb)
    # ===================================================================
    # Heb 1 — Son superior to angels
    SupplementaryCrossRef("heb:1:0", "psa:2:0", "5", "7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("heb:1:0", "2sa:7:0", "5", "14", "quotation",
                          "我要作他的父他要作我的子"),
    SupplementaryCrossRef("heb:1:0", "psa:104:0", "7", "4", "quotation",
                          "以風為使者以火焰為僕役"),
    SupplementaryCrossRef("heb:1:0", "psa:45:0", "8-9", "6-7", "quotation",
                          "你的寶座是永永遠遠的"),
    SupplementaryCrossRef("heb:1:0", "psa:102:0", "10-12", "25-27", "quotation",
                          "你起初立了地的根基"),
    SupplementaryCrossRef("heb:1:0", "psa:110:0", "13", "1", "quotation",
                          "你坐在我的右邊"),
    # Heb 2 — Psalm 8
    SupplementaryCrossRef("heb:2:0", "psa:8:0", "6-8", "4-6", "quotation",
                          "人算什麼你竟顧念他"),
    SupplementaryCrossRef("heb:2:0", "psa:22:0", "12", "22", "quotation",
                          "我要將你的名傳與我的弟兄"),
    SupplementaryCrossRef("heb:2:0", "isa:8:0", "13", "17-18", "quotation",
                          "看哪我與神所給我的兒女"),
    # Heb 3 — Moses & rest
    SupplementaryCrossRef("heb:3:0", "psa:95:0", "7-11", "7-11", "quotation",
                          "你們今日若聽他的話就不可硬著心"),
    SupplementaryCrossRef("heb:3:1", "psa:95:0", "15", "7-8", "quotation",
                          "不可硬著心"),
    # Heb 4 — Sabbath rest
    SupplementaryCrossRef("heb:4:0", "gen:2:0", "4", "2", "quotation",
                          "到第七日神歇了一切的工"),
    SupplementaryCrossRef("heb:4:0", "psa:95:0", "3,5,7", "11", "quotation",
                          "他們斷不可進入我的安息"),
    # Heb 5-7 — Melchizedek priesthood
    SupplementaryCrossRef("heb:5:0", "psa:2:0", "5", "7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("heb:5:0", "psa:110:0", "6", "4", "quotation",
                          "你是照著麥基洗德的等次永遠為祭司"),
    SupplementaryCrossRef("heb:7:0", "gen:14:0", "1-2", "18-20", "quotation",
                          "麥基洗德迎接亞伯拉罕"),
    SupplementaryCrossRef("heb:7:1", "psa:110:0", "17,21", "4", "quotation",
                          "照著麥基洗德的等次永遠為祭司"),
    # Heb 8 — New covenant
    SupplementaryCrossRef("heb:8:0", "jer:31:0", "8-12", "31-34", "quotation",
                          "我要與以色列家另立新約"),
    # Heb 10
    SupplementaryCrossRef("heb:10:0", "psa:40:0", "5-7", "6-8", "quotation",
                          "祭物和禮物是你不願意的"),
    SupplementaryCrossRef("heb:10:1", "jer:31:0", "16-17", "33-34", "quotation",
                          "我要將我的律法放在他們心上"),
    SupplementaryCrossRef("heb:10:2", "hab:2:0", "37-38", "3-4", "quotation",
                          "義人必因信得生"),
    # Heb 11 — Faith chapter allusions
    SupplementaryCrossRef("heb:11:0", "gen:1:0", "3", "1", "allusion",
                          "因著信我們知道諸世界是藉神話造成的"),
    SupplementaryCrossRef("heb:11:0", "gen:4:0", "4", "3-5", "allusion",
                          "亞伯因著信獻祭與神"),
    SupplementaryCrossRef("heb:11:0", "gen:5:0", "5", "24", "allusion",
                          "以諾因著信被接去"),
    SupplementaryCrossRef("heb:11:0", "gen:6:0", "7", "13-22", "allusion",
                          "挪亞因著信預備了方舟"),
    SupplementaryCrossRef("heb:11:0", "gen:12:0", "8-10", "1-4", "allusion",
                          "亞伯拉罕因著信蒙召出去"),
    SupplementaryCrossRef("heb:11:1", "gen:22:0", "17-19", "1-14", "allusion",
                          "亞伯拉罕因著信獻以撒"),
    # Heb 12
    SupplementaryCrossRef("heb:12:0", "pro:3:0", "5-6", "11-12", "quotation",
                          "我兒不可輕看主的管教"),
    SupplementaryCrossRef("heb:12:1", "hag:2:0", "26", "6", "quotation",
                          "再一次我不單要震動地還要震動天"),
    # Heb 13
    SupplementaryCrossRef("heb:13:0", "deu:31:0", "5", "6", "quotation",
                          "我總不撇下你也不丟棄你"),
    SupplementaryCrossRef("heb:13:0", "psa:118:0", "6", "6", "quotation",
                          "主是幫助我的我必不懼怕"),

    # ===================================================================
    # James (jas)
    # ===================================================================
    SupplementaryCrossRef("jas:2:2", "gen:15:0", "23", "6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("jas:2:2", "lev:19:0", "8", "18", "quotation",
                          "要愛人如己"),

    # ===================================================================
    # 1 Peter (1pe)
    # ===================================================================
    # 1 Pet 1 — Be holy
    SupplementaryCrossRef("1pe:1:1", "lev:19:0", "16", "2", "quotation",
                          "你們要聖潔因為我是聖潔的"),
    SupplementaryCrossRef("1pe:1:2", "isa:40:0", "24-25", "6-8", "quotation",
                          "凡有血氣的盡都如草惟有主的道是永存的"),
    # 1 Pet 2 — Living stones (THE KEY CROSS-REFS!)
    SupplementaryCrossRef("1pe:2:0", "isa:28:0", "6", "16", "quotation",
                          "在錫安放一塊石頭作為根基是寶貴的房角石"),
    SupplementaryCrossRef("1pe:2:0", "psa:118:0", "7", "22", "quotation",
                          "匠人所棄的石頭已作了房角的頭塊石頭"),
    SupplementaryCrossRef("1pe:2:0", "isa:8:0", "8", "14", "quotation",
                          "作了絆腳的石頭跌人的磐石"),
    SupplementaryCrossRef("1pe:2:0", "exo:19:0", "9", "5-6", "quotation",
                          "你們是被揀選的族類是有君尊的祭司"),
    SupplementaryCrossRef("1pe:2:0", "hos:2:0", "10", "23", "quotation",
                          "從前不是子民現在卻是神的子民"),
    # 1 Pet 2 — Suffering servant
    SupplementaryCrossRef("1pe:2:2", "isa:53:0", "22", "9", "quotation",
                          "他並沒有犯罪口裏也沒有詭詐"),
    SupplementaryCrossRef("1pe:2:2", "isa:53:0", "24", "5-6", "quotation",
                          "因他受的鞭傷你們得了醫治"),
    SupplementaryCrossRef("1pe:2:2", "isa:53:0", "25", "6", "quotation",
                          "你們從前好像迷路的羊"),
    # 1 Pet 3
    SupplementaryCrossRef("1pe:3:1", "psa:34:0", "10-12", "12-16", "quotation",
                          "主的眼看顧義人主的耳聽他們的呼求"),
    SupplementaryCrossRef("1pe:3:1", "isa:8:0", "14-15", "12-13", "quotation",
                          "不要怕人的威嚇也不要驚慌"),
    # 1 Pet 5
    SupplementaryCrossRef("1pe:5:0", "pro:3:0", "5", "34", "quotation",
                          "神阻擋驕傲的人賜恩給謙卑的人"),

    # ===================================================================
    # 2 Peter (2pe)
    # ===================================================================
    SupplementaryCrossRef("2pe:2:0", "pro:26:0", "22", "11", "quotation",
                          "狗所吐的他轉過來又吃"),

    # ===================================================================
    # Jude (jud)
    # ===================================================================
    SupplementaryCrossRef("jud:1:0", "zec:3:0", "9", "2", "allusion",
                          "主責備你吧"),

    # ===================================================================
    # Revelation (rev)
    # ===================================================================
    SupplementaryCrossRef("rev:1:0", "dan:7:0", "7", "13", "allusion",
                          "看哪他駕雲降臨"),
    SupplementaryCrossRef("rev:1:0", "zec:12:0", "7", "10", "allusion",
                          "連刺他的人也要看見他"),
    SupplementaryCrossRef("rev:1:0", "dan:10:0", "13-16", "5-6", "allusion",
                          "人子的形像"),
    SupplementaryCrossRef("rev:2:0", "gen:2:0", "7", "9", "allusion",
                          "生命樹"),
    SupplementaryCrossRef("rev:4:0", "isa:6:0", "8", "3", "allusion",
                          "聖哉聖哉聖哉"),
    SupplementaryCrossRef("rev:4:0", "ezk:1:0", "6-7", "5-10", "allusion",
                          "四活物的形像"),
    SupplementaryCrossRef("rev:5:0", "dan:7:0", "5-6", "13-14", "allusion",
                          "被殺的羔羊配得權柄"),
    SupplementaryCrossRef("rev:7:0", "isa:49:0", "16-17", "10", "allusion",
                          "不再飢不再渴"),
    SupplementaryCrossRef("rev:11:1", "dan:7:0", "15", "14,27", "allusion",
                          "世上的國成了我主基督的國"),
    SupplementaryCrossRef("rev:15:0", "exo:15:0", "3-4", "1-18", "allusion",
                          "摩西的歌"),
    SupplementaryCrossRef("rev:18:0", "isa:13:0", "2", "19-22", "allusion",
                          "巴比倫傾倒了"),
    SupplementaryCrossRef("rev:18:0", "jer:51:0", "2-8", "6-9,45", "allusion",
                          "巴比倫大城傾倒了"),
    SupplementaryCrossRef("rev:19:1", "psa:118:0", "1", "1", "allusion",
                          "哈利路亞"),
    SupplementaryCrossRef("rev:19:2", "dan:7:0", "11-16", "13-14", "allusion",
                          "萬王之王萬主之主"),
    SupplementaryCrossRef("rev:20:0", "isa:65:0", "4", "17", "allusion",
                          "新天新地"),
    SupplementaryCrossRef("rev:21:0", "isa:65:0", "1", "17", "quotation",
                          "我造新天新地"),
    SupplementaryCrossRef("rev:21:0", "isa:25:0", "4", "8", "quotation",
                          "神要擦去他們一切的眼淚"),
    SupplementaryCrossRef("rev:22:0", "gen:2:0", "1-2", "9-10", "allusion",
                          "生命樹和生命河"),
    SupplementaryCrossRef("rev:22:0", "ezk:47:0", "1", "1-12", "allusion",
                          "生命水的河"),
]


def resolve_pericope_id(
    books: list,
    book_id: str,
    chapter_num: int,
    verse_num: int,
) -> str | None:
    """
    Given a book_id, chapter number, and verse number, find the pericope ID
    that contains that verse.

    Args:
        books: list of parsed Book objects
        book_id: e.g. "isa"
        chapter_num: e.g. 28
        verse_num: e.g. 16

    Returns:
        pericope ID like "isa:28:2" or None if not found
    """
    for book in books:
        if book.id != book_id:
            continue
        for chapter in book.chapters:
            if chapter.chapter_num != chapter_num:
                continue
            for pericope in chapter.pericopes:
                for verse in pericope.verses:
                    if verse.verse_start <= verse_num <= verse.verse_end:
                        return pericope.id
    return None
