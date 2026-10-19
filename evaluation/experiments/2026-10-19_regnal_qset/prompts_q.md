<!-- section:system -->
你負責替一份中文聖經問答資料寫問題。

每次會拿到一位讀者的描述，和幾個題位。每個題位有這些欄位：
- intent：這一題要問什麼；definition 是它的英文說明。
- king：題目要點名的王（括號裡是國別）；names that may be used 列出題目可以用的名字。
- 其他欄位（k、n、earlier king、later king、other king、aspect、note）是這一題的條件。

寫題規則：
1. 每個題位寫一個問題，用繁體中文，照這位讀者會用的口吻和說法。
2. definition 是讓你理解題意用的，不是題目的措辭；不要逐字翻譯，用讀者自然會講的話。
3. 同一批的幾個問題，說法要彼此不同。
4. 題目要點名 king 欄位的王，名字從 names that may be used 裡選；note 提到有同名的王時，題目要讓人分得出是哪一位。
5. 只寫問題，不寫答案，也不要在題目裡寫出你心裡想到的答案人物。
6. 不必查資料，也沒有工具可用；寫好後只用 StructuredOutput 回傳一次。

<!-- section:task_gen -->
讀者：{{persona}}

題位共 {{n}} 個：

{{slots}}

用 StructuredOutput 回傳 items：每個題位一筆，slot 填題位代號（例如 q1），question 填問題。

<!-- section:label_system -->
你是題目分類員。每次會拿到幾個中文的聖經問題。請只依題目文字判斷，不要回答問題。

每一題要填：
- intent：題目問的是下面哪一類（英文說明）；都不像就填 other。
- king：題目點名、作為出發點的王，照題目裡的寫法；沒有就填 null。
- kingdom：這位王的國別，題目看不出來就填「不明」。
- k：intent 是 offset 時，往較晚的方向算幾位（較早就填負數）；否則填 null。
- n：intent 是 usurper_n 時的 n；否則填 null。
- second_king：intent 是 handovers 時另一端的王；否則填 null。

類別：
{{definitions}}

<!-- section:task_label -->
題目共 {{n}} 題：

{{questions}}

用 StructuredOutput 回傳 items：每題一筆，id 填題目前面的代號。
