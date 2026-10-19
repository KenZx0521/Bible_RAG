"""The chronology card (王朝年表卡): the regnal layer walked by a program, attached to the
generator's prompt on dynasty-chronology questions only.

Confirmed on a blind set of 32 questions in 14 units (experiment A, 2026-10-19: H1 vs the
canonical formula window +0.456, H2 vs the same rows given to the LLM +0.266) and brought
into the architecture by Kay's decisions of 2026-10-19
(``docs/records/2026-10-19_regnal_card_integration_plan.md``). The generator's prompt with a
card is the experiment's, byte for byte, and so is the seed call's when it runs. Since
2026-10-19 the seeds come from rules first (``seeds.rule_seeds``, no LLM call) and the gemma
seed call is only their fallback. The confirmed arm used the gemma seeds alone, so a
rule-seeded card is a processing change from what was confirmed, checked in-sample only
(``test_regnal_seeds``). A question the trigger does not take, or a card the engine cannot
write, goes the ordinary path unchanged.
"""
