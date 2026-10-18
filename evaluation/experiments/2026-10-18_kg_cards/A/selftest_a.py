"""Scorer self-test of experiment A (appendix A.5): synthetic answers built from each item's keys and
the reference layer at run time (no answer text is stored in the repo). Each case has the score the
appendix rules give; dry_run_a writes the results to store A/dry_run/summary.json."""
from __future__ import annotations

from a_common import KNAME
from keys_a import OTHER, item_ctx, king_lexicon, score_line
from score_a import answer_text


def key_text(k: dict) -> str:
    if k["type"] == "number":
        return f"{k['value']}{k['unit'].split('|')[0]}"
    return k["accept"][0]


def cases(it: dict, VR, traps: set) -> list[tuple[str, str, float]]:
    keys = it["keys"]
    gold = "，".join(key_text(k) for k in keys)
    out = [("gold", f"推理。\n答案：{gold}", 1.0), ("gold+trap", f"答案：{gold}，{sorted(traps)[0]}", 0.0),
           ("bold marker", f"**答案**：{gold}", 1.0),
           ("list block", "答案：\n" + "\n".join(f"{i}. {key_text(k)}" for i, k in enumerate(keys, 1)), 1.0)]
    names = [k for k in keys if k["type"] == "name"]
    if any(k["type"] == "number" for k in keys):
        nums = [k for k in keys if k["type"] == "number"]
        rest = "，".join(key_text(k) for k in keys if k["type"] != "number")
        cite = "（王下21:" + "-".join(str(k["value"]) for k in nums) + "）"
        out.append(("numbers only in a citation", f"答案：{rest}{cite}", (len(keys) - len(nums)) / len(keys)))
        out.append(("number with another unit", "答案：" + "，".join(
            f"{k['value']}個月" if k["type"] == "number" else key_text(k) for k in keys), (len(keys) - len(nums)) / len(keys)))
    for y in it["gold"]:
        g = VR.nodes[y]
        if g["father"] and names:
            out.append(("father phrase", f"答案：{g['father']}的兒子{gold}", 1.0))
        foreign = [z for z, n in VR.nodes.items() if n["kingdom"] != g["kingdom"] and g["name"] in VR.names(z)]
        if foreign and len(keys) == 1:
            out.append(("other kingdom's homonym", f"答案：{OTHER[g['kingdom']]}王{g['name']}", 0.0))
        wrong = [n["father"] for z, n in VR.nodes.items() if z != y and n["kingdom"] == g["kingdom"]
                 and g["name"] in VR.names(z) and n["father"]]
        for f in wrong:
            out.append(("wrong-father homonym", f"答案：{f}的兒子{gold}", 1.0 - 1 / len(keys)))
            out.append(("negated wrong father", f"答案：{g['father']}的兒子{gold}（不是{f}的兒子{g['name']}）", 1.0))
    if it.get("kind") == "natural":
        chain = "、".join(VR.nodes[z]["name"] for z in it["path"])
        out.append(("walk path named", f"答案：{gold}。{chain}", 1.0))
    if any(k["type"] == "term" and k.get("reject") for k in keys) and len(it["seeds"]) == 2:
        a, b = (VR.nodes[z]["name"] for z in it["seeds"])
        out += [("kinship direction", f"答案：{b}是{a}的曾祖父", 1.0), ("kinship reversed", f"答案：{a}是{b}的曾祖父", 0.0)]
    return out


def selftest(items: list[dict], VR) -> dict:
    base, res = king_lexicon(VR), {"n": 0, "ok": 0, "fails": [], "by_case": {}}
    for it in items:
        ctx = item_ctx(it, VR, base)
        for name, content, want in cases(it, VR, ctx["traps"]):
            got = score_line(ctx, answer_text(content))["score"]
            ok = abs(got - want) < 1e-9
            res["n"] += 1
            res["ok"] += ok
            c = res["by_case"].setdefault(name, [0, 0])
            c[0], c[1] = c[0] + ok, c[1] + 1
            if not ok:
                res["fails"].append([it["id"], name, KNAME.get(it["kingdom"]), got, want])
    return res
