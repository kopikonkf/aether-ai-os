import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Skill:
    name: str
    trigger: str
    uses: int = 0
    success_rate: float = 0.0
    description: str = ""


class SkillManager:
    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._skills: list[Skill] = []
        self._load()

    def _load(self):
        if not self.skills_dir.is_dir():
            self._skills = []
            return
        for f in sorted(self.skills_dir.glob("**/*.md")):
            skill = self._parse(f)
            if skill:
                self._skills.append(skill)

    def _parse(self, path: Path) -> Optional[Skill]:
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = self._parse_frontmatter(text)
        if not fm:
            return None
        return Skill(
            name=fm.get("name", path.stem),
            trigger=fm.get("trigger", ""),
            uses=fm.get("uses", 0),
            success_rate=fm.get("success_rate", 0.0),
            description=self._strip_frontmatter(text),
        )

    def _parse_frontmatter(self, text: str) -> Optional[dict]:
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not m:
            return None
        try:
            return yaml.safe_load(m.group(1))
        except Exception:
            return None

    def _strip_frontmatter(self, text: str) -> str:
        return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL).strip()

    def match(self, prompt: str, top_k: int = 3) -> list[Skill]:
        if not self._skills:
            return []
        scored = []
        prompt_lower = prompt.lower()
        for s in self._skills:
            if not s.trigger:
                continue
            trigger_lower = s.trigger.lower()
            trigger_words = trigger_lower.split()
            if not trigger_words:
                continue
            matched = sum(1 for tw in trigger_words if tw in prompt_lower)
            if matched:
                overlap = matched / len(trigger_words)
                score = s.success_rate * s.uses * overlap
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def format_prompt_suffix(self, prompt: str, top_k: int = 3) -> str:
        matched = self.match(prompt, top_k=top_k)
        if not matched:
            return ""
        lines = ["", "Relevant skills:", "---"]
        for s in matched:
            lines.append(f"- {s.name}: {s.description[:200]}")
        return "\n".join(lines)

    def reload(self):
        self._skills = []
        self._load()
