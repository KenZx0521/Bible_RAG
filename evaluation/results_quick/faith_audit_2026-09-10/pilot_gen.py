#!/usr/bin/env python
"""
Generator-side pilot (no model change): regenerate a handful of real-error cases with
(v1) the production SYSTEM_PROMPT and (v2) a prompt with grounding rules, using the
production model (gemma4:e4b-it-q8_0, temperature 0.1, same context builder).
Then judge each answer (stored v1 / regenerated v1 / v2) with hdr_zh faithfulness
and answer_coverage, so the trade-off is visible.
"""
import asyncio, json, os, sys, time
import httpx

SP = '/tmp/claude-1001/-home-kenzx0521-Bible-RAG/bf0f2dab-e373-4e67-94f3-73544818e90d/scratchpad'
sys.path.insert(0, SP)
import refaith  # noqa: E402  (sets cwd to evaluation/, sys.path)
from refaith import build_hdr_contexts, ZhNLIPrompt, settings  # noqa: E402
import asyncpg  # noqa: E402
from langchain_ollama import ChatOllama  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402
from ragas.metrics._faithfulness import StatementGeneratorPrompt, StatementGeneratorInput, NLIStatementInput  # noqa: E402
from src.metrics.coverage_eval import _PROMPT_TEMPLATE, _parse_verdicts, _VERDICT_SCORE  # noqa: E402
from src.llm import judge_completion  # noqa: E402

GEN_MODEL = 'gemma4:e4b-it-q8_0'
GEN_TEMP = 0.1
GEN_MAX_TOKENS = 10000
OUT = f'{SP}/pilot_results.json'

QIDS = [q for q in os.environ.get('PILOT_QIDS','').split(',') if q] or [
    'GENERAL_BIBLE_QUESTION_039', 'GENERAL_BIBLE_QUESTION_071', 'GENERAL_BIBLE_QUESTION_081',
    'GENERAL_BIBLE_QUESTION_077', 'PERSON_QUESTION_061', 'EVENT_QUESTION_068', 'VERSE_LOOKUP_090',
    'GENERAL_BIBLE_QUESTION_020', 'EVENT_QUESTION_033', 'PERSON_QUESTION_077',
    'VERSE_LOOKUP_017', 'VERSE_LOOKUP_030',
]

SYSTEM_PROMPT_V1 = """你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」中的資訊來回答，禁止使用經文以外的任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）
3. 將相關經文內容整理成連貫的回答
4. 不要加入經文中沒有提到的推論、解讀或額外資訊
5. 回答使用繁體中文"""

SYSTEM_PROMPT_V2 = """你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」中的資訊來回答，禁止使用經文以外的任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）；出處只能取自各段落標頭所標示的書卷與章節
3. 將相關經文內容整理成連貫的回答
4. 不要加入經文中沒有提到的推論、解讀或額外資訊；不要補充段落中沒有出現的人名、地名、數字或神學術語
5. 若問題所需的某卷書、某段記載或某個事件不在提供的段落中，要明確寫出「提供的經文段落中沒有 X 的記載」，不可用其他段落代替，也不可推測其內容
6. 比較、順序或先後次序類的問題，先逐段核對每個段落的內容再下結論，結論必須與你列出的細節一致
7. 引述某人的話或行動時，必須依照段落中實際記載的人物，不可張冠李戴
8. 回答使用繁體中文"""

CONTEXT_TEMPLATE = """以下是提供的經文段落（你只能使用這些內容來回答）：

{context}

---

嚴格根據以上經文段落的內容，回答以下問題。不要添加經文中沒有的資訊：
{question}"""


async def generate(system_prompt, question, context):
    prompt = CONTEXT_TEMPLATE.format(context=context, question=question)
    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json={
            "model": GEN_MODEL,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": GEN_TEMP, "num_predict": GEN_MAX_TOKENS},
        })
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


async def faith_zh(llm, sg, nli, question, answer, hdr_ctx):
    stmts = (await sg.generate(llm=llm, data=StatementGeneratorInput(question=question, answer=answer))).statements
    if not stmts:
        return None, []
    ctx = f"【使用者問題】{question}\n\n【經文段落】\n" + "\n\n".join(hdr_ctx)
    out = await nli.generate(llm=llm, data=NLIStatementInput(context=ctx, statements=stmts))
    verdicts = [{'statement': s.statement, 'verdict': int(bool(s.verdict)), 'reason': s.reason} for s in out.statements]
    return (sum(v['verdict'] for v in verdicts) / len(verdicts) if verdicts else None), verdicts


async def coverage(question, points, answer):
    if not points or not answer.strip():
        return None
    pb = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    prompt = _PROMPT_TEMPLATE.replace("<<QUESTION>>", question).replace("<<POINTS>>", pb).replace("<<ANSWER>>", answer)
    raw = await judge_completion(prompt, max_tokens=8192, temperature=0.0)
    v = _parse_verdicts(raw, len(points))
    return None if v is None else sum(_VERDICT_SCORE[x] for x in v) / len(v)


async def main():
    raw = {x['question_id']: x for x in json.load(open('results_graph/raw_responses.json'))}
    gt = json.load(open('../ground_truth.json'))
    items = gt if isinstance(gt, list) else gt.get('questions', gt.get('items', []))
    gtm = {x['question_id']: x for x in items}
    results = json.load(open(OUT)) if os.path.exists(OUT) else {}

    pool = await asyncpg.create_pool(host=settings.postgres_host, port=settings.postgres_port, database=settings.postgres_db,
                                     user=settings.postgres_user, password=settings.postgres_password, min_size=1, max_size=2)
    llm = LangchainLLMWrapper(ChatOllama(model=settings.eval_ollama_model, base_url=settings.ollama_base_url, temperature=0.0,
                                         num_predict=8192, num_ctx=16384, top_p=0.9, reasoning=False, keep_alive="60m"),
                              run_config=RunConfig(timeout=1800, max_retries=1, max_wait=30))
    sg, nli = StatementGeneratorPrompt(), ZhNLIPrompt()

    for qid in QIDS:
        if qid in results and all(k in results[qid] for k in ('v1_stored', 'v1_regen', 'v2')):
            continue
        r = raw[qid]; q = r['question']; points = gtm[qid].get('expected_answer_points') or []
        hdr_ctx = await build_hdr_contexts(pool, r)
        context = "\n\n".join(hdr_ctx)
        rec = results.setdefault(qid, {'question': q})
        t0 = time.time()
        answers = {'v1_stored': r['rag_answer']}
        answers['v1_regen'] = await generate(SYSTEM_PROMPT_V1, q, context)
        answers['v2'] = await generate(SYSTEM_PROMPT_V2, q, context)
        print(f"[pilot] {qid} generated ({time.time()-t0:.0f}s)", flush=True)
        for k, a in answers.items():
            try:
                f, verd = await faith_zh(llm, sg, nli, q, a, hdr_ctx)
            except Exception as e:
                f, verd = None, [{'error': repr(e)[:200]}]
            try:
                c = await coverage(q, points, a)
            except Exception as e:
                c = None
            rec[k] = {'answer': a, 'faith_zh': f, 'coverage': c, 'verdicts': verd}
            print(f"[pilot] {qid} {k}: faith_zh={f} cov={c} len={len(a)}", flush=True)
        json.dump(results, open(OUT, 'w'), ensure_ascii=False, indent=1)
    await pool.close()
    print("[pilot] DONE", flush=True)


if __name__ == '__main__':
    asyncio.run(main())
