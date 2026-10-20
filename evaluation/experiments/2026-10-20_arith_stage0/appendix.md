# 附錄：有序鏈算術 stage-0（harness 建置時寫入，尚無任何臂的生成）

規格：`prereg.md`。資料只在 store `reports/arith_stage0_20261020/`；本檔不含題目原文、經文、卡片文字或答案。王朝的種子 id 是 r4 層 id（括號內是參照層 ref_v2 id），創世記是 store gen_layer.json 的 id。

## 1. 題與 gold

| 題號 | 族 | 題型 | 國／章 | L | k | 種子 id | gold | 碰到的段 | nested | 推導行含 gold | T-canon 窗含齊依據節 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S5_01 | DYN | S5 | I | 3 | — | A03 拿答 / A08 以拉（參照層 I02 / I04） | 28 | I02-I04 | 是 | 是 | 是 |
| S5_02 | DYN | S5 | I | 3 | — | A10 暗利 / A12 亞哈謝（參照層 I06 / I08） | 36 | I06-I08 | 是 | 是 | 是 |
| S5_03 | DYN | S5 | I | 6 | — | A10 暗利 / A17 約哈斯（參照層 I06 / I11） | 93 | I06-I08 / I09-I11 | 否 | 是 | 否 |
| S5_04 | DYN | S5 | I | 5 | — | A11 亞哈 / A17 約哈斯（參照層 I07 / I11） | 81 | I06-I08 / I09-I11 | 否 | 是 | 否 |
| S5_05 | DYN | S5 | I | 4 | — | A12 亞哈謝 / A17 約哈斯（參照層 I08 / I11） | 59 | I06-I08 / I09-I11 | 否 | 是 | 是 |
| S5_06 | DYN | S5 | I | 4 | — | A14 約蘭 / A21 約阿施（參照層 I09 / I12） | 73 | I09-I11 | 否 | 是 | 是 |
| S5_07 | DYN | S5 | J | 5 | — | A01 羅波安 / A13 約蘭（參照層 J01 / J05） | 94 | J01-J03 / J04-J06 | 否 | 是 | 否 |
| S5_08 | DYN | S5 | J | 6 | — | A01 羅波安 / A15 亞哈謝（參照層 J01 / J06） | 95 | J01-J03 / J04-J06 | 否 | 是 | 否 |
| S5_09 | DYN | S5 | J | 3 | — | A20 亞瑪謝 / A25 約坦（參照層 J09 / J11） | 97 | J08-J10 / J11-J13 | 否 | 是 | 否 |
| S5_10 | DYN | S5 | J | 3 | — | A23 亞撒利雅 / A31 亞哈斯（參照層 J10 / J12） | 84 | J08-J10 / J11-J13 | 否 | 是 | 是 |
| S5_11 | DYN | S5 | J | 4 | — | A23 亞撒利雅 / A32 希西家（參照層 J10 / J13） | 113 | J08-J10 / J11-J13 | 否 | 是 | 否 |
| S5_12 | DYN | S5 | J | 6 | — | A23 亞撒利雅 / A34 亞們（參照層 J10 / J15） | 170 | J08-J10 / J11-J13 / J14-J16 | 否 | 是 | 否 |
| S5_13 | DYN | S5 | J | 4 | — | A25 約坦 / A33 瑪拿西（參照層 J11 / J14） | 116 | J11-J13 / J14-J16 | 否 | 是 | 是 |
| S5_14 | DYN | S5 | J | 5 | — | A25 約坦 / A34 亞們（參照層 J11 / J15） | 118 | J11-J13 / J14-J16 | 否 | 是 | 是 |
| S6_01 | S6 | S6 | J | — | — | A19 約阿施 / A20 亞瑪謝（參照層 J08 / J09） | 22 | J08-J10 | 是 | 是 | 是 |
| S6_02 | S6 | S6 | J | — | — | A25 約坦 / A31 亞哈斯（參照層 J11 / J12） | 21 | J11-J13 | 是 | 是 | 是 |
| S6_03 | S6 | S6 | J | — | — | A32 希西家 / A33 瑪拿西（參照層 J13 / J14） | 42 | J11-J13 / J14-J16 | 否 | 是 | 是 |
| S6_04 | S6 | S6 | J | — | — | A33 瑪拿西 / A34 亞們（參照層 J14 / J15） | 45 | J14-J16 | 是 | 是 | 是 |
| SYNC2_01 | SYNC | SYNC2 | I | — | 2 | A10 暗利（參照層 I06） | Y＝I08 亞哈謝；Z＝J04 約沙法 | I06-I08 | 是 | 是 | 是 |
| SYNC2_02 | SYNC | SYNC2 | I | — | 2 | A17 約哈斯（參照層 I11） | Y＝I13 耶羅波安；Z＝J09 亞瑪謝 | I09-I11 | 否 | 是 | 是 |
| SYNC2_03 | SYNC | SYNC2 | I | — | 2 | A21 約阿施（參照層 I12） | Y＝I14 撒迦利雅；Z＝J10 亞撒利雅 | — | 否 | 是 | 否 |
| SYNC2_04 | SYNC | SYNC2 | J | — | 2 | A01 羅波安（參照層 J01） | Y＝J03 亞撒；Z＝I01 耶羅波安 | J01-J03 | 是 | 是 | 是 |
| SYNC2_05 | SYNC | SYNC2 | J | — | 2 | A04 亞比央（參照層 J02） | Y＝J04 約沙法；Z＝I07 亞哈 | J01-J03 / J04-J06 | 否 | 是 | 否 |
| SYNC2_06 | SYNC | SYNC2 | J | — | 2 | A19 約阿施（參照層 J08） | Y＝J10 亞撒利雅；Z＝I13 耶羅波安 | J08-J10 | 是 | 是 | 否 |
| SYNC2_07 | SYNC | SYNC2 | J | — | 2 | A23 亞撒利雅（參照層 J10） | Y＝J12 亞哈斯；Z＝I18 比加 | J08-J10 / J11-J13 | 否 | 是 | 否 |
| SYNC2_08 | SYNC | SYNC2 | J | — | 2 | A25 約坦（參照層 J11） | Y＝J13 希西家；Z＝I19 何細亞 | J11-J13 | 是 | 是 | 是 |
| SYNC3_01 | SYNC | SYNC3 | I | — | 3 | A03 拿答（參照層 I02） | Y＝I05 心利；Z＝J03 亞撒 | I02-I04 | 否 | 是 | 是 |
| SYNC3_02 | SYNC | SYNC3 | I | — | 3 | A07 巴沙（參照層 I03） | Y＝I06 暗利；Z＝J03 亞撒 | I02-I04 / I06-I08 | 否 | 是 | 是 |
| SYNC3_03 | SYNC | SYNC3 | I | — | 3 | A09 心利（參照層 I05） | Y＝I08 亞哈謝；Z＝J04 約沙法 | I06-I08 | 否 | 是 | 是 |
| SYNC3_04 | SYNC | SYNC3 | I | — | 3 | A16 耶戶（參照層 I10） | Y＝I13 耶羅波安；Z＝J09 亞瑪謝 | I09-I11 | 否 | 是 | 否 |
| SYNC3_05 | SYNC | SYNC3 | I | — | 3 | A21 約阿施（參照層 I12） | Y＝I15 沙龍；Z＝J10 亞撒利雅 | — | 否 | 是 | 否 |
| SYNC3_06 | SYNC | SYNC3 | J | — | 3 | A01 羅波安（參照層 J01） | Y＝J04 約沙法；Z＝I07 亞哈 | J01-J03 / J04-J06 | 否 | 是 | 否 |
| SYNC3_07 | SYNC | SYNC3 | J | — | 3 | A19 約阿施（參照層 J08） | Y＝J11 約坦；Z＝I18 比加 | J08-J10 / J11-J13 | 否 | 是 | 否 |
| SYNC3_08 | SYNC | SYNC3 | J | — | 3 | A23 亞撒利雅（參照層 J10） | Y＝J13 希西家；Z＝I19 何細亞 | J08-J10 / J11-J13 | 否 | 是 | 否 |
| F1_01 | GEN | F1 | 創 5 | — | — | G05.01 塞特 / G05.04 瑪勒列 | 265 | G05.00-G05.02 / G05.02-G05.04 | 否 | 是 | — |
| F1_02 | GEN | F1 | 創 5 | — | — | G05.02 以挪士 / G05.05 雅列 | 225 | G05.02-G05.04 / G05.04-G05.06 | 否 | 是 | — |
| F1_03 | GEN | F1 | 創 5 | — | — | G05.02 以挪士 / G05.06 以諾 | 387 | G05.02-G05.04 / G05.04-G05.06 | 否 | 是 | — |
| F1_04 | GEN | F1 | 創 5 | — | — | G05.03 該南 / G05.05 雅列 | 135 | G05.02-G05.04 / G05.04-G05.06 | 否 | 是 | — |
| F1_05 | GEN | F1 | 創 5 | — | — | G05.03 該南 / G05.06 以諾 | 297 | G05.02-G05.04 / G05.04-G05.06 | 否 | 是 | — |
| F1_06 | GEN | F1 | 創 5 | — | — | G05.05 雅列 / G05.09 挪亞 | 596 | G05.04-G05.06 / G05.06-G05.08 | 否 | 是 | — |
| F1_07 | GEN | F1 | 創 11 | — | — | G11.00 閃 / G11.04 法勒 | 199 | G11.00-G11.02 / G11.02-G11.04 | 否 | 是 | — |
| F1_08 | GEN | F1 | 創 11 | — | — | G11.01 亞法撒 / G11.03 希伯 | 65 | G11.00-G11.02 / G11.02-G11.04 | 否 | 是 | — |
| F1_09 | GEN | F1 | 創 11 | — | — | G11.01 亞法撒 / G11.04 法勒 | 99 | G11.00-G11.02 / G11.02-G11.04 | 否 | 是 | — |
| F1_10 | GEN | F1 | 創 11 | — | — | G11.02 沙拉 / G11.06 西鹿 | 126 | G11.02-G11.04 / G11.04-G11.06 | 否 | 是 | — |
| F1_11 | GEN | F1 | 創 11 | — | — | G11.03 希伯 / G11.07 拿鶴 | 126 | G11.02-G11.04 / G11.04-G11.06 / G11.06-G11.08 | 否 | 是 | — |
| F1_12 | GEN | F1 | 創 11 | — | — | G11.06 西鹿 / G11.08 他拉 | 59 | G11.06-G11.08 | 是 | 是 | — |
| F3_01 | GEN | F3 | 創 11 | — | — | G11.03 希伯 | 67 | G11.00-G11.02 / G11.02-G11.04 | 否 | 是 | — |
| F3_02 | GEN | F3 | 創 11 | — | — | G11.04 法勒 | 101 | G11.00-G11.02 / G11.02-G11.04 | 否 | 是 | — |
| F3_03 | GEN | F3 | 創 11 | — | — | G11.06 西鹿 | 163 | G11.00-G11.02 / G11.02-G11.04 / G11.04-G11.06 | 否 | 是 | — |
| F3_04 | GEN | F3 | 創 11 | — | — | G11.08 他拉 | 222 | G11.00-G11.02 / G11.02-G11.04 / G11.04-G11.06 / G11.06-G11.08 | 否 | 是 | — |
| F5_01 | GEN | F5 | 創 5 | — | — | G05.03 該南 / G05.07 瑪土撒拉 | 548 | G05.02-G05.04 / G05.04-G05.06 / G05.06-G05.08 | 否 | 是 | — |
| F5_02 | GEN | F5 | 創 11 | — | — | G11.05 拉吳 / G11.08 他拉 | 148 | G11.04-G11.06 / G11.06-G11.08 | 否 | 是 | — |

