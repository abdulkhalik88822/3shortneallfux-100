"""Smart, strict and typo-tolerant filename search helpers.

This module contains only Python stdlib code so the parser/ranking can be tested
without a MongoDB connection.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional

LANGUAGES = {
    "hindi", "english", "telugu", "tamil", "kannada", "malayalam",
    "bengali", "marathi", "punjabi", "urdu", "gujarati"
}

QUALITY_ALIASES = {
    "4k": ("4k", "2160p"),
    "2160p": ("2160p", "4k"),
    "1080p": ("1080p",),
    "720p": ("720p",),
    "480p": ("480p",),
    "360p": ("360p",),
}

_GENERIC_WORDS = {"movie", "movies", "film", "films"}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    # S01E03 -> S01 E03 so both components are parsed independently.
    text = re.sub(r"(?i)(s\s*0*\d{1,2})\s*(e\s*0*\d{1,3})", r"\1 \2", text)
    text = re.sub(r"[._+\-]+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_search_query(query: str) -> Dict[str, object]:
    """Parse title/year/season/episode/language/quality from user text."""
    normalized = normalize_text(query)
    working = normalized

    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", working)
    year: Optional[str] = year_match.group(1) if year_match else None

    season_match = re.search(r"\b(?:season|session)\s*0*(\d{1,2})\b|\bs\s*0*(\d{1,2})\b", working, re.I)
    season = int(next((g for g in season_match.groups() if g is not None), 0)) if season_match else None

    episode_match = re.search(r"\bepisode\s*0*(\d{1,3})\b|\bep\s*0*(\d{1,3})\b|\be\s*0*(\d{1,3})\b", working, re.I)
    episode = int(next((g for g in episode_match.groups() if g is not None), 0)) if episode_match else None

    tokens = working.split()
    language = next((t for t in tokens if t in LANGUAGES), None)
    quality = next((t for t in tokens if t in QUALITY_ALIASES), None)

    # Remove metadata from title text. Do this after parsing so e.g. "S01 E03" is preserved above.
    if year:
        working = re.sub(rf"(?<!\d){re.escape(year)}(?!\d)", " ", working)
    working = re.sub(r"\b(?:season|session)\s*0*\d{1,2}\b|\bs\s*0*\d{1,2}\b", " ", working, flags=re.I)
    working = re.sub(r"\bepisode\s*0*\d{1,3}\b|\bep\s*0*\d{1,3}\b|\be\s*0*\d{1,3}\b", " ", working, flags=re.I)

    if language:
        working = re.sub(rf"\b{re.escape(language)}\b", " ", working)
    if quality:
        working = re.sub(rf"\b{re.escape(quality)}\b", " ", working)

    title_tokens = [t for t in working.split() if t]
    # "movie RRR" is usually a request modifier, not part of the actual title.
    if len(title_tokens) > 1:
        title_tokens = [t for t in title_tokens if t not in _GENERIC_WORDS]

    title_phrase = " ".join(title_tokens)
    return {
        "raw": str(query or "").strip(),
        "normalized": normalized,
        "title_tokens": title_tokens,
        "title_phrase": title_phrase,
        "year": year,
        "season": season,
        "episode": episode,
        "language": language,
        "quality": quality,
    }


def token_regex(token: str) -> str:
    # Strict standalone alphanumeric token: Mom != Moms.
    return rf"(?:^|[^a-z0-9]){re.escape(token)}(?:$|[^a-z0-9])"


def year_regex(year: str) -> str:
    return rf"(?<!\d){re.escape(year)}(?!\d)"


def season_regex(season: int) -> str:
    # Matches S1, S01, Season 1, Session 01 and also S01E03.
    n = int(season)
    return rf"(?:^|[^a-z0-9])(?:s(?:eason|ession)?[\s._-]*0*{n})(?!\d)"


def episode_regex(episode: int) -> str:
    # Matches E1, E01, EP1, Episode 01 and S01E01.
    n = int(episode)
    return rf"(?:episode|ep|e)[\s._-]*0*{n}(?!\d)"


def language_regex(language: str) -> str:
    return token_regex(language)


def quality_regex(quality: str) -> str:
    aliases = QUALITY_ALIASES.get(quality, (quality,))
    inner = "|".join(re.escape(x) for x in aliases)
    return rf"(?:^|[^a-z0-9])(?:{inner})(?:$|[^a-z0-9])"


def metadata_conditions(spec: Dict[str, object]) -> List[dict]:
    conditions: List[dict] = []
    if spec.get("year"):
        conditions.append({"file_name": {"$regex": year_regex(str(spec["year"])), "$options": "i"}})
    if spec.get("season") is not None:
        conditions.append({"file_name": {"$regex": season_regex(int(spec["season"])), "$options": "i"}})
    if spec.get("episode") is not None:
        conditions.append({"file_name": {"$regex": episode_regex(int(spec["episode"])), "$options": "i"}})
    if spec.get("language"):
        conditions.append({"file_name": {"$regex": language_regex(str(spec["language"])), "$options": "i"}})
    if spec.get("quality"):
        conditions.append({"file_name": {"$regex": quality_regex(str(spec["quality"])), "$options": "i"}})
    return conditions


def build_strict_filter(spec: Dict[str, object]) -> dict:
    conditions: List[dict] = []
    for token in spec.get("title_tokens", []):
        conditions.append({"file_name": {"$regex": token_regex(str(token)), "$options": "i"}})
    conditions.extend(metadata_conditions(spec))
    return {"$and": conditions} if conditions else {"_id": {"$exists": False}}


def build_fuzzy_candidate_filter(spec: Dict[str, object]) -> Optional[dict]:
    tokens: List[str] = [str(x) for x in spec.get("title_tokens", [])]
    anchors = []
    for token in tokens:
        if len(token) >= 4:
            prefix = re.escape(token[:3])
            anchors.append({"file_name": {"$regex": rf"(?:^|[^a-z0-9]){prefix}[a-z0-9]*", "$options": "i"}})
    if not anchors:
        return None
    conditions = metadata_conditions(spec)
    conditions.append({"$or": anchors})
    return {"$and": conditions} if len(conditions) > 1 else conditions[0]


def _filename_tokens(filename: str) -> List[str]:
    name = normalize_text(filename)
    # Source tags and common file metadata should not dominate typo scoring.
    return [t for t in name.split() if not t.startswith("www") and not t.isdigit()]


def fuzzy_similarity(filename: str, spec: Dict[str, object]) -> float:
    query_tokens: List[str] = [str(x) for x in spec.get("title_tokens", [])]
    if not query_tokens:
        return 0.0
    file_tokens = _filename_tokens(filename)
    if not file_tokens:
        return 0.0

    scores = []
    for q in query_tokens:
        if q in file_tokens:
            scores.append(1.0)
            continue
        best = max((SequenceMatcher(None, q, token).ratio() for token in file_tokens), default=0.0)
        scores.append(best)

    # Do not allow one correct word to hide one completely unrelated word.
    if min(scores, default=0.0) < 0.58:
        return 0.0
    return sum(scores) / len(scores)


def relevance_score(filename: str, spec: Dict[str, object], fuzzy: bool = False) -> float:
    normalized_name = normalize_text(filename)
    title_phrase = str(spec.get("title_phrase") or "")
    title_tokens = [str(x) for x in spec.get("title_tokens", [])]

    score = 0.0
    if title_phrase:
        phrase_pattern = rf"(?:^|\s){re.escape(title_phrase)}(?:$|\s)"
        if re.search(phrase_pattern, normalized_name, flags=re.I):
            score += 120.0
        for token in title_tokens:
            if re.search(token_regex(token), normalized_name, flags=re.I):
                score += 25.0

    if spec.get("year") and re.search(year_regex(str(spec["year"])), normalized_name, flags=re.I):
        score += 30.0
    if spec.get("season") is not None and re.search(season_regex(int(spec["season"])), normalized_name, flags=re.I):
        score += 25.0
    if spec.get("episode") is not None and re.search(episode_regex(int(spec["episode"])), normalized_name, flags=re.I):
        score += 25.0
    if spec.get("language") and re.search(language_regex(str(spec["language"])), normalized_name, flags=re.I):
        score += 12.0
    if spec.get("quality") and re.search(quality_regex(str(spec["quality"])), normalized_name, flags=re.I):
        score += 10.0

    if fuzzy:
        score += fuzzy_similarity(filename, spec) * 100.0
    return score


def fuzzy_accept(filename: str, spec: Dict[str, object]) -> bool:
    return fuzzy_similarity(filename, spec) >= 0.74
