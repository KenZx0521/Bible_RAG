"""Simulated anchored_rules (plan §4 1A): slot patterns inside one verse, names by
longest match over the full name lexicon with word-boundary checks, endpoints
resolved through the pericope's own MENTIONS (so the provenance gate holds by
construction). Direction comes from the slot, never from id order."""
import re
STOP_DE = 'all'
from collections import defaultdict

DELIM = set('、，；。：（）「」『』！？ \n')
LIST_SEP = set('、和與及')
# what may sit right before a name (a name glued to a preceding hanzi is a substring)
PREV_OK = DELIM | set('是叫名給和與及的就又也並乃從到在對向同為生娶了')
# single characters that cannot continue a name: a name followed by one of these ends there
TRAIL_OK = DELIM | set('的生是就又也並作在說和與及同從到為等都所被將便乃要上下來去起往向對給把叫名娶有因年歲活死共'
                       '一二三四五六七八九十百千各之後時這那王長不沒未卻已曾必若既還才再亦仍')


def build_tokenizer(names):
    names = sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True)
    return re.compile('|'.join(re.escape(n) for n in names))


def tokens(text, big):
    return [(m.start(), m.end(), m.group()) for m in big.finditer(text)]


def _ok_before(text, s):
    return s == 0 or text[s - 1] in PREV_OK


def _ok_after(text, e, allowed):
    return e >= len(text) or text[e] in DELIM or text[e] in allowed


CHILD_RE = re.compile(r'的(?:長|次|三|四|五|六|七|小)?(兒子|女兒)(?:是|有|就是|名叫|叫)?')
BEGOT_RE = re.compile(r'(?:又|也)?生(?:了)?')
WIFE_RE = re.compile(r'的妻(?:子)?(?:是|名叫|叫)?')
IS_CHILD_RE = re.compile(r'是')


def _list_after(toks, j, cur, text, resolve):
    """Names listed right after position `cur` (A、B和C...)."""
    out = []
    cur0 = cur
    while j < len(toks) and toks[j][0] < cur:   # tokens swallowed by the pattern (兒子, 妻子 are lexicon names too)
        j += 1
    while j < len(toks):
        s, e, nm = toks[j]
        if s == cur or (s == cur + 1 and text[cur] in LIST_SEP):
            if not (e >= len(text) or text[e] in TRAIL_OK):
                break
            if STOP_DE != 'off' and e < len(text) and text[e] == '的':
                first_direct = (not out) and s == cur0
                if not (STOP_DE == 'cont' and first_direct):
                    break   # plan C3: an item followed by 的 owns the next clause; the list ends
                out.append((resolve(nm), nm)) if resolve(nm) else None
                break
            eid = resolve(nm)
            if eid:
                out.append((eid, nm))
            cur = e
            j += 1
            if cur < len(text) and text[cur] in '。；：！？':
                break
        else:
            break
    return out


def extract(pid, vno, text, big, resolve, begot_mode):
    """Yield (head, rel, tail, pattern, evidence)."""
    toks = tokens(text, big)
    out = []
    for i, (s, e, nm) in enumerate(toks):
        if not _ok_before(text, s):
            continue
        a = resolve(nm)
        if not a:
            continue
        rest = text[e:]
        m = CHILD_RE.match(rest)
        if m:
            rel = 'SON_OF' if m.group(1) == '兒子' else 'DAUGHTER_OF'
            for c, cn in _list_after(toks, i + 1, e + m.end(), text, resolve):
                if c != a:
                    out.append((c, rel, a, 'P1_child_of', text))
            continue
        m = WIFE_RE.match(rest)
        if m:
            for w, wn in _list_after(toks, i + 1, e + m.end(), text, resolve)[:1]:
                if w != a:
                    x, y = sorted((a, w))
                    out.append((x, 'SPOUSE_OF', y, 'P4_wife', text))
            continue
        m = BEGOT_RE.match(rest)
        gei_ok = begot_mode == 'father' or (begot_mode == 'gei' and s > 0 and text[s - 1] == '給')
        if m and begot_mode != 'off' and gei_ok:
            for c, cn in _list_after(toks, i + 1, e + m.end(), text, resolve):
                if c != a:
                    out.append((a, 'FATHER_OF', c, 'P3_begot', text))
            continue
        # P2: C 是 P 的兒子/女兒
        m = IS_CHILD_RE.match(rest)
        nxt = next((k for k in range(i + 1, len(toks)) if toks[k][0] >= e), None)
        if m and nxt is not None and toks[nxt][0] == e + m.end():
            s2, e2, nm2 = toks[nxt]
            p = resolve(nm2)
            m2 = CHILD_RE.match(text[e2:])
            if p and m2 and p != a:
                rel = 'SON_OF' if m2.group(1) == '兒子' else 'DAUGHTER_OF'
                out.append((a, rel, p, 'P2_is_child_of', text))
    return out


def run(pericopes, mentions, chunk_parent, lexicon_names, verses_of, begot_mode='father',
        declared=None, deny=frozenset({'group:yehehua'}), guard=None, conflicts=None):
    """declared: entity_id -> {canonical, aliases}; when given, a span resolves only
    if it is the entity's own canonical name or declared alias (no homophone-absorbed
    foreign surface, R3)."""
    # pericope -> span -> {entity ids}; Person only for kinship slots
    span_map = defaultdict(lambda: defaultdict(set))
    stats = defaultdict(int)
    for m in mentions:
        pid = chunk_parent.get(m['sid'], m['sid']) if m['label'] == 'Chunk' else m['sid']
        if m['eid'].startswith('person:') and m['eid'] not in deny and m['span']:
            if declared is not None and m['span'] not in declared.get(m['eid'], ()):
                stats['foreign_surface_skipped'] += 1
                continue
            span_map[pid][m['span']].add(m['eid'])
    big = build_tokenizer(lexicon_names)
    triples = []
    for pid, p in pericopes.items():
        smap = span_map.get(pid)
        if not smap:
            continue

        def resolve(nm, smap=smap):
            ids = smap.get(nm)
            if not ids:
                return None
            if len(ids) > 1:
                stats['ambiguous_name'] += 1
                return None
            return next(iter(ids))
        for vno, text in verses_of(p['content']):
            for h, rel, t, pat, ev in extract(pid, vno, text, big, resolve, begot_mode):
                pc = (t, h) if rel in ('SON_OF', 'DAUGHTER_OF') else (h, t) if rel == 'FATHER_OF' else None
                if pc is not None and guard is not None:
                    parent, child = pc
                    others = guard(child, parent)
                    if others:
                        stats['same_name_guard_abstain'] += 1
                        conflicts.append({'head_id': h, 'relation': rel, 'tail_id': t, 'source_pericope_id': pid,
                                          'verse': vno, 'other_parents': sorted(others)})
                        continue
                triples.append({'head_id': h, 'relation': rel, 'tail_id': t, 'source_pericope_id': pid,
                                'verse': vno, 'pattern': pat, 'evidence_span': ev[:200]})
                stats[pat] += 1
    return triples, dict(stats)
