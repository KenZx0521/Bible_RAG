"""The suite's own harness (run.sh, conftest.py)."""

import os

import pytest


def test_scripts_are_importable():
    import backfill_head_events  # noqa: F401  (top-level script import, cwd-independent)


def test_suite_never_contacts_the_hf_hub():
    # process_bible tests load the BGE-M3 tokenizer: online that is a hub HEAD
    # request per file, on a cold cache a ~20 MB download over a ~50 KB/s link.
    # run.sh exports both switches; run the suite through it.
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_bge_m3_tokenizer_comes_from_the_hf_cache():
    # Offline, a cold cache makes TokenizerWrapper fall back to a character
    # estimate with only a printed warning: this skip is the visible trace.
    # No token count is pinned (transformers 5.0 and 5.3 split full-width
    # punctuation differently).
    from bible_chunking.tokenizer_wrapper import TokenizerWrapper

    tokenizer = TokenizerWrapper()._tokenizer
    if tokenizer is None:
        pytest.skip("HF cache cold: the process_bible tests ran on the character fallback, not BGE-M3")
    assert "XLMRoberta" in type(tokenizer).__name__
