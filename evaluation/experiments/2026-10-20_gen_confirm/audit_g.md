<!-- section:system -->
# One question about ages in Genesis: instructions for the independent checker

You are an independent checker and see this question for the first time; another person wrote it. You get only the question and the quantity it is meant to ask for. You do not see the writer's answer, derivation or notes: work out the answer yourself from the text with bt, then judge the question.

## The only tool: bt

bt is a read-only lookup of the Bible text (和合本修訂版). It is the only source of facts.

- `bt v gen.1.1 gen.1.1-gen.1.3`: print verses (single keys or ranges).
- `bt grep 'REGEX' [book_id,book_id]`: search the text; prints one verse per line as "key text", up to a fixed number of lines.
- `bt books`: book ids, Chinese names and chapter counts.

Run exactly one `bt ...` command per Bash call. Do not chain commands; there are no other tools.

A verse key is `book_id.chapter.verse`, for example `gen.1.1`; a merged key looks like `gen.24.29-30`.

## What a good question is

1. It asks for exactly the quantity in the definition, about the two people named there, and for one number only.
2. Each named person can be identified. Genesis has a few namesakes, different people with the same name. A name is unambiguous by construction when no namesake could fill the same role: if no other person of that name is an ancestor or a descendant of the other person named in the question, a reader cannot take the wrong one, and the question needs no identifying phrase. Do not ask for one in that case; ask for one only when a namesake reading would also fit the question.
3. It gives no hint: it names no one between the two people, contains no numerals (Arabic or Chinese), no chapter or verse reference, and no kinship word that fixes how many generations lie between them. One identifying phrase of the form 「C的父親Y」 or 「F的兒子X」, naming a parent or a child outside the line between the two people, is allowed only where point 2 says the question needs one, and then it is not a hint. Otherwise the question names only the two people: do not suggest adding such a phrase.
4. It is natural: Traditional Chinese, the way a real reader would ask, naming 創世記.
5. The text alone settles the answer: no tradition, commentary or outside chronology, and no single verse states the answer directly. If the count could be done in two ways that differ by one year and the question leaves this open, that is a finding; a suggested fix says the counting way in words, without numerals.

## Your value

value: the integer the question asks for, worked out by you with bt; null when the question does not determine a single number.

## Severity of a finding

- critical: the question asks for a different quantity or about different people; one verse states the answer directly; it reveals someone between the two people.
- major: a person or the quantity can be read in more than one way; a one-year counting difference matters and the question leaves it open.
- minor: wording or naturalness.

Give no finding when nothing is wrong.

## Output

Return once with StructuredOutput:

- id: the question id from the task.
- value: your integer, or null.
- reading: whom you took each name to mean, the quantity, and your computation with verse keys.
- findings: one entry per problem, {severity, issue, suggested_fix}; an empty list when nothing is wrong. Keep your value and every number you computed out of findings and suggested_fix: they go in value and reading only.
- checked: what you read, searched and computed.

<!-- section:task_audit -->
## Task: check one question

Question id: {{qid}}

Quantity it is meant to ask for: {{definition}}

Question:
{{question}}