## 2. 題數、段與旗標

- 題數：DYN S5 14；S6 S6 4；SYNC SYNC2 8；SYNC SYNC3 8；GEN F1 12；GEN F3 4；GEN F5 2；共 52 題。
- DYN 跨段 12/14 題（§3.5 下限 10），nested 2 題。
- GEN 跨段 17/18 題（§3.5 下限 7），nested 1 題。
- 候選池（排除後）：{'S5': {'I3': 8, 'I4': 5, 'I5': 3, 'I6': 2, 'J3': 11, 'J4': 9, 'J5': 7, 'J6': 5}, 'SYNC': {'k2': 16, 'k3': 13, 'answer_kings': 9}, 'F1': {'c11': 18, 'c5m': 14, 'c5a': 6}, 'F3': 7, 'F5': {'ch5': 27, 'ch11': 7}}；抽樣 seed 20261020。
- 題目旗標：
  - S5_10：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - S5_11：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - S5_12：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - SYNC2_02：耶羅波安 (I13) has a same-kingdom homonym in r4 and ref_v2
  - SYNC2_03：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - SYNC2_04：耶羅波安 (I01) has a same-kingdom homonym in r4 and ref_v2
  - SYNC2_06：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father；耶羅波安 (I13) has a same-kingdom homonym in r4 and ref_v2
  - SYNC2_07：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - SYNC3_04：耶羅波安 (I13) has a same-kingdom homonym in r4 and ref_v2
  - SYNC3_05：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - SYNC3_08：ref_v2 lists another same-kingdom king under 亞撒利雅 (J10); r4 does not, so it is named without a father
  - F1_03：同名人物，題目以不在路徑上的親屬名辨識（§3.4）
  - F1_05：同名人物，題目以不在路徑上的親屬名辨識（§3.4）
  - F1_11：同名人物，題目以不在路徑上的親屬名辨識（§3.4）

