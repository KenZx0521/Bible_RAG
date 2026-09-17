#!/usr/bin/env python
"""
Re-score RAGAS faithfulness under controlled conditions with statement-level logging.

Conditions (NLI step only; statements are generated once per sample and shared):
  A  orig    : contexts exactly as stored in raw_responses.json (headerless, verse/pericope id collision)
  B  hdr     : contexts rebuilt as the generator saw them ([i] 書卷 第N章 - 標題 (節)) + collision fix
  C  hdr_zh  : hdr contexts + question shown to judge + zh-TW domain-adapted NLI instruction/examples

Judge: same model as the official run (gemma4:26b-a4b-it-q8_0 via ollama), greedy.
Output: JSONL in scratchpad (one line per qid x condition), resumable.
"""
import asyncio, json, os, random, sys, time

EVAL_ROOT = '/home/kenzx0521/Bible_RAG/evaluation'
SP = '/tmp/claude-1001/-home-kenzx0521-Bible-RAG/bf0f2dab-e373-4e67-94f3-73544818e90d/scratchpad'
sys.path.insert(0, EVAL_ROOT)
os.chdir(EVAL_ROOT)

import asyncpg
from langchain_ollama import ChatOllama
from ragas.llms import LangchainLLMWrapper
from ragas.run_config import RunConfig
from ragas.metrics._faithfulness import (
    StatementGeneratorPrompt, StatementGeneratorInput,
    NLIStatementPrompt, NLIStatementInput, NLIStatementOutput, StatementFaithfulnessAnswer,
)
from src.config import settings
from src.content_fetcher import _fetch_single_verse, _fetch_verse_range

OUT = f'{SP}/refaith_results.jsonl'
STMT_CACHE = f'{SP}/refaith_statements.json'
CONDITIONS = [c for c in os.environ.get('CONDITIONS', 'orig,hdr,hdr_zh').split(',') if c]
LIMIT = int(os.environ.get('LIMIT', '0'))
N_CONTROL = int(os.environ.get('N_CONTROL', '40'))


