"""
Configuration for Bible Chunking

Contains:
- TOKEN_CONFIG: BGE-M3 token configuration
- BOOK_CONFIG: 66 Bible books configuration
- CROSS_REF_ABBREV: Cross-reference abbreviation mapping
"""

from typing import Dict, Optional, Any

# =============================================================================
# TOKEN CONFIGURATION (BGE-M3)
# =============================================================================

TOKEN_CONFIG = {
    # BGE-M3 Model Configuration
    "model_name": "BAAI/bge-m3",
    "max_model_tokens": 8192,       # BGE-M3 maximum supported
    "embedding_dim": 1024,          # BGE-M3 embedding dimension

    # Chunk Configuration
    "target_chunk_tokens": 512,     # Recommended chunk size for BGE-M3
    "max_chunk_tokens": 768,        # Trigger chunking threshold (1.5x target)
    "min_chunk_tokens": 128,        # Minimum chunk size (avoid too small)
    "overlap_verses": 1,            # Overlap verses for context continuity
}


# =============================================================================
# BOOK CONFIGURATION (66 Books)
# =============================================================================

BOOK_CONFIG: Dict[str, Dict[str, Any]] = {
    # === Old Testament - Pentateuch (5) ===
    "創世記": {"id": "gen", "name_en": "Genesis", "testament": "old", "category": "pentateuch", "order": 1},
    "出埃及記": {"id": "exo", "name_en": "Exodus", "testament": "old", "category": "pentateuch", "order": 2},
    "利未記": {"id": "lev", "name_en": "Leviticus", "testament": "old", "category": "pentateuch", "order": 3},
    "民數記": {"id": "num", "name_en": "Numbers", "testament": "old", "category": "pentateuch", "order": 4},
    "申命記": {"id": "deu", "name_en": "Deuteronomy", "testament": "old", "category": "pentateuch", "order": 5},

    # === Old Testament - Historical Books (12) ===
    "約書亞記": {"id": "jos", "name_en": "Joshua", "testament": "old", "category": "historical", "order": 6},
    "士師記": {"id": "jdg", "name_en": "Judges", "testament": "old", "category": "historical", "order": 7},
    "路得記": {"id": "rut", "name_en": "Ruth", "testament": "old", "category": "historical", "order": 8},
    "撒母耳記上": {"id": "1sa", "name_en": "1 Samuel", "testament": "old", "category": "historical", "order": 9},
    "撒母耳記下": {"id": "2sa", "name_en": "2 Samuel", "testament": "old", "category": "historical", "order": 10},
    "列王紀上": {"id": "1ki", "name_en": "1 Kings", "testament": "old", "category": "historical", "order": 11},
    "列王紀下": {"id": "2ki", "name_en": "2 Kings", "testament": "old", "category": "historical", "order": 12},
    "歷代志上": {"id": "1ch", "name_en": "1 Chronicles", "testament": "old", "category": "historical", "order": 13},
    "歷代志下": {"id": "2ch", "name_en": "2 Chronicles", "testament": "old", "category": "historical", "order": 14},
    "以斯拉記": {"id": "ezr", "name_en": "Ezra", "testament": "old", "category": "historical", "order": 15},
    "尼西米記": {"id": "neh", "name_en": "Nehemiah", "testament": "old", "category": "historical", "order": 16},
    "以斯帖記": {"id": "est", "name_en": "Esther", "testament": "old", "category": "historical", "order": 17},

    # === Old Testament - Wisdom/Poetry (5) ===
    "約伯記": {"id": "job", "name_en": "Job", "testament": "old", "category": "wisdom", "order": 18},
    "詩篇": {"id": "psa", "name_en": "Psalms", "testament": "old", "category": "wisdom", "order": 19},
    "箴言": {"id": "pro", "name_en": "Proverbs", "testament": "old", "category": "wisdom", "order": 20},
    "傳道書": {"id": "ecc", "name_en": "Ecclesiastes", "testament": "old", "category": "wisdom", "order": 21},
    "雅歌": {"id": "sng", "name_en": "Song of Solomon", "testament": "old", "category": "wisdom", "order": 22},

    # === Old Testament - Major Prophets (5) ===
    "以賽亞書": {"id": "isa", "name_en": "Isaiah", "testament": "old", "category": "major_prophets", "order": 23},
    "耶利米書": {"id": "jer", "name_en": "Jeremiah", "testament": "old", "category": "major_prophets", "order": 24},
    "耶利米哀歌": {"id": "lam", "name_en": "Lamentations", "testament": "old", "category": "major_prophets", "order": 25},
    "以西結書": {"id": "ezk", "name_en": "Ezekiel", "testament": "old", "category": "major_prophets", "order": 26},
    "但以理書": {"id": "dan", "name_en": "Daniel", "testament": "old", "category": "major_prophets", "order": 27},

    # === Old Testament - Minor Prophets (12) ===
    "何西阿書": {"id": "hos", "name_en": "Hosea", "testament": "old", "category": "minor_prophets", "order": 28},
    "約珥書": {"id": "jol", "name_en": "Joel", "testament": "old", "category": "minor_prophets", "order": 29},
    "阿摩司書": {"id": "amo", "name_en": "Amos", "testament": "old", "category": "minor_prophets", "order": 30},
    "俄巴底亞書": {"id": "oba", "name_en": "Obadiah", "testament": "old", "category": "minor_prophets", "order": 31},
    "約拿書": {"id": "jon", "name_en": "Jonah", "testament": "old", "category": "minor_prophets", "order": 32},
    "彌迦書": {"id": "mic", "name_en": "Micah", "testament": "old", "category": "minor_prophets", "order": 33},
    "那鴻書": {"id": "nam", "name_en": "Nahum", "testament": "old", "category": "minor_prophets", "order": 34},
    "哈巴谷書": {"id": "hab", "name_en": "Habakkuk", "testament": "old", "category": "minor_prophets", "order": 35},
    "西番雅書": {"id": "zep", "name_en": "Zephaniah", "testament": "old", "category": "minor_prophets", "order": 36},
    "哈該書": {"id": "hag", "name_en": "Haggai", "testament": "old", "category": "minor_prophets", "order": 37},
    "撒迦利亞書": {"id": "zec", "name_en": "Zechariah", "testament": "old", "category": "minor_prophets", "order": 38},
    "瑪拉基書": {"id": "mal", "name_en": "Malachi", "testament": "old", "category": "minor_prophets", "order": 39},

    # === New Testament - Gospels (4) ===
    "馬太福音": {"id": "mat", "name_en": "Matthew", "testament": "new", "category": "gospels", "order": 40},
    "馬可福音": {"id": "mrk", "name_en": "Mark", "testament": "new", "category": "gospels", "order": 41},
    "路加福音": {"id": "luk", "name_en": "Luke", "testament": "new", "category": "gospels", "order": 42},
    "約翰福音": {"id": "jhn", "name_en": "John", "testament": "new", "category": "gospels", "order": 43},

    # === New Testament - Acts (1) ===
    "使徒行傳": {"id": "act", "name_en": "Acts", "testament": "new", "category": "acts", "order": 44},

    # === New Testament - Pauline Epistles (13) ===
    "羅馬書": {"id": "rom", "name_en": "Romans", "testament": "new", "category": "pauline", "order": 45},
    "哥林多前書": {"id": "1co", "name_en": "1 Corinthians", "testament": "new", "category": "pauline", "order": 46},
    "哥林多後書": {"id": "2co", "name_en": "2 Corinthians", "testament": "new", "category": "pauline", "order": 47},
    "加拉太書": {"id": "gal", "name_en": "Galatians", "testament": "new", "category": "pauline", "order": 48},
    "以弗所書": {"id": "eph", "name_en": "Ephesians", "testament": "new", "category": "pauline", "order": 49},
    "腓立比書": {"id": "php", "name_en": "Philippians", "testament": "new", "category": "pauline", "order": 50},
    "歌羅西書": {"id": "col", "name_en": "Colossians", "testament": "new", "category": "pauline", "order": 51},
    "帖撒羅尼迦前書": {"id": "1th", "name_en": "1 Thessalonians", "testament": "new", "category": "pauline", "order": 52},
    "帖撒羅尼迦後書": {"id": "2th", "name_en": "2 Thessalonians", "testament": "new", "category": "pauline", "order": 53},
    "提摩太前書": {"id": "1ti", "name_en": "1 Timothy", "testament": "new", "category": "pauline", "order": 54},
    "提摩太後書": {"id": "2ti", "name_en": "2 Timothy", "testament": "new", "category": "pauline", "order": 55},
    "提多書": {"id": "tit", "name_en": "Titus", "testament": "new", "category": "pauline", "order": 56},
    "腓利門書": {"id": "phm", "name_en": "Philemon", "testament": "new", "category": "pauline", "order": 57},

    # === New Testament - General Epistles (8) ===
    "希伯來書": {"id": "heb", "name_en": "Hebrews", "testament": "new", "category": "general", "order": 58},
    "雅各書": {"id": "jas", "name_en": "James", "testament": "new", "category": "general", "order": 59},
    "彼得前書": {"id": "1pe", "name_en": "1 Peter", "testament": "new", "category": "general", "order": 60},
    "彼得後書": {"id": "2pe", "name_en": "2 Peter", "testament": "new", "category": "general", "order": 61},
    "約翰一書": {"id": "1jn", "name_en": "1 John", "testament": "new", "category": "general", "order": 62},
    "約翰二書": {"id": "2jn", "name_en": "2 John", "testament": "new", "category": "general", "order": 63},
    "約翰三書": {"id": "3jn", "name_en": "3 John", "testament": "new", "category": "general", "order": 64},
    "猶大書": {"id": "jud", "name_en": "Jude", "testament": "new", "category": "general", "order": 65},

    # === New Testament - Apocalyptic (1) ===
    "啟示錄": {"id": "rev", "name_en": "Revelation", "testament": "new", "category": "apocalyptic", "order": 66},
}