## 3. SYNC 入選題的答案王分佈

- 答案王（Z，配額依層 id 計，每位至多 2 題）：I01 耶羅波安 ×1；I07 亞哈 ×2；I13 耶羅波安 ×1；I18 比加 ×2；I19 何細亞 ×2；J03 亞撒 ×2；J04 約沙法 ×2；J09 亞瑪謝 ×2；J10 亞撒利雅 ×2（9 位）
- 第 k 位王（Y）：I05 心利 ×1；I06 暗利 ×1；I08 亞哈謝 ×2；I13 耶羅波安 ×2；I14 撒迦利雅 ×1；I15 沙龍 ×1；J03 亞撒 ×1；J04 約沙法 ×2；J10 亞撒利雅 ×1；J11 約坦 ×1；J12 亞哈斯 ×1；J13 希西家 ×2（12 位）
- k：k＝2 8 題；k＝3 8 題

## 4. K0（CPU，叫 Ollama 前）

- 整體：通過；輸入釘值問題 無；實驗 A 凍結檔問題 無；出題檢查 通過。
- K0-1（ref_v2 與 r4 欄位一致、王朝 gold 雙路）：是，34 題，問題 0 題。
- K0-2（創世記層、創世記 gold 雙路）：是；beget＋remain＝total 9/9、子名 17/17、挪亞無 remain 是；列數 {'nodes': 19, 'beget': 19, 'remain': 17, 'total': 11, 'derived': 8}；gold 問題 0 題。
- K0-3（推導行）：王朝 a＝34/34、矛盾 0 題；創世記 a＝18/18、矛盾 0 題（含壽數上限）。
- K0-4（計分器）：合成測試 194 passed（test_arith_stage0_keys.py, test_arith_stage0_score.py）；各題 G 推導行照抄 114 例、不符 0；A／A_confirm 記錄重算 66 筆、75 鍵，原本對的變錯 0、記錄分數下降 0、變對 9（{'QJ1s2a2': 8, 'QJ3s2a1': 1}）。
- K0-5（截斷 smoke）：harness、本附錄與 K0 commit 之後才跑，是第一次叫 Ollama；結果在 store smoke/smoke.json。
- K0-6（字數與列）：是；各臂附加字數最大 {'G': 669, 'T-rows': 365, 'T-canon': 900, 'B0': 0, 'B0p': 0}（上限 900）；問題 0 題、job 問題 無。

