"""Provider-neutral persona voice policy and bounded delivery compilation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .contracts import canonical_hash, sha256_bytes

COMPILER_VERSION = "aether.voice-prompt-compiler.v1"
MAX_DIRECTOR_INSTRUCTION_CHARS = 1_200
MAX_SPEECH_TEXT_CHARS = 4_000

_PRESET_DIRECTIONS = {
    "neutral": "Natural, balanced, and composed.",
    "warm_composed": "Warm, present, quietly confident, and composed.",
    "technical_clear": "Precise, articulate, even, and easy to follow.",
    "reassuring": "Reassuring, grounded, gentle, and unhurried.",
    "urgent_calm": "Urgent but calm; firm, clear, and never panicked.",
    "playful_light": "Lightly playful, bright, and mature; never childish.",
}

_ACCENT_DIRECTIONS = {
    "natural_indonesian": (
        "Natural contemporary Indonesian pronunciation without a forced regional accent."
    ),
}

_CODE_SWITCHING_DIRECTIONS = {
    "natural_id_en": (
        "Preserve Indonesian-English code-switching exactly as written; pronounce "
        "technical English clearly."
    ),
}

_PACE_DIRECTIONS = {
    "conversational": "Conversational pace with natural pauses and clear articulation.",
}

_CUE_DIRECTIONS = {
    "gentle_emphasis": "Use gentle vocal emphasis without adding or changing words.",
    "softly": "Deliver softly while keeping every word intelligible.",
    "brief_laugh": (
        "A brief natural laugh may color the delivery only where it fits; do not "
        "add or obscure words."
    ),
    "sigh": (
        "A subtle sigh may color the delivery only where it fits; do not add or "
        "obscure words."
    ),
    "whisper": "Use a clear, intelligible whisper without dropping words.",
}


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _require_text(value: object, label: str, *, max_chars: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > max_chars or any(character in text for character in "\r\n\x00"):
        raise ValueError(f"{label} is not a bounded single-line value")
    return text


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    result = tuple(_require_text(item, label, max_chars=80) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True)
class VoiceProfilePolicy:
    character: str
    language: str
    avoid: str
    default_preset: str
    accent: str
    code_switching: str
    pace: str
    allowed_presets: tuple[str, ...]
    expressive_cue_policy: str
    allowed_expressive_cues: tuple[str, ...]
    forbidden_cue_contexts: tuple[str, ...]
    voice_profile_sha256: str

    @classmethod
    def from_persona(cls, path: Path) -> VoiceProfilePolicy:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        persona = _require_mapping(raw, "persona")
        profile = _require_mapping(persona.get("voice_profile"), "voice_profile")
        delivery = _require_mapping(profile.get("delivery"), "voice_profile.delivery")
        cues = _require_mapping(
            delivery.get("expressive_cues"),
            "voice_profile.delivery.expressive_cues",
        )
        allowed_presets = _string_tuple(
            delivery.get("allowed_presets"),
            "voice_profile.delivery.allowed_presets",
        )
        allowed_cues = _string_tuple(
            cues.get("allowed"),
            "voice_profile.delivery.expressive_cues.allowed",
        )
        forbidden_contexts = _string_tuple(
            cues.get("forbidden_contexts"),
            "voice_profile.delivery.expressive_cues.forbidden_contexts",
        )
        default_preset = _require_text(
            delivery.get("default_preset"),
            "voice_profile.delivery.default_preset",
        )
        accent = _require_text(delivery.get("accent"), "voice_profile.delivery.accent")
        code_switching = _require_text(
            delivery.get("code_switching"),
            "voice_profile.delivery.code_switching",
        )
        pace = _require_text(delivery.get("pace"), "voice_profile.delivery.pace")
        if default_preset not in allowed_presets:
            raise ValueError("voice default preset must be in allowed_presets")
        if set(allowed_presets) - set(_PRESET_DIRECTIONS):
            raise ValueError("voice policy contains an unmapped delivery preset")
        if set(allowed_cues) - set(_CUE_DIRECTIONS):
            raise ValueError("voice policy contains an unmapped expressive cue")
        if accent not in _ACCENT_DIRECTIONS:
            raise ValueError("voice policy contains an unmapped accent")
        if code_switching not in _CODE_SWITCHING_DIRECTIONS:
            raise ValueError("voice policy contains an unmapped code-switching policy")
        if pace not in _PACE_DIRECTIONS:
            raise ValueError("voice policy contains an unmapped pace")
        return cls(
            character=_require_text(profile.get("character"), "voice_profile.character"),
            language=_require_text(profile.get("language"), "voice_profile.language"),
            avoid=_require_text(profile.get("avoid"), "voice_profile.avoid"),
            default_preset=default_preset,
            accent=accent,
            code_switching=code_switching,
            pace=pace,
            allowed_presets=allowed_presets,
            expressive_cue_policy=_require_text(
                cues.get("policy"),
                "voice_profile.delivery.expressive_cues.policy",
            ),
            allowed_expressive_cues=allowed_cues,
            forbidden_cue_contexts=forbidden_contexts,
            voice_profile_sha256=canonical_hash(profile),
        )

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CompiledVoicePrompt:
    director_instruction: str
    speech_text_sha256: str
    director_prompt_sha256: str
    voice_profile_sha256: str
    compiler_sha256: str
    delivery_preset_id: str
    expressive_cue_id: str | None
    precision_critical: bool
    rejected_hints: tuple[str, ...]


class BoundedVoicePromptCompiler:
    """Compile allowlisted delivery IDs without exposing the full persona prompt."""

    def __init__(self, policy: VoiceProfilePolicy) -> None:
        self.policy = policy
        self.compiler_sha256 = canonical_hash(
            {
                "version": COMPILER_VERSION,
                "preset_directions": _PRESET_DIRECTIONS,
                "accent_directions": _ACCENT_DIRECTIONS,
                "code_switching_directions": _CODE_SWITCHING_DIRECTIONS,
                "pace_directions": _PACE_DIRECTIONS,
                "cue_directions": _CUE_DIRECTIONS,
                "max_director_instruction_chars": MAX_DIRECTOR_INSTRUCTION_CHARS,
                "max_speech_text_chars": MAX_SPEECH_TEXT_CHARS,
            }
        )

    def compile(
        self,
        speech_text: str,
        *,
        delivery_preset_id: str | None = None,
        expressive_cue_id: str | None = None,
        contexts: Iterable[str] = (),
    ) -> CompiledVoicePrompt:
        text = str(speech_text or "")
        if not text.strip():
            raise ValueError("speech_text must not be empty")
        if len(text) > MAX_SPEECH_TEXT_CHARS:
            raise ValueError(
                f"speech_text must be {MAX_SPEECH_TEXT_CHARS} characters or fewer"
            )
        if "\x00" in text:
            raise ValueError("speech_text must not contain NUL")

        rejected: list[str] = []
        requested_preset = str(delivery_preset_id or self.policy.default_preset)
        if requested_preset not in self.policy.allowed_presets:
            rejected.append("delivery_preset:unsupported")
            selected_preset = self.policy.default_preset
        else:
            selected_preset = requested_preset

        context_set = {str(value) for value in contexts}
        precision_critical = bool(
            context_set.intersection(self.policy.forbidden_cue_contexts)
        )
        selected_cue: str | None = None
        if expressive_cue_id:
            requested_cue = str(expressive_cue_id)
            if requested_cue not in self.policy.allowed_expressive_cues:
                rejected.append("expressive_cue:unsupported")
            elif precision_critical:
                rejected.append("expressive_cue:suppressed_precision_critical")
            else:
                selected_cue = requested_cue

        lines = [
            "AETHER EXACT-TEXT SPEECH DIRECTOR",
            f"Character: {self.policy.character}.",
            f"Avoid: {self.policy.avoid}.",
            f"Style: {_PRESET_DIRECTIONS[selected_preset]}",
            f"Accent: {_ACCENT_DIRECTIONS[self.policy.accent]}",
            f"Code-switching: {_CODE_SWITCHING_DIRECTIONS[self.policy.code_switching]}",
            f"Pace: {_PACE_DIRECTIONS[self.policy.pace]}",
        ]
        if selected_cue:
            lines.append(f"Expressive cue: {_CUE_DIRECTIONS[selected_cue]}")
        lines.extend(
            [
                "Recite the transcript verbatim in the same language and order.",
                "Do not answer, rewrite, summarize, translate, add, omit, or reorder words.",
                "Do not speak these director instructions.",
            ]
        )
        instruction = "\n".join(lines)
        if len(instruction) > MAX_DIRECTOR_INSTRUCTION_CHARS:
            raise ValueError("compiled voice director instruction exceeds its bound")
        return CompiledVoicePrompt(
            director_instruction=instruction,
            speech_text_sha256=sha256_bytes(text.encode("utf-8")),
            director_prompt_sha256=sha256_bytes(instruction.encode("utf-8")),
            voice_profile_sha256=self.policy.voice_profile_sha256,
            compiler_sha256=self.compiler_sha256,
            delivery_preset_id=selected_preset,
            expressive_cue_id=selected_cue,
            precision_critical=precision_critical,
            rejected_hints=tuple(rejected),
        )