# =============================================================================
# CROSS-REFERENCE ABBREVIATIONS
# =============================================================================

CROSS_REF_ABBREV: Dict[str, str] = {
    # Old Testament
    "創": "gen",
    "出": "exo",
    "利": "lev",
    "民": "num",
    "申": "deu",
    "書": "jos",
    "士": "jdg",
    "得": "rut",
    "撒上": "1sa",
    "撒下": "2sa",
    "王上": "1ki",
    "王下": "2ki",
    "代上": "1ch",
    "代下": "2ch",
    "拉": "ezr",
    "尼": "neh",
    "斯": "est",
    "伯": "job",
    "詩": "psa",
    "箴": "pro",
    "傳": "ecc",
    "歌": "sng",
    "賽": "isa",
    "耶": "jer",
    "哀": "lam",
    "結": "ezk",
    "但": "dan",
    "何": "hos",
    "珥": "jol",
    "摩": "amo",
    "俄": "oba",
    "拿": "jon",
    "彌": "mic",
    "鴻": "nam",
    "哈": "hab",
    "番": "zep",
    "該": "hag",
    "亞": "zec",
    "瑪": "mal",

    # New Testament
    "太": "mat",
    "可": "mrk",
    "路": "luk",
    "約": "jhn",
    "徒": "act",
    "羅": "rom",
    "林前": "1co",
    "林後": "2co",
    "加": "gal",
    "弗": "eph",
    "腓": "php",
    "西": "col",
    "帖前": "1th",
    "帖後": "2th",
    "提前": "1ti",
    "提後": "2ti",
    "多": "tit",
    "門": "phm",
    "來": "heb",
    "雅": "jas",
    "彼前": "1pe",
    "彼後": "2pe",
    "約一": "1jn",
    "約二": "2jn",
    "約三": "3jn",
    "猶": "jud",
    "啟": "rev",
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_book_config(book_name: str) -> Dict[str, Any]:
    """
    Get configuration for a book by Chinese name.

    Args:
        book_name: Chinese book name (e.g., "創世記")

    Returns:
        Dictionary with id, name_en, testament, category, order

    Raises:
        ValueError: If book name is not found
    """
    if book_name not in BOOK_CONFIG:
        raise ValueError(f"Unknown book: {book_name}")
    return BOOK_CONFIG[book_name]


def get_book_by_id(book_id: str) -> Optional[Dict[str, Any]]:
    """
    Get book configuration by ID.

    Args:
        book_id: Book ID (e.g., "gen")

    Returns:
        Dictionary with name and config, or None if not found
    """
    for name, config in BOOK_CONFIG.items():
        if config["id"] == book_id:
            return {"name": name, **config}
    return None


def get_book_id_by_abbrev(abbrev: str) -> Optional[str]:
    """
    Get book ID from cross-reference abbreviation.

    Args:
        abbrev: Abbreviation (e.g., "創", "太")

    Returns:
        Book ID or None if not found
    """
    return CROSS_REF_ABBREV.get(abbrev)


def get_all_book_names() -> list:
    """Get list of all book names in canonical order."""
    return sorted(BOOK_CONFIG.keys(), key=lambda x: BOOK_CONFIG[x]["order"])