F3 回聲案例（K0-4，照 §5 計，不改規則）：

| 案例 | 答案行（自造，甲、丁是假名） | 取到的值 | 分數 |
|---|---|---|---|
| anchor_first_segment | 甲生於洪水後2年;丁在洪水之後37年出生 | 2 | 0 |
| anchor_same_segment | 甲生於洪水後2年,丁在洪水之後37年出生 | 37 | 1 |
| anchor_after_answer | 丁在洪水之後37年出生,甲生於洪水後2年 | 2 | 0 |
| anchor_after_answer_because | 丁在洪水之後37年出生,因為甲生於洪水後2年 | 37 | 1 |
| anchor_in_brackets | 丁在洪水之後37年出生(甲生於洪水後2年) | 37 | 1 |
| anchor_in_sum | 2+30+5=37年 | 37 | 1 |
| anchor_total_word | 洪水後2年加35年,共37年 | 37 | 1 |

## 5. 臂與 prompt

- job：588 次；{'DYN|B0': 42, 'DYN|G': 42, 'DYN|T-canon': 42, 'DYN|T-rows': 42, 'GEN|B0': 54, 'GEN|B0p': 18, 'GEN|G': 54, 'GEN|T-rows': 54, 'S6|B0': 12, 'S6|G': 12, 'S6|T-canon': 12, 'S6|T-rows': 12, 'SYNC|B0': 48, 'SYNC|G': 48, 'SYNC|T-canon': 48, 'SYNC|T-rows': 48}。
- G 附加字數：平均 392.3、最大 669（52 題）。
- T-rows 附加字數：平均 216.7、最大 365（52 題）。
- T-canon 附加字數：平均 878.3、最大 900（34 題）。
- user prompt 最大 2093 字；刪列 0、刪行 0。
- T-canon 窗含齊依據節：DYN 7/14；S6 4/4；SYNC 7/16（GEN 不跑 T-canon，§4）。

