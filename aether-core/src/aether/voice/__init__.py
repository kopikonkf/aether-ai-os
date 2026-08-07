"""Provider-neutral voice audition contracts and tooling."""

from .adapters import (
    CartesiaTTSAdapter,
    GeminiExactTextTTSAdapter,
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
    VoiceTranscriptionReceipt,
    VoiceTranscriptionRequest,
)
from .policy import (
    BoundedVoicePromptCompiler,
    CompiledVoicePrompt,
    VoiceProfilePolicy,
)
from .runtime import (
    ExactTextVoiceRuntime,
    VoiceDeploymentManifest,
    VoiceRuntimeResult,
    VoiceTurnReceipt,
    VoiceTurnRequest,
)

__all__ = [
    "AuditionCorpusEntry",
    "AuditionRunner",
    "BoundedVoicePromptCompiler",
    "CartesiaTTSAdapter",
    "CompiledVoicePrompt",
    "CredentialResolver",
    "ExactTextVoiceRuntime",
    "GeminiExactTextTTSAdapter",
    "GoogleCloudTTSAdapter",
    "OpenAIExactTextTTSAdapter",
    "OpenAITranscriptionAdapter",
    "VoiceArtifact",
    "VoiceComparisonRecord",
    "VoiceDeploymentManifest",
    "VoiceProfilePolicy",
    "VoiceProvider",
    "VoiceProviderManifest",
    "VoiceRuntimeResult",
    "VoiceSynthesisReceipt",
    "VoiceSynthesisRequest",
    "VoiceTranscriptionReceipt",
    "VoiceTranscriptionRequest",
    "VoiceTurnReceipt",
    "VoiceTurnRequest",
    "write_comparison_sheets",
]
