"""
NT → OT Supplementary Cross-References

Contains well-known New Testament quotations and allusions to the Old Testament
that are not annotated in the original Markdown source files.

Each entry names both ends in verse coordinates, 'book chapter:verses'
(verses: n, a-b, or a comma list of those; one chapter per end). Step 0
(scripts/process_bible.py) resolves every verse of both ends to its pericope
through bible_chunking.curated_xrefs: an entry whose verses straddle a
pericope boundary yields one cross reference per touched (source, target)
pericope pair, each carrying only that pair's verses, and an entry that does
not resolve stops Step 0 before any file is written.

The 161 entries of a32fbea (pericope id + verses) are frozen in
docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json; this list is their
mechanical conversion plus the changes recorded in
scripts/tests/test_supp_defs_frozen.py::test_definition_ledger.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SupplementaryCrossRef:
    src: str                       # source end, e.g. "1pe 2:6"
    tgt: str                       # target end, e.g. "isa 28:16"
    ref_type: str                  # "quotation" | "allusion"
    description: str               # brief description
    tsk_exempt: str | None = None  # why it may lack verse-level TSK support; never stored as null


# ---------------------------------------------------------------------------
# Master list of NT → OT cross-references
#
# Organised by NT book in canonical order.
# ---------------------------------------------------------------------------

SUPPLEMENTARY_CROSS_REFS: list[SupplementaryCrossRef] = [
    # ===================================================================
    # Matthew (mat)
    # ===================================================================
    # Mat 1 — Virgin birth
    SupplementaryCrossRef("mat 1:22-23", "isa 7:14", "quotation",
                          "童女懷孕生子"),
    # Mat 2 — Birth in Bethlehem
    SupplementaryCrossRef("mat 2:6", "mic 5:2", "quotation",
                          "伯利恆出君王"),
    # Mat 2 — Out of Egypt
    SupplementaryCrossRef("mat 2:15", "hos 11:1", "quotation",
                          "從埃及召出我的兒子"),
    # Mat 2 — Slaughter of innocents
    SupplementaryCrossRef("mat 2:18", "jer 31:15", "quotation",
                          "拉結為兒女哀哭"),
    # Mat 3 — Voice in the wilderness
    SupplementaryCrossRef("mat 3:3", "isa 40:3", "quotation",
                          "在曠野有人聲喊著說"),
    # Mat 4 — Temptation quotations
    SupplementaryCrossRef("mat 4:4", "deu 8:3", "quotation",
                          "人活著不是單靠食物"),
    SupplementaryCrossRef("mat 4:7", "deu 6:16", "quotation",
                          "不可試探主你的神"),
    SupplementaryCrossRef("mat 4:10", "deu 6:13", "quotation",
                          "當拜主你的神單要事奉他"),
    # Mat 4 — Great light in Galilee
    SupplementaryCrossRef("mat 4:15-16", "isa 9:1-2", "quotation",
                          "在黑暗中的百姓看見了大光"),
    # Mat 8 — He took our infirmities
    SupplementaryCrossRef("mat 8:17", "isa 53:4", "quotation",
                          "他代替我們的軟弱"),
    # Mat 11 — Messenger before
    SupplementaryCrossRef("mat 11:10", "mal 3:1", "quotation",
                          "我差遣我的使者在你前面"),
    # Mat 12 — My servant
    SupplementaryCrossRef("mat 12:18-21", "isa 42:1-4", "quotation",
                          "看哪我的僕人"),
    # Mat 13 — Speak in parables
    SupplementaryCrossRef("mat 13:35", "psa 78:2", "quotation",
                          "我要開口用比喻"),
    # Mat 21 — Triumphal entry
    SupplementaryCrossRef("mat 21:5", "zec 9:9", "quotation",
                          "你的王騎著驢來"),
    SupplementaryCrossRef("mat 21:5", "isa 62:11", "allusion",
                          "你的拯救者來了"),
    # Mat 21 — Rejected stone
    SupplementaryCrossRef("mat 21:42", "psa 118:22-23", "quotation",
                          "匠人所棄的石頭已作了房角石"),
    # Mat 22 — Greatest commandment
    SupplementaryCrossRef("mat 22:37", "deu 6:5", "quotation",
                          "你要盡心盡性盡意愛主你的神"),
    SupplementaryCrossRef("mat 22:39", "lev 19:18", "quotation",
                          "愛人如己"),
    # Mat 26-27 — Passion
    SupplementaryCrossRef("mat 26:31", "zec 13:7", "quotation",
                          "擊打牧人羊就分散"),
    SupplementaryCrossRef("mat 27:9", "zec 11:12-13", "quotation",
                          "三十塊錢"),
    SupplementaryCrossRef("mat 27:46", "psa 22:1", "quotation",
                          "我的神為什麼離棄我"),

    # ===================================================================
    # Mark (mrk)
    # ===================================================================
    SupplementaryCrossRef("mrk 1:3", "isa 40:3", "quotation",
                          "在曠野有人聲喊著說"),
    SupplementaryCrossRef("mrk 1:2", "mal 3:1", "quotation",
                          "差遣使者在你前面"),
    SupplementaryCrossRef("mrk 12:10-11", "psa 118:22-23", "quotation",
                          "匠人所棄的石頭"),
    SupplementaryCrossRef("mrk 12:29-30", "deu 6:4-5", "quotation",
                          "你要盡心愛主你的神"),
    SupplementaryCrossRef("mrk 15:34", "psa 22:1", "quotation",
                          "我的神為什麼離棄我"),

    # ===================================================================
    # Luke (luk)
    # ===================================================================
    SupplementaryCrossRef("luk 1:17", "mal 4:5-6", "allusion",
                          "以利亞的心志能力"),
    SupplementaryCrossRef("luk 3:4-6", "isa 40:3-5", "quotation",
                          "在曠野有人聲喊著說"),
    SupplementaryCrossRef("luk 4:18-19", "isa 61:1-2", "quotation",
                          "主的靈在我身上因為他膏了我"),
    SupplementaryCrossRef("luk 20:17", "psa 118:22", "quotation",
                          "匠人所棄的石頭"),
    SupplementaryCrossRef("luk 22:37", "isa 53:12", "quotation",
                          "他被列在罪犯之中"),

    # ===================================================================
    # John (jhn)
    # ===================================================================
    SupplementaryCrossRef("jhn 1:1-3", "gen 1:1", "allusion",
                          "太初有道（起初神創造）"),
    SupplementaryCrossRef("jhn 2:17", "psa 69:9", "quotation",
                          "我為你的殿心裏焦急"),
    SupplementaryCrossRef("jhn 6:31", "psa 78:24", "quotation",
                          "他從天上賜下糧食給他們吃"),
    SupplementaryCrossRef("jhn 10:34", "psa 82:6", "quotation",
                          "我曾說你們是神"),
    SupplementaryCrossRef("jhn 12:38", "isa 53:1", "quotation",
                          "主啊誰信我們所傳的"),
    SupplementaryCrossRef("jhn 12:40", "isa 6:10", "quotation",
                          "使他們瞎了眼硬了心"),
    SupplementaryCrossRef("jhn 12:15", "zec 9:9", "quotation",
                          "你的王騎著驢駒來"),
    SupplementaryCrossRef("jhn 19:24", "psa 22:18", "quotation",
                          "他們分了我的外衣"),
    SupplementaryCrossRef("jhn 19:37", "zec 12:10", "quotation",
                          "他們要仰望自己所扎的人"),

    # ===================================================================
    # Acts (act)
    # ===================================================================
    SupplementaryCrossRef("act 2:17-21", "jol 2:28-32", "quotation",
                          "以後我要將我的靈澆灌"),
    SupplementaryCrossRef("act 2:25-28", "psa 16:8-11", "quotation",
                          "你必不將我的靈魂撇在陰間"),
    SupplementaryCrossRef("act 2:34-35", "psa 110:1", "quotation",
                          "主對我主說你坐在我的右邊"),
    SupplementaryCrossRef("act 4:11", "psa 118:22", "quotation",
                          "匠人所棄的石頭已作了房角石"),
    SupplementaryCrossRef("act 8:32-33", "isa 53:7-8", "quotation",
                          "他像羊被牽到宰殺之地"),
    SupplementaryCrossRef("act 13:33", "psa 2:7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("act 13:34", "isa 55:3", "quotation",
                          "我必將所應許大衛那聖潔可靠的恩典賜給你們"),
    SupplementaryCrossRef("act 13:35", "psa 16:10", "quotation",
                          "你必不叫你的聖者見朽壞"),
    SupplementaryCrossRef("act 15:16-17", "amo 9:11-12", "quotation",
                          "重新修造大衛倒塌的帳幕"),

    # ===================================================================
    # Romans (rom)
    # ===================================================================
    SupplementaryCrossRef("rom 1:17", "hab 2:4", "quotation",
                          "義人必因信得生"),
    SupplementaryCrossRef("rom 3:10-12", "psa 14:1-3", "quotation",
                          "沒有義人連一個也沒有"),
    SupplementaryCrossRef("rom 3:13", "psa 5:9", "quotation",
                          "他們的喉嚨是敞開的墳墓"),
    SupplementaryCrossRef("rom 3:13", "psa 140:3", "quotation",
                          "嘴唇裏有虺蛇的毒氣"),
    SupplementaryCrossRef("rom 3:14", "psa 10:7", "quotation",
                          "他們滿口是咒罵苦毒"),
    SupplementaryCrossRef("rom 3:15-17", "isa 59:7-8", "quotation",
                          "殺人流血他們的腳飛跑"),
    SupplementaryCrossRef("rom 3:18", "psa 36:1", "quotation",
                          "他眼中不怕神"),
    SupplementaryCrossRef("rom 4:3", "gen 15:6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("rom 4:7-8", "psa 32:1-2", "quotation",
                          "得赦免其過的人是有福的"),
    SupplementaryCrossRef("rom 8:36", "psa 44:22", "quotation",
                          "為你的緣故我們終日被殺"),
    SupplementaryCrossRef("rom 9:7", "gen 21:12", "allusion",
                          "從以撒生的才要稱為你的後裔"),
    SupplementaryCrossRef("rom 9:15", "exo 33:19", "quotation",
                          "我要憐憫誰就憐憫誰"),
    SupplementaryCrossRef("rom 9:17", "exo 9:16", "quotation",
                          "我將你興起來特要在你身上彰顯我的權能"),
    SupplementaryCrossRef("rom 9:33", "isa 28:16", "quotation",
                          "在錫安放一塊絆腳石"),
    SupplementaryCrossRef("rom 9:33", "isa 8:14", "quotation",
                          "作了絆腳的石頭跌人的磐石"),
    SupplementaryCrossRef("rom 10:6-8", "deu 30:12-14", "quotation",
                          "這道離你不遠"),
    SupplementaryCrossRef("rom 10:11", "isa 28:16", "quotation",
                          "信靠他的人必不至於羞愧"),
    SupplementaryCrossRef("rom 10:13", "jol 2:32", "quotation",
                          "凡求告主名的就必得救"),
    SupplementaryCrossRef("rom 10:15", "isa 52:7", "quotation",
                          "報福音傳喜信的人的腳蹤何等佳美"),
    SupplementaryCrossRef("rom 10:16", "isa 53:1", "quotation",
                          "主啊誰信我們所傳的呢"),
    SupplementaryCrossRef("rom 11:3-4", "1ki 19:10,18", "quotation",
                          "我為自己留下七千人"),
    SupplementaryCrossRef("rom 11:8", "isa 29:10", "quotation",
                          "神給他們昏迷的心"),
    SupplementaryCrossRef("rom 11:9-10", "psa 69:22-23", "quotation",
                          "願他們的筵席變為網羅"),
    SupplementaryCrossRef("rom 11:26-27", "isa 59:20-21", "quotation",
                          "必有一位救主從錫安出來"),
    SupplementaryCrossRef("rom 15:3", "psa 69:9", "quotation",
                          "辱罵你人的辱罵都落在我身上"),
    SupplementaryCrossRef("rom 15:12", "isa 11:10", "quotation",
                          "耶西的根要興起來"),

    # ===================================================================
    # 1 Corinthians (1co)
    # ===================================================================
    SupplementaryCrossRef("1co 1:19", "isa 29:14", "quotation",
                          "我要滅絕智慧人的智慧"),
    SupplementaryCrossRef("1co 3:19", "job 5:13", "quotation",
                          "他叫有智慧的中了自己的詭計"),
    SupplementaryCrossRef("1co 3:20", "psa 94:11", "quotation",
                          "主知道智慧人的意念是虛妄的"),
    SupplementaryCrossRef("1co 10:7", "exo 32:6", "quotation",
                          "百姓坐下吃喝起來玩耍"),
    SupplementaryCrossRef("1co 15:54", "isa 25:8", "quotation",
                          "死被得勝吞滅了"),
    SupplementaryCrossRef("1co 15:55", "hos 13:14", "quotation",
                          "死啊你得勝的權勢在哪裏"),

    # ===================================================================
    # 2 Corinthians (2co)
    # ===================================================================
    SupplementaryCrossRef("2co 4:6", "gen 1:3", "allusion",
                          "那吩咐光從黑暗裏照出來的神"),
    SupplementaryCrossRef("2co 6:2", "isa 49:8", "quotation",
                          "在悅納的時候我應允了你"),
    SupplementaryCrossRef("2co 6:16", "lev 26:12", "quotation",
                          "我要在他們中間居住"),

    # ===================================================================
    # Galatians (gal)
    # ===================================================================
    SupplementaryCrossRef("gal 3:6", "gen 15:6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("gal 3:8", "gen 12:3", "quotation",
                          "萬國都必因你得福"),
    SupplementaryCrossRef("gal 3:10", "deu 27:26", "quotation",
                          "凡不常照律法書上所記一切之事去行的就被咒詛"),
    SupplementaryCrossRef("gal 3:11", "hab 2:4", "quotation",
                          "義人必因信得生"),
    SupplementaryCrossRef("gal 3:13", "deu 21:23", "quotation",
                          "凡掛在木頭上都是被咒詛的"),
    SupplementaryCrossRef("gal 4:30", "gen 21:10", "quotation",
                          "把使女和她兒子趕出去"),

    # ===================================================================
    # Ephesians (eph)
    # ===================================================================
    SupplementaryCrossRef("eph 4:8", "psa 68:18", "quotation",
                          "他升上高天擄掠了仇敵"),
    SupplementaryCrossRef("eph 5:31", "gen 2:24", "quotation",
                          "人要離開父母與妻子連合二人成為一體"),
    SupplementaryCrossRef("eph 6:2-3", "exo 20:12", "quotation",
                          "要孝敬父母使你得福在世長壽"),

    # ===================================================================
    # Philippians (php)
    # ===================================================================
    SupplementaryCrossRef("php 2:10-11", "isa 45:23", "quotation",
                          "萬膝都要跪拜萬口都要宣認"),

    # ===================================================================
    # Hebrews (heb)
    # ===================================================================
    # Heb 1 — Son superior to angels
    SupplementaryCrossRef("heb 1:5", "psa 2:7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("heb 1:5", "2sa 7:14", "quotation",
                          "我要作他的父他要作我的子"),
    SupplementaryCrossRef("heb 1:7", "psa 104:4", "quotation",
                          "以風為使者以火焰為僕役"),
    SupplementaryCrossRef("heb 1:8-9", "psa 45:6-7", "quotation",
                          "你的寶座是永永遠遠的"),
    SupplementaryCrossRef("heb 1:10-12", "psa 102:25-27", "quotation",
                          "你起初立了地的根基"),
    SupplementaryCrossRef("heb 1:13", "psa 110:1", "quotation",
                          "你坐在我的右邊"),
    # Heb 2 — Psalm 8
    SupplementaryCrossRef("heb 2:6-8", "psa 8:4-6", "quotation",
                          "人算什麼你竟顧念他"),
    SupplementaryCrossRef("heb 2:12", "psa 22:22", "quotation",
                          "我要將你的名傳與我的弟兄"),
    SupplementaryCrossRef("heb 2:13", "isa 8:17-18", "quotation",
                          "看哪我與神所給我的兒女"),
    # Heb 3 — Moses & rest
    SupplementaryCrossRef("heb 3:7-11", "psa 95:7-11", "quotation",
                          "你們今日若聽他的話就不可硬著心"),
    SupplementaryCrossRef("heb 3:15", "psa 95:7-8", "quotation",
                          "不可硬著心"),
    # Heb 4 — Sabbath rest
    SupplementaryCrossRef("heb 4:4", "gen 2:2", "quotation",
                          "到第七日神歇了一切的工"),
    SupplementaryCrossRef("heb 4:3,5,7", "psa 95:11", "quotation",
                          "他們斷不可進入我的安息"),
    # Heb 5-7 — Melchizedek priesthood
    SupplementaryCrossRef("heb 5:5", "psa 2:7", "quotation",
                          "你是我的兒子我今日生你"),
    SupplementaryCrossRef("heb 5:6", "psa 110:4", "quotation",
                          "你是照著麥基洗德的等次永遠為祭司"),
    SupplementaryCrossRef("heb 7:1-2", "gen 14:18-20", "quotation",
                          "麥基洗德迎接亞伯拉罕"),
    SupplementaryCrossRef("heb 7:17,21", "psa 110:4", "quotation",
                          "照著麥基洗德的等次永遠為祭司"),
    # Heb 8 — New covenant
    SupplementaryCrossRef("heb 8:8-12", "jer 31:31-34", "quotation",
                          "我要與以色列家另立新約"),
    # Heb 10
    SupplementaryCrossRef("heb 10:5-7", "psa 40:6-8", "quotation",
                          "祭物和禮物是你不願意的"),
    SupplementaryCrossRef("heb 10:16-17", "jer 31:33-34", "quotation",
                          "我要將我的律法放在他們心上"),
    SupplementaryCrossRef("heb 10:37-38", "hab 2:3-4", "quotation",
                          "義人必因信得生"),
    # Heb 11 — Faith chapter allusions
    SupplementaryCrossRef("heb 11:3", "gen 1:1", "allusion",
                          "因著信我們知道諸世界是藉神話造成的"),
    SupplementaryCrossRef("heb 11:4", "gen 4:3-5", "allusion",
                          "亞伯因著信獻祭與神"),
    SupplementaryCrossRef("heb 11:5", "gen 5:24", "allusion",
                          "以諾因著信被接去"),
    SupplementaryCrossRef("heb 11:7", "gen 6:13-22", "allusion",
                          "挪亞因著信預備了方舟"),
    SupplementaryCrossRef("heb 11:8-10", "gen 12:1-4", "allusion",
                          "亞伯拉罕因著信蒙召出去"),
    SupplementaryCrossRef("heb 11:17-19", "gen 22:1-14", "allusion",
                          "亞伯拉罕因著信獻以撒"),
    # Heb 12
    SupplementaryCrossRef("heb 12:5-6", "pro 3:11-12", "quotation",
                          "我兒不可輕看主的管教"),
    SupplementaryCrossRef("heb 12:26", "hag 2:6", "quotation",
                          "再一次我不單要震動地還要震動天"),
    # Heb 13
    SupplementaryCrossRef("heb 13:5", "deu 31:6", "quotation",
                          "我總不撇下你也不丟棄你"),
    SupplementaryCrossRef("heb 13:6", "psa 118:6", "quotation",
                          "主是幫助我的我必不懼怕"),

    # ===================================================================
    # James (jas)
    # ===================================================================
    SupplementaryCrossRef("jas 2:23", "gen 15:6", "quotation",
                          "亞伯拉罕信神就算為他的義"),
    SupplementaryCrossRef("jas 2:8", "lev 19:18", "quotation",
                          "要愛人如己"),

    # ===================================================================
    # 1 Peter (1pe)
    # ===================================================================
    # 1 Pet 1 — Be holy
    SupplementaryCrossRef("1pe 1:16", "lev 19:2", "quotation",
                          "你們要聖潔因為我是聖潔的"),
    SupplementaryCrossRef("1pe 1:24-25", "isa 40:6-8", "quotation",
                          "凡有血氣的盡都如草惟有主的道是永存的"),
    # 1 Pet 2 — Living stones (THE KEY CROSS-REFS!)
    SupplementaryCrossRef("1pe 2:6", "isa 28:16", "quotation",
                          "在錫安放一塊石頭作為根基是寶貴的房角石"),
    SupplementaryCrossRef("1pe 2:7", "psa 118:22", "quotation",
                          "匠人所棄的石頭已作了房角的頭塊石頭"),
    SupplementaryCrossRef("1pe 2:8", "isa 8:14", "quotation",
                          "作了絆腳的石頭跌人的磐石"),
    SupplementaryCrossRef("1pe 2:9", "exo 19:5-6", "quotation",
                          "你們是被揀選的族類是有君尊的祭司"),
    SupplementaryCrossRef("1pe 2:10", "hos 2:23", "quotation",
                          "從前不是子民現在卻是神的子民"),
    # 1 Pet 2 — Suffering servant
    SupplementaryCrossRef("1pe 2:22", "isa 53:9", "quotation",
                          "他並沒有犯罪口裏也沒有詭詐"),
    SupplementaryCrossRef("1pe 2:24", "isa 53:5-6", "quotation",
                          "因他受的鞭傷你們得了醫治"),
    SupplementaryCrossRef("1pe 2:25", "isa 53:6", "quotation",
                          "你們從前好像迷路的羊"),
    # 1 Pet 3
    SupplementaryCrossRef("1pe 3:10-12", "psa 34:12-16", "quotation",
                          "主的眼看顧義人主的耳聽他們的呼求"),
    SupplementaryCrossRef("1pe 3:14-15", "isa 8:12-13", "quotation",
                          "不要怕人的威嚇也不要驚慌"),
    # 1 Pet 5
    SupplementaryCrossRef("1pe 5:5", "pro 3:34", "quotation",
                          "神阻擋驕傲的人賜恩給謙卑的人"),

    # ===================================================================
    # 2 Peter (2pe)
    # ===================================================================
    SupplementaryCrossRef("2pe 2:22", "pro 26:11", "quotation",
                          "狗所吐的他轉過來又吃"),

    # ===================================================================
    # Jude (jud)
    # ===================================================================
    SupplementaryCrossRef("jud 1:9", "zec 3:2", "allusion",
                          "主責備你吧"),

    # ===================================================================
    # Revelation (rev)
    # ===================================================================
    SupplementaryCrossRef("rev 1:7", "dan 7:13", "allusion",
                          "看哪他駕雲降臨"),
    SupplementaryCrossRef("rev 1:7", "zec 12:10", "allusion",
                          "連刺他的人也要看見他"),
    SupplementaryCrossRef("rev 1:13-16", "dan 10:5-6", "allusion",
                          "人子的形像"),
    SupplementaryCrossRef("rev 2:7", "gen 2:9", "allusion",
                          "生命樹"),
    SupplementaryCrossRef("rev 4:8", "isa 6:3", "allusion",
                          "聖哉聖哉聖哉"),
    SupplementaryCrossRef("rev 4:6-7", "ezk 1:5-10", "allusion",
                          "四活物的形像"),
    SupplementaryCrossRef("rev 5:5-6", "dan 7:13-14", "allusion",
                          "被殺的羔羊配得權柄"),
    SupplementaryCrossRef("rev 7:16-17", "isa 49:10", "allusion",
                          "不再飢不再渴"),
    SupplementaryCrossRef("rev 11:15", "dan 7:14,27", "allusion",
                          "世上的國成了我主基督的國"),
    SupplementaryCrossRef("rev 15:3-4", "exo 15:1-18", "allusion",
                          "摩西的歌"),
    SupplementaryCrossRef("rev 18:2", "isa 13:19-22", "allusion",
                          "巴比倫傾倒了"),
    SupplementaryCrossRef("rev 18:2-8", "jer 51:6-9,45", "allusion",
                          "巴比倫大城傾倒了"),
    # rev 19:1 → psa 118:1 and rev 20:4 → isa 65:17 are deleted (XREF-2): no
    # verse-level TSK support (scripts/tests/test_supp_defs_frozen.py DELETED).
    # Was rev 19:11-16 → dan 7:13-14, which no verse-level TSK supports (X2,
    # test_supp_defs_frozen.py RETARGETED); dan 2:47 萬神之神、萬王之主.
    SupplementaryCrossRef("rev 19:16", "dan 2:47", "allusion",
                          "萬王之王萬主之主"),
    SupplementaryCrossRef("rev 21:1", "isa 65:17", "quotation",
                          "我造新天新地"),
    SupplementaryCrossRef("rev 21:4", "isa 25:8", "quotation",
                          "神要擦去他們一切的眼淚"),
    SupplementaryCrossRef("rev 22:1-2", "gen 2:9-10", "allusion",
                          "生命樹和生命河"),
    SupplementaryCrossRef("rev 22:1", "ezk 47:1-12", "allusion",
                          "生命水的河"),
]
