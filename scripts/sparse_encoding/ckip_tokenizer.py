"""
CKIP-based tokenizer for Traditional Chinese text segmentation.
Uses lazy loading to avoid loading heavy models until needed.
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


class CKIPTokenizer:
    """
    Traditional Chinese tokenizer using CKIP Transformers.

    Features:
    - Lazy initialization: Models are loaded only when first needed
    - Configurable GPU usage
    - Batch processing support
    - Stopword filtering
    """

    # Default stopwords for Chinese (common particles, punctuation, etc.)
    DEFAULT_STOPWORDS = {
        # Particles and function words
        "的", "了", "是", "在", "有", "和", "與", "就", "都", "也",
        "而", "及", "或", "把", "被", "對", "給", "從", "到", "向",
        "為", "以", "於", "這", "那", "之", "所", "使", "能", "要",
        "會", "可", "將", "又", "再", "很", "更", "最", "才", "只",
        "若", "如", "若", "且", "因", "但", "卻", "乃", "便", "則",
        # Pronouns
        "他", "她", "它", "我", "你", "們", "他們", "她們", "我們", "你們",
        "這個", "那個", "什麼", "怎麼", "誰", "哪", "哪裡", "哪個",
        # Numbers
        "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
        "百", "千", "萬", "第",
        # Common verbs
        "說", "來", "去", "做", "讓", "叫",
        # Punctuation (will also be filtered by regex)
        "。", "，", "、", "；", "：", "？", "！", "「", "」",
        "『", "』", "（", "）", "【", "】", "…", "—", "～",
    }

    def __init__(
        self,
        use_gpu: bool = False,
        stopwords: Optional[set] = None,
        min_token_length: int = 1,
    ):
        """
        Initialize the CKIP tokenizer.

        Args:
            use_gpu: Whether to use GPU for the model.
            stopwords: Custom stopwords set. If None, uses default.
            min_token_length: Minimum token length to keep.
        """
        self._ws_driver = None
        self._initialized = False
        self.use_gpu = use_gpu
        self.stopwords = stopwords if stopwords is not None else self.DEFAULT_STOPWORDS
        self.min_token_length = min_token_length

        # Pattern to match non-Chinese characters and punctuation
        self._punctuation_pattern = re.compile(
            r'[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u0030-\u0039\u0041-\u005a\u0061-\u007a]+'
        )

    def _initialize(self):
        """Lazy initialization of CKIP word segmenter."""
        if self._initialized:
            return

        try:
            from ckip_transformers.nlp import CkipWordSegmenter

            logger.info("Loading CKIP Word Segmenter...")
            device = 0 if self.use_gpu else -1
            self._ws_driver = CkipWordSegmenter(model="bert-base", device=device)
            self._initialized = True
            logger.info("CKIP Word Segmenter loaded successfully")

        except ImportError:
            logger.error(
                "CKIP Transformers not installed. "
                "Install with: pip install ckip-transformers"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to initialize CKIP: {e}")
            raise

    def tokenize(self, text: str, remove_stopwords: bool = True) -> List[str]:
        """
        Tokenize a single text into words.

        Args:
            text: The text to tokenize.
            remove_stopwords: Whether to remove stopwords.

        Returns:
            List of tokens.
        """
        self._initialize()

        # Get word segmentation result
        result = self._ws_driver([text])
        tokens = result[0] if result else []

        # Post-process tokens
        processed = []
        for token in tokens:
            # Skip empty tokens
            if not token or not token.strip():
                continue

            # Remove punctuation and special characters
            token = self._punctuation_pattern.sub("", token)
            if not token:
                continue

            # Check minimum length
            if len(token) < self.min_token_length:
                continue

            # Remove stopwords if requested
            if remove_stopwords and token in self.stopwords:
                continue

            processed.append(token)

        return processed

    def tokenize_batch(
        self,
        texts: List[str],
        remove_stopwords: bool = True,
    ) -> List[List[str]]:
        """
        Tokenize a batch of texts.

        Args:
            texts: List of texts to tokenize.
            remove_stopwords: Whether to remove stopwords.

        Returns:
            List of token lists.
        """
        self._initialize()

        # Batch process with CKIP
        results = self._ws_driver(texts)

        # Post-process each result
        processed_batch = []
        for tokens in results:
            processed = []
            for token in tokens:
                if not token or not token.strip():
                    continue

                token = self._punctuation_pattern.sub("", token)
                if not token:
                    continue

                if len(token) < self.min_token_length:
                    continue

                if remove_stopwords and token in self.stopwords:
                    continue

                processed.append(token)

            processed_batch.append(processed)

        return processed_batch

    def add_stopwords(self, words: set):
        """Add additional stopwords."""
        self.stopwords.update(words)

    def remove_stopwords(self, words: set):
        """Remove stopwords from the set."""
        self.stopwords -= words

    @property
    def is_initialized(self) -> bool:
        """Check if the model is loaded."""
        return self._initialized
