"""Provider-neutral voice audition contracts and tooling."""

from .adapters import (
    CartesiaTTSAdapter,
    GoogleCloudTTSAdapter,
    OpenAIExactTextTTSAdapter,
    OpenAITranscriptionAdapter,
)
from .audition import AuditionRunner, write_comparison_sheets
from .contracts import (
    AuditionCorpusEntry,
    CredentialResolver,
    VoiceArtifact,
    VoiceComparisonRecord,
    VoiceProvider,
    VoiceProviderManifest,
    VoiceSynthesisReceipt,
    VoiceSynthesisRequest,
    VoiceTranscriptionRequest,
    VoiceTranscriptionReceipt,
)

__all__ = [
    "AuditionCorpusEntry",
    "AuditionRunner",
    "CartesiaTTSAdapter",
    "CredentialResolver",
    "GoogleCloudTTSAdapter",
    "OpenAIExactTextTTSAdapter",
    "OpenAITranscriptionAdapter",
    "VoiceArtifact",
    "VoiceComparisonRecord",
    "VoiceProvider",
    "VoiceProviderManifest",
    "VoiceSynthesisReceipt",
    "VoiceSynthesisRequest",
    "VoiceTranscriptionRequest",
    "VoiceTranscriptionReceipt",
    "write_comparison_sheets",
]
