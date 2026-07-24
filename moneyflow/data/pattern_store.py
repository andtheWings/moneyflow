"""Persistence for user-defined category patterns and rejected suggestions."""

from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

from .category_patterns import CategoryPattern


class PatternStore:
    """Load and save category patterns and rejection state in a profile directory."""

    CONFIG_FILE = "config.yaml"
    REJECTED_FILE = "rejected_suggestions.yaml"

    def __init__(self, profile_dir: Path):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def _config_path(self) -> Path:
        return self.profile_dir / self.CONFIG_FILE

    def _rejected_path(self) -> Path:
        return self.profile_dir / self.REJECTED_FILE

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_yaml(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def load_patterns(self) -> List[CategoryPattern]:
        """Load enabled patterns from profile config.yaml."""
        config = self._load_yaml(self._config_path())
        raw_patterns = config.get("category_patterns", [])
        if not isinstance(raw_patterns, list):
            return []

        patterns: List[CategoryPattern] = []
        for raw in raw_patterns:
            if not isinstance(raw, dict):
                continue
            fields = raw.get("fields")
            patterns.append(
                CategoryPattern(
                    pattern=str(raw.get("pattern", "")),
                    category=str(raw.get("category", "")),
                    fields=tuple(fields) if isinstance(fields, list) else ("merchant", "description", "notes"),
                    only_when_uncategorized=bool(raw.get("only_when_uncategorized", True)),
                    enabled=bool(raw.get("enabled", True)),
                    description=raw.get("description"),
                )
            )
        return patterns

    def save_patterns(self, patterns: List[CategoryPattern]) -> None:
        """Save patterns back to profile config.yaml, preserving other keys."""
        config = self._load_yaml(self._config_path())
        config["category_patterns"] = [
            {
                "pattern": p.pattern,
                "category": p.category,
                "fields": list(p.fields),
                "only_when_uncategorized": p.only_when_uncategorized,
                "enabled": p.enabled,
                "description": p.description,
            }
            for p in patterns
        ]
        self._save_yaml(self._config_path(), config)

    def load_rejected(self) -> Set[str]:
        """Load set of transaction IDs whose suggestions were rejected."""
        data = self._load_yaml(self._rejected_path())
        raw = data.get("rejected", [])
        return set(raw) if isinstance(raw, list) else set()

    def save_rejected(self, rejected: Set[str]) -> None:
        """Save set of rejected transaction IDs."""
        self._save_yaml(self._rejected_path(), {"rejected": sorted(rejected)})
