"""The chronology card (王朝年表卡): the regnal layer walked by a program, attached to the
generator's prompt on dynasty-chronology questions only.

Confirmed on a blind set of 32 questions in 14 units (experiment A, 2026-10-19: H1 vs the
canonical formula window +0.456, H2 vs the same rows given to the LLM +0.266) and brought
into the architecture by Kay's decisions of 2026-10-19
(``docs/records/2026-10-19_regnal_card_integration_plan.md``). The generator's prompt is put
together the experiment's way (its system prompt and user template, byte for byte), and so is the
seed call's when it runs. The card in it is not the confirmed arm's: since 2026-10-19 the layer is
the fixed one (Athaliah on the Judah chain, Solomon off it), the engine's S4 guard can drop a born
line, and the seeds come from rules first (``seeds.rule_seeds``, no LLM call) with the gemma seed
call only their fallback. H1 and H2 speak of the confirmed arm (experiment A's layer, gemma seeds,
no guard); this version is checked in-sample only (the seed regression and A4′). A question the
trigger does not take, or a card the engine cannot write, goes the ordinary path unchanged.
"""