class ZhNLIPrompt(NLIStatementPrompt):
    instruction = (
        "你的任務是根據給定的經文段落（context），逐條判斷陳述（statements）是否忠於經文。"
        "若陳述能由經文直接支持或合理推得，verdict=1；若陳述加入了經文中沒有的事實、或與經文矛盾，verdict=0。判斷準則：\n"
        "1. 段落標頭（例如「[1] 約翰福音 第3章 - 耶穌與尼哥德慕 (16節)」）是經文的一部分；陳述中的書卷、章、節出處只要與標頭相符即視為有支持。\n"
        "2. 陳述若只是複述「使用者問題」中已給定的前提（例如問題已指明說話者、對象、書卷或經文位置），不視為捏造。\n"
        "3. 標題、引導句、格式性片段（如「耶穌的解釋：」）以及對「所提供經文是否包含某內容」的說明，不是事實宣稱；只要描述正確就給 verdict=1。\n"
        "4. 針對問題所要求的歸納、比較、分階段整理，只要各組成事實均出自經文即 verdict=1；若引入經文沒有的人物、地點、事件、數字，或錯置歸屬（把甲的事說成乙），verdict=0。\n"
        "5. 對經文的意譯、白話重述或同義轉換視為有支持。\n"
        "請以 JSON 格式輸出。"
    )
    examples = [
        (
            NLIStatementInput(
                context=(
                    "【使用者問題】根據約翰福音20:29，耶穌對多馬說什麼樣的人有福？\n\n"
                    "【經文段落】\n[1] 約翰福音 第20章 - 耶穌向多馬顯現 (29節)\n"
                    "29. 耶穌對他說：「你因看見了我才信；那沒有看見就信的有福了。」"
                ),
                statements=[
                    "根據約翰福音第20章第29節，耶穌對多馬說話。",
                    "耶穌說那沒有看見就信的人有福了。",
                    "多馬後來到印度傳道。",
                    "這句話是保羅對多馬說的。",
                ],
            ),
            NLIStatementOutput(statements=[
                StatementFaithfulnessAnswer(statement="根據約翰福音第20章第29節，耶穌對多馬說話。", reason="出處與段落標頭相符；「多馬」是使用者問題已給定的對象，且經文記載耶穌對他說話。", verdict=1),
                StatementFaithfulnessAnswer(statement="耶穌說那沒有看見就信的人有福了。", reason="經文明載「那沒有看見就信的有福了」。", verdict=1),
                StatementFaithfulnessAnswer(statement="多馬後來到印度傳道。", reason="經文段落完全沒有提到印度或傳道，屬經文以外的資訊。", verdict=0),
                StatementFaithfulnessAnswer(statement="這句話是保羅對多馬說的。", reason="經文明載說話者是耶穌，陳述錯置歸屬。", verdict=0),
            ]),
        ),
        (
            NLIStatementInput(
                context=(
                    "【使用者問題】亞拿尼亞和撒非喇犯了什麼罪？結局如何？\n\n"
                    "【經文段落】\n[1] 使徒行傳 第5章 - 亞拿尼亞和撒非喇 (1-11節)\n"
                    "1 有一個人，名叫亞拿尼亞，同他的妻子撒非喇賣了田產， 2 把價銀私自留下幾分，他的妻子也知道，其餘的幾分拿來放在使徒腳前。 "
                    "3 彼得說：「亞拿尼亞！為甚麼撒但充滿了你的心，叫你欺哄聖靈，把田地的價銀私自留下幾分呢？」 "
                    "5 亞拿尼亞聽見這話，就仆倒，斷了氣；聽見的人都甚懼怕。 6 有些少年人起來，把他包裹，抬出去埋葬了。"
                ),
                statements=[
                    "他們的結局是：",
                    "亞拿尼亞和撒非喇私自留下部分賣田產的價銀（使徒行傳 第5章 2節）。",
                    "亞拿尼亞聽見彼得的話就仆倒斷了氣（使徒行傳 第5章 5節）。",
                    "撒非喇被會眾用石頭打死。",
                    "提供的經文段落沒有提到他們埋葬的地點。",
                ],
            ),
            NLIStatementOutput(statements=[
                StatementFaithfulnessAnswer(statement="他們的結局是：", reason="這是引導句，不是事實宣稱。", verdict=1),
                StatementFaithfulnessAnswer(statement="亞拿尼亞和撒非喇私自留下部分賣田產的價銀（使徒行傳 第5章 2節）。", reason="第2節明載，且出處與標頭相符。", verdict=1),
                StatementFaithfulnessAnswer(statement="亞拿尼亞聽見彼得的話就仆倒斷了氣（使徒行傳 第5章 5節）。", reason="第3節是彼得說話，第5節記載他仆倒斷氣。", verdict=1),
                StatementFaithfulnessAnswer(statement="撒非喇被會眾用石頭打死。", reason="經文沒有記載用石頭打死，屬捏造。", verdict=0),
                StatementFaithfulnessAnswer(statement="提供的經文段落沒有提到他們埋葬的地點。", reason="對所提供經文內容的描述正確：只說抬出去埋葬，未提地點。", verdict=1),
            ]),
        ),
    ]


def metric(sample, name):
    for m in sample['metrics']:
        if m['name'] == name:
            return m['value'] if m['valid'] else None
    return None


def build_header(i, src):
    header = f"[{i}] {src.get('book','')} 第{src.get('chapter','')}章"
    if src.get('title'):
        header += f" - {src['title']}"
    if src.get('verse_range'):
        header += f" ({src['verse_range']}節)"
    return header


async def fetch_content(pool, src, route):
    sid = src['id']
    parts = sid.split(':')
    if len(parts) == 3 and '-' in parts[2]:
        a, b = parts[2].split('-', 1)
        return await _fetch_verse_range(pool, parts[0], int(parts[1]), int(a), int(b))
    if len(parts) == 3 and route == 'R1' and str(src.get('verse_range', '')) == parts[2]:
        # single verse from verse_direct (fixes verse/pericope id collision, e.g. 3jn:1:2)
        return await _fetch_single_verse(pool, parts[0], int(parts[1]), int(parts[2]))
    if len(parts) == 4:
        row = await pool.fetchrow("SELECT content FROM chunks WHERE id=$1", sid)
        return row['content'] if row else ''
    row = await pool.fetchrow("SELECT content FROM pericopes WHERE id=$1", sid)
    if row:
        return row['content']
    if parts[2].isdigit():
        return await _fetch_single_verse(pool, parts[0], int(parts[1]), int(parts[2]))
    return ''


async def build_hdr_contexts(pool, raw):
    out = []
    for i, src in enumerate(raw['sources'], 1):
        content = await fetch_content(pool, src, raw.get('route_used'))
        if not content:
            continue
        out.append(build_header(i, src) + "\n" + content)
    return out


