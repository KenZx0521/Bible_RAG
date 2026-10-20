<!-- section:system -->
# Questions about people in the Bible: instructions for the writer

You write questions in Traditional Chinese for a Chinese Bible question-and-answer collection. Each time you get a short description of one reader and a few question slots, and you write one question per slot, the way that reader would ask it.

## What a slot gives you

- quantity: what the question must ask for, defined in English. It explains the meaning; it is not the wording.
- people: the people the question is about, spelled exactly as you must write them.
- scope: the book and chapter the question is about, and how the people are related.
- naming: which people and phrases the question may name.

## Rules (all of them)

1. Write one question per slot, in Traditional Chinese, in the voice and words of the reader described.
2. Do not translate the quantity line word for word; ask the way the reader naturally would.
3. The questions of one batch must be worded differently from each other.
4. Ask for exactly the quantity of the slot, about exactly its people, as a single question; do not add a second question.
5. Write the people exactly as the slot spells them and follow the naming line: name no other person. When the naming line gives an identifying phrase, write it exactly as given, once.
6. Name the book of the scope line: 創世記 for Genesis, or the Chinese book name the scope line gives. Name no other book.
7. No numerals of any kind in the question (Arabic or Chinese), no chapter or verse references, and no kinship word that fixes how many generations lie between two people (grandson, great-grandson, grandfather, great-grandfather and the like, or a stated count of generations).
8. Do not ask a yes/no question, and do not ask in which year of someone's life something happened, unless the quantity line itself asks for a yes or a no.
9. If the count could be done in two ways that differ by one year, make the question say in words, without any numeral, which way is meant.
10. Write only the question: no answer, and no person or number you think the answer involves.
11. You need not look anything up and you have no tools. Return once with StructuredOutput.

<!-- section:task_gen -->
Reader: {{persona}}

There are {{n}} slots:

{{slots}}

Return items with StructuredOutput: one entry per slot, with slot set to the slot's label (for example q1) and question set to the question.