## 6. sha256

| 檔 | sha256 |
|---|---|
| store gen_layer.json | `46d87abb29000d1210d0ee6fd5e045f7bf6ac08a2f1c034374a61c5e9c1aead5` |
| store items.json | `f873b886aa16d45f6ad81de382de5f687ea2ab2c2c0f891011fa88abc4e6571b` |
| store cards.json | `62078346c4827ed5bf7f12413bcefcd55f76fa7906480ee369fedc514b3ccf3d` |
| store jobs.json | `8b927055fc025238fc90674bceabb7787373dbae2ef7ce3f8e37a7b570bf7445` |
| store arms_meta.json | `d35813c6862864107b612c0f191cc3e0dcaf87ddd117f7322654962bb509b422` |
| store k0.json | `409f69fcc31a9ec17f502a344e2f1e6a8d0744b15f3c1b95d100ff51c5e68bb0` |
| K0-4 合成測試 test_arith_stage0_keys.py（k0.json） | `fa76f4ff64db1a2be894c562075c46c3fb29ccca28549a7a1fbf96f3ec74529f` |
| K0-4 合成測試 test_arith_stage0_score.py（k0.json） | `4e1c7d0c10f8b20c1e3fbdfb7d1ccdf8418469fc28c70b7139b7d306942b4054` |
| 全部 prompt（job_id, system, user 依序） | `8892f30660291728c8e7137a888c8190890e65aae94d8c11e4604278ffd183ad` |
| SYSTEM_PROMPT | `f58c03fa9dfbdfbded1c4c6a01c72c5129078f54cdade009299448bb28ddfa54` |
| USER_TEMPLATE | `677e91e5d33a0791a67007785f5993db8f62e4241bb62378ca639891f44328b8` |
| ref_layer_v2.json | `e39e04f227f1b558300dd85662d7dbdaf76e73252ddf732ef1f6aab96cec576a` |
| r4 regnal_layer.json | `252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11` |
| 文字層 digest | `247eafe44b02ed27f49d244ba525d02b87bd7c8402ca03ce38cb97972a12e75a` |
| powerA_strong.py | `78d67cb84da4be052329113f97ca91c1d97af4521d88afaac9496ebe1b03d500` |
| harness analyze_x.py | `cbd13540dac71565911b732eaf11426e2c0ccf9cda0fc65eff8037813ebf6ee8` |
| harness appendix_x.py | `0d10b337e7612296f6220d777e9d363cbc5997f6abdd0d34ec0fe39a5814b4aa` |
| harness arms_x.py | `4a083b4280c3fcffcfe32cb8345eb835caabb4bd7787e443ed881235c656c616` |
| harness engine_x.py | `57495aed05c4914eca0b8ee16900e169d76c46151c227e3ba86ef8719bc38fa2` |
| harness gen_layer.py | `b4d5fedb1b4c77a95778de14b628716835640cf066cfb88500b80c5685c12db8` |
| harness items_x.py | `055fe22635b0536089a571b8dff495c20300affd3be62c4cad4388da0a4b20fe` |
| harness keys_x.py | `ef03715048c9f8033b4032e17f789012b7b79b604d855dd911d1697a268aef6d` |
| harness power_x.py | `e5396d62e285ce03b881a9f5ea600fd038c8fbd486b93949e1d180fa1b0efcf1` |
| harness prereg.md | `4c64f946e2c9eec5d3bb3c98f5291c7e5bc2949bea01531bfb2b62b5987c04b0` |
| harness run_x.py | `5c8181ab5688d6fa1c9712527ae5c9287b80361e353a92172d49995b02cd08ee` |
| harness score_x.py | `6722a33bfd02886decc3fd5cb813bdf6c6149c531413f0d3d0a4917cff18bdbf` |
| harness tests/test_arith_stage0_analyze.py | `9ef1f1b3006996ab6880b8cd8b73ad50847f793b5906d0c31bf294c3c25e2392` |
| harness tests/test_arith_stage0_appendix.py | `56019c65f80543d77162d5a74a26b71d84a284a90535d50cf9e6c61974036161` |
| harness tests/test_arith_stage0_arms.py | `42778a4187af9936a50b3ed48d12c34811c8f2c451181f4e5006487f3ef4c2a7` |
| harness tests/test_arith_stage0_engine.py | `c97e3f3cb7543a8b6afe44c8d57250626ba9e28a2347e4e27a95ab1ab004f3e3` |
| harness tests/test_arith_stage0_gen_layer.py | `5887978304ab96b091de1216d8c6db069d4e12dec211b3f752c83f85c7aab2c8` |
| harness tests/test_arith_stage0_items.py | `7cb902ecf672688ceee0cd728a78a9d639970279b40ccbe582db0b953073cd5d` |
| harness tests/test_arith_stage0_keys.py | `fa76f4ff64db1a2be894c562075c46c3fb29ccca28549a7a1fbf96f3ec74529f` |
| harness tests/test_arith_stage0_power.py | `02fe52a22d133c36b78a1b8a346e52017d00c340c7beebc887b69359e02ca6d8` |
| harness tests/test_arith_stage0_run.py | `3f3374f2b278f60bdcd73506b076e58173d8f05e85cb73666b1da9b3705ee1ba` |
| harness tests/test_arith_stage0_score.py | `4e1c7d0c10f8b20c1e3fbdfb7d1ccdf8418469fc28c70b7139b7d306942b4054` |
| harness units_x.py | `ee74895d8478dc123a98fb389ffd20508a4ebf3808f243e5a7f3b12f2c31cb75` |
| harness x_common.py | `def83e663c3111fc590b23b4a7926f4fb35b62d30aeda2c2aeacbf31eabafcfb` |
| 實驗 A cards_common.py | `ae9dc16ceedad750a0ea0e2da0ec4db8098dfa4f58ae32820e84a567ed56acef` |
| 實驗 A A/a_common.py | `d2b39cc997a9e89a2e048337fb3c3d1dc016049d761b0faf064d5ae84dd58bf4` |
| 實驗 A A/keys_a.py | `73c9f217acc0a6d4f0c8c1f4342580bd656f41d526e4c3ab38485450ef815f32` |
| 實驗 A A/score_a.py | `a75039eddc649feeaf847501318082dfcf567cc4ec3e3e6fe16c8cf03b8bec94` |
| 實驗 A A/tcanon.py | `610d1b39abf43b505f41c044980e04d3e279bb56a2c8ce65750e995c7e3105c2` |
| 實驗 A A/regnal.py | `ce49df68b1b4ee9cb2204d7ee806fbdb3b0e374f80fbd3015d31bbfb212df710` |
| 實驗 A A/confirm/c_common.py | `c48288c176152e1fd1782478e908fcbbfa497536717ea9ade302cf5ce6042977` |
| 實驗 A A/confirm/arms_c.py | `5a9c6db48d88c5eefbf10df9c660d9f8aa682aece3b95efc85eae13b8316bdc7` |
| backend backend/utils/regnal/engine.py | `a04d58774ee4fabbf4278f19f175d53eabfcb9e314cbdfe6363e9921e4864a95` |
| backend packages/ragcommon/regnal.py | `ada1a5a1d12517e677d743d7af40607444343275f730c9ee0103741743e0d40b` |