def select_ids(res):
    low, perfect = [], []
    for s in res['samples']:
        f = metric(s, 'ragas_faithfulness')
        if f is None:
            continue
        (perfect if f >= 1.0 else low).append(s['question_id'])
    rnd = random.Random(42)
    controls = rnd.sample(perfect, min(N_CONTROL, len(perfect)))
    ids = low + controls
    return ids, set(controls)


async def main():
    raw = {x['question_id']: x for x in json.load(open('results_graph/raw_responses.json'))}
    res = json.load(open('results_graph/evaluation_results.json'))
    stored = {s['question_id']: metric(s, 'ragas_faithfulness') for s in res['samples']}
    ids, controls = select_ids(res)
    if LIMIT:
        ids = ids[:LIMIT]
    print(f"[refaith] {len(ids)} samples ({len(controls & set(ids))} controls) conditions={CONDITIONS}", flush=True)

    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                d = json.loads(line)
                done.add((d['qid'], d['condition']))
            except Exception:
                pass
    stmt_cache = json.load(open(STMT_CACHE)) if os.path.exists(STMT_CACHE) else {}

    llm = LangchainLLMWrapper(
        ChatOllama(model=settings.eval_ollama_model, base_url=settings.ollama_base_url,
                   temperature=0.0, num_predict=8192, num_ctx=16384, top_p=0.9,
                   reasoning=False, keep_alive="60m"),
        run_config=RunConfig(timeout=1800, max_retries=1, max_wait=30),
    )
    sg_prompt = StatementGeneratorPrompt()
    nli_default = NLIStatementPrompt()
    nli_zh = ZhNLIPrompt()

    pool = await asyncpg.create_pool(host=settings.postgres_host, port=settings.postgres_port,
                                     database=settings.postgres_db, user=settings.postgres_user,
                                     password=settings.postgres_password, min_size=1, max_size=2)
    t_start = time.time()
    for n, qid in enumerate(ids, 1):
        r = raw[qid]
        todo = [c for c in CONDITIONS if (qid, c) not in done]
        if not todo:
            continue
        # 1) statements (shared across conditions)
        if qid in stmt_cache:
            statements = stmt_cache[qid]
        else:
            t0 = time.time()
            try:
                sg = await sg_prompt.generate(llm=llm, data=StatementGeneratorInput(question=r['question'], answer=r['rag_answer']))
                statements = sg.statements
            except Exception as e:
                print(f"[refaith] {qid} statement generation failed: {e!r}", flush=True)
                statements = []
            stmt_cache[qid] = statements
            json.dump(stmt_cache, open(STMT_CACHE, 'w'), ensure_ascii=False, indent=1)
            print(f"[refaith] {n}/{len(ids)} {qid} statements={len(statements)} ({time.time()-t0:.1f}s)", flush=True)
        if not statements:
            for c in todo:
                with open(OUT, 'a') as f:
                    f.write(json.dumps({'qid': qid, 'condition': c, 'stored': stored.get(qid), 'score': None, 'error': 'no statements', 'is_control': qid in controls}, ensure_ascii=False) + "\n")
            continue
        hdr_ctx = await build_hdr_contexts(pool, r)
        for c in todo:
            if c == 'orig':
                ctx = "\n".join(r['contexts']); prompt = nli_default
            elif c == 'hdr':
                ctx = "\n\n".join(hdr_ctx); prompt = nli_default
            elif c == 'hdr_zh':
                ctx = f"【使用者問題】{r['question']}\n\n【經文段落】\n" + "\n\n".join(hdr_ctx); prompt = nli_zh
            else:
                raise ValueError(c)
            t0 = time.time()
            rec = {'qid': qid, 'condition': c, 'stored': stored.get(qid), 'route': r.get('route_used'),
                   'is_control': qid in controls, 'n_statements': len(statements)}
            try:
                out = await prompt.generate(llm=llm, data=NLIStatementInput(context=ctx, statements=statements))
                verdicts = [{'statement': s.statement, 'verdict': int(bool(s.verdict)), 'reason': s.reason} for s in out.statements]
                score = sum(v['verdict'] for v in verdicts) / len(verdicts) if verdicts else None
                rec.update({'score': score, 'verdicts': verdicts})
            except Exception as e:
                rec.update({'score': None, 'error': repr(e)[:300]})
            rec['secs'] = round(time.time() - t0, 1)
            with open(OUT, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[refaith] {n}/{len(ids)} {qid} {c}: stored={stored.get(qid)} -> {rec.get('score')} ({rec['secs']}s) elapsed={(time.time()-t_start)/60:.1f}m", flush=True)
    await pool.close()
    print("[refaith] DONE", flush=True)


if __name__ == '__main__':
    asyncio.run(main())
