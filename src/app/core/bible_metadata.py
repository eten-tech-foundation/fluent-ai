from typing import List, Dict

BIBLE_BOOK_GROUPS: Dict[str, List[str]] = {
    "gospel_narrative": ["mat", "mrk", "luk", "jhn"],
    "jesus_parables": ["mat", "mrk", "luk"],
    "johannine_writings": ["jhn", "1jn", "2jn", "3jn", "rev"],
    "lukan_writings": ["luk", "act"],
    "pauline_theology": ["rom", "1co", "2co", "gal", "eph", "php", "col"],
    "pastoral_epistles": ["1ti", "2ti", "tit"],
    "prison_epistles": ["eph", "php", "col", "phm"],
    "wisdom_literature": ["job", "psa", "pro", "ecc", "sng"],
    "major_prophetic_style": ["isa", "jer", "ezk", "dan"],
    "minor_prophetic_style": [
        "hos", "jol", "amo", "oba", "jon", "mic",
        "nam", "hab", "zep", "hag", "zec", "mal"
    ],
    "torah_legal_language": ["gen", "exo", "lev", "num", "deu"],
    "kingdom_history": ["1sa", "2sa", "1ki", "2ki", "1ch", "2ch"],
    "post_exilic_history": ["ezr", "neh", "est"],
    "exile_and_restoration": ["jer", "ezk", "dan", "ezr", "neh"],
    "messianic_prophecy": ["isa", "mic", "zec", "psa"],
    "church_history_and_mission": ["luk", "act"],
    "suffering_and_endurance": ["job", "1pe", "jas", "heb"],
    "worship_and_prayer": ["psa"],
    "love_and_relationship_poetry": ["sng"],
}

RECOMMENDED_STRATEGIES: Dict[str, List[str]] = {
    "mat": BIBLE_BOOK_GROUPS["gospel_narrative"],
    "mrk": BIBLE_BOOK_GROUPS["gospel_narrative"],
    "luk": ["luk", "act", "mat", "mrk"],
    "jhn": BIBLE_BOOK_GROUPS["johannine_writings"],
    "act": BIBLE_BOOK_GROUPS["lukan_writings"],
    "rom": BIBLE_BOOK_GROUPS["pauline_theology"],
    "1co": BIBLE_BOOK_GROUPS["pauline_theology"],
    "2co": BIBLE_BOOK_GROUPS["pauline_theology"],
    "gal": BIBLE_BOOK_GROUPS["pauline_theology"],
    "eph": BIBLE_BOOK_GROUPS["pauline_theology"],
    "php": BIBLE_BOOK_GROUPS["pauline_theology"],
    "col": BIBLE_BOOK_GROUPS["pauline_theology"],
    "1ti": BIBLE_BOOK_GROUPS["pastoral_epistles"],
    "2ti": BIBLE_BOOK_GROUPS["pastoral_epistles"],
    "tit": BIBLE_BOOK_GROUPS["pastoral_epistles"],
    "phm": BIBLE_BOOK_GROUPS["prison_epistles"],
    "isa": BIBLE_BOOK_GROUPS["major_prophetic_style"],
    "jer": BIBLE_BOOK_GROUPS["major_prophetic_style"],
    "ezk": BIBLE_BOOK_GROUPS["major_prophetic_style"],
    "dan": BIBLE_BOOK_GROUPS["major_prophetic_style"],
    "zec": BIBLE_BOOK_GROUPS["minor_prophetic_style"],
    "job": BIBLE_BOOK_GROUPS["wisdom_literature"],
    "psa": BIBLE_BOOK_GROUPS["wisdom_literature"],
    "pro": BIBLE_BOOK_GROUPS["wisdom_literature"],
    "ecc": BIBLE_BOOK_GROUPS["wisdom_literature"],
    "sng": BIBLE_BOOK_GROUPS["wisdom_literature"],
    "gen": BIBLE_BOOK_GROUPS["torah_legal_language"],
    "exo": BIBLE_BOOK_GROUPS["torah_legal_language"],
    "lev": BIBLE_BOOK_GROUPS["torah_legal_language"],
    "num": BIBLE_BOOK_GROUPS["torah_legal_language"],
    "deu": BIBLE_BOOK_GROUPS["torah_legal_language"],
}

def get_context_book_codes(target_book_code: str) -> List[str]:
    code = target_book_code.lower()
    
    if code in RECOMMENDED_STRATEGIES:
        return RECOMMENDED_STRATEGIES[code]
        
    for group in BIBLE_BOOK_GROUPS.values():
        if code in group:
            return group
            
    return [code]
