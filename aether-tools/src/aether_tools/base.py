from dataclasses import dataclass


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict | None = None
    error: str | None = None


class Tool:
    name: str = ""
    spec: str = ""

    def validate(self, **kwargs) -> ToolResult:
        """Validate arguments and policy scope without producing side effects."""
        return ToolResult(True, "Tool arguments accepted.")

    def __call__(self, **kwargs) -> ToolResult:
        raise NotImplementedError
