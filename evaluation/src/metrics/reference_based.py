"""
Reference-based generation metrics: BLEU, ROUGE, BERTScore.

All scores are computed between the RAG answer and the ground truth reference_answer.
"""

from __future__ import annotations

import logging

from rich.console import Console

from ..models import EvalSample, MetricResult

console = Console()
logger = logging.getLogger(__name__)

# CKIP word segmenter (lazy-loaded)
_ws_driver = None


def _get_ws_driver():
    """Lazy-load CKIP word segmenter."""
    global _ws_driver
    if _ws_driver is None:
        from ckip_transformers.nlp import CkipWordSegmenter
        logger.info("Loading CKIP word segmenter (bert-base)...")
        _ws_driver = CkipWordSegmenter(model="bert-base", device=-1)
        logger.info("CKIP word segmenter loaded.")
    return _ws_driver


def _tokenize_zh(text: str) -> str:
    """Tokenize Chinese text with CKIP, return space-separated string."""
    ws = _get_ws_driver()
    result = ws([text])
    return " ".join(result[0])


def _compute_bleu(hypothesis: str, reference: str) -> float:
    """Compute sentence-level BLEU using sacrebleu with CKIP tokenization."""
    import sacrebleu

    hyp_tok = _tokenize_zh(hypothesis)
    ref_tok = _tokenize_zh(reference)
    result = sacrebleu.sentence_bleu(hyp_tok, [ref_tok])
    return result.score / 100.0  # normalize to 0-1


def _compute_rouge(hypothesis: str, reference: str) -> dict[str, float]:
    """Compute ROUGE-1, ROUGE-2, ROUGE-L with CKIP tokenization."""
    from rouge_score import rouge_scorer

    hyp_tok = _tokenize_zh(hypothesis)
    ref_tok = _tokenize_zh(reference)

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=False)
    scores = scorer.score(ref_tok, hyp_tok)

    return {
        "rouge1": scores["rouge1"].fmeasure,
        "rouge2": scores["rouge2"].fmeasure,
        "rougeL": scores["rougeL"].fmeasure,
    }


def _compute_bertscore(hypotheses: list[str], references: list[str]) -> list[float]:
    """Compute BERTScore F1 for a batch using bert-base-chinese."""
    from bert_score import score as bert_score_fn

    P, R, F1 = bert_score_fn(
        hypotheses,
        references,
        lang="zh",
        model_type="bert-base-chinese",
        verbose=False,
    )
    return F1.tolist()


def compute_reference_metrics(samples: list[EvalSample]) -> dict[str, list[MetricResult]]:
    """
    Compute BLEU, ROUGE, BERTScore for all samples.

    Returns: { question_id: [MetricResult, ...] }
    """
    results: dict[str, list[MetricResult]] = {}

    # Collect pairs for batch BERTScore
    valid_indices = []
    hyps_for_bert = []
    refs_for_bert = []

    for i, sample in enumerate(samples):
        ref = sample.reference_answer
        hyp = sample.rag_answer

        if not ref or not hyp:
            results[sample.question_id] = [
                MetricResult(name="bleu", value=0.0, category="reference_based"),
                MetricResult(name="rouge1", value=0.0, category="reference_based"),
                MetricResult(name="rouge2", value=0.0, category="reference_based"),
                MetricResult(name="rougeL", value=0.0, category="reference_based"),
                MetricResult(name="bertscore", value=0.0, category="reference_based"),
            ]
            continue

        bleu = _compute_bleu(hyp, ref)
        rouge = _compute_rouge(hyp, ref)

        results[sample.question_id] = [
            MetricResult(name="bleu", value=round(bleu, 4), category="reference_based"),
            MetricResult(name="rouge1", value=round(rouge["rouge1"], 4), category="reference_based"),
            MetricResult(name="rouge2", value=round(rouge["rouge2"], 4), category="reference_based"),
            MetricResult(name="rougeL", value=round(rouge["rougeL"], 4), category="reference_based"),
        ]

        valid_indices.append(i)
        hyps_for_bert.append(hyp)
        refs_for_bert.append(ref)

    # Batch BERTScore
    if hyps_for_bert:
        console.print("[dim]Computing BERTScore (bert-base-chinese)...[/dim]")
        f1_scores = _compute_bertscore(hyps_for_bert, refs_for_bert)
        for idx, f1 in zip(valid_indices, f1_scores):
            qid = samples[idx].question_id
            results[qid].append(
                MetricResult(name="bertscore", value=round(f1, 4), category="reference_based")
            )
    else:
        # Fill missing
        for sample in samples:
            if sample.question_id in results and len(results[sample.question_id]) < 5:
                results[sample.question_id].append(
                    MetricResult(name="bertscore", value=0.0, category="reference_based")
                )

    return results
