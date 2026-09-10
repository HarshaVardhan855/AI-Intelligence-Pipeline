import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from ai_pipeline.schemas import EntityMapping


def normalize_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    value = re.sub(r"\b(incorporated|inc|corp|corporation|llc|ltd|limited|company|co)\b", " ", value)
    return re.sub(r"\s+", "", value)


class EntityResolver:
    def __init__(self, seed_path: Path):
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        self.canonical = {normalize_name(item["canonical"]): item["canonical"] for item in data}
        self.aliases = {normalize_name(alias): item["canonical"] for item in data for alias in item.get("aliases", [])}

    def resolve(self, raw_name: str) -> EntityMapping:
        key = normalize_name(raw_name)
        if key in self.canonical:
            return EntityMapping(raw_name=raw_name, canonical_name=self.canonical[key], resolution_method="exact", confidence=1.0)
        if key in self.aliases:
            return EntityMapping(raw_name=raw_name, canonical_name=self.aliases[key], resolution_method="alias", confidence=0.99)
        candidates = [(SequenceMatcher(None, key, known).ratio(), value) for known, value in self.canonical.items()]
        score, value = max(candidates, default=(0, None))
        if score >= 0.93:
            return EntityMapping(raw_name=raw_name, canonical_name=value, resolution_method="fuzzy", confidence=round(score, 3))
        return EntityMapping(raw_name=raw_name, canonical_name=None, resolution_method="unresolved", confidence=round(score, 3))
