"""
End-to-End Test: Aether Pipeline
- ToolRegistry with all 8 primitives
- [TOOL] tag parsing + execution
- RuntimeManager integration
- Skills System
- MemoryTool (FTS5)
"""

import tempfile
from pathlib import Path

import pytest
from aether_tools import ToolRegistry
from aether_tools.parser import parse_tool_tags, strip_tool_tags
from aether_tools.primitives import ReadTool, WriteTool, EditTool, GrepTool, GlobTool, MemoryTool
from aether_tools.primitives.bash import BashTool
from aether_tools.primitives.webfetch import WebFetchTool
from aether_tools.skills import SkillManager


@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil
    shutil.rmtree(str(d))


@pytest.fixture
def registry(tmp_dir):
    reg = ToolRegistry()
    reg.register(ReadTool([tmp_dir]))
    reg.register(WriteTool([tmp_dir]))
    reg.register(EditTool([tmp_dir]))
    reg.register(GrepTool([tmp_dir]))
    reg.register(GlobTool([tmp_dir]))
    reg.register(BashTool(cwd=tmp_dir))
    reg.register(WebFetchTool(https_only=False))
    reg.register(MemoryTool(tmp_dir / "test_memory.db"))
    return reg


class TestE2E_ToolPipeline:
    """Test the full [TOOL] pipeline: parse → execute → format result."""

    TOOL_READ = '[TOOL read path="test.txt"][/TOOL]'
    TOOL_BASH = '[TOOL bash cmd="echo hello" timeout=5][/TOOL]'
    TOOL_GREP = '[TOOL grep pattern="hello" path="."][/TOOL]'

    def test_parse_tool_tags(self):
        calls = parse_tool_tags(self.TOOL_READ)
        assert len(calls) == 1
        assert calls[0]["name"] == "read"
        assert calls[0]["args"] == {"path": "test.txt"}

        calls = parse_tool_tags(self.TOOL_BASH)
        assert len(calls) == 1
        assert calls[0]["name"] == "bash"
        assert calls[0]["args"] == {"cmd": "echo hello", "timeout": "5"}

        calls = parse_tool_tags(self.TOOL_GREP)
        assert len(calls) == 1
        assert calls[0]["name"] == "grep"
        assert calls[0]["args"] == {"pattern": "hello", "path": "."}

    def test_strip_tool_tags(self):
        text = "Hello [TOOL read path=x][/TOOL] world"
        result = strip_tool_tags(text)
        assert "Hello" in result
        assert "world" in result
        assert "[TOOL" not in result

    def test_tool_execution_read(self, registry, tmp_dir):
        (tmp_dir / "test.txt").write_text("hello world")
        result = registry.execute("read", path="test.txt")
        assert result.ok
        assert "hello world" in result.output

    def test_tool_execution_write(self, registry, tmp_dir):
        result = registry.execute("write", path="out.txt", _body="hello")
        assert result.ok
        assert (tmp_dir / "out.txt").read_text() == "hello"

    def test_tool_execution_bash(self, registry, tmp_dir):
        result = registry.execute("bash", cmd="echo hello", timeout=5)
        assert result.ok
        assert "hello" in result.output

    def test_tool_execution_grep(self, registry, tmp_dir):
        (tmp_dir / "data.txt").write_text("hello world\nfoo bar")
        result = registry.execute("grep", pattern="hello", path=str(tmp_dir))
        assert result.ok
        assert "data.txt" in result.output

    def test_tool_execution_glob(self, registry, tmp_dir):
        (tmp_dir / "a.py").write_text("")
        (tmp_dir / "b.py").write_text("")
        result = registry.execute("glob", pattern="*.py", path=str(tmp_dir))
        assert result.ok
        assert "a.py" in result.output
        assert "b.py" in result.output

    def test_tool_execution_edit(self, registry, tmp_dir):
        (tmp_dir / "doc.txt").write_text("hello world")
        result = registry.execute("edit", path="doc.txt", find="world", replace="there")
        assert result.ok
        assert (tmp_dir / "doc.txt").read_text() == "hello there"

    def test_tool_execution_memory(self, registry, tmp_dir):
        r = registry.execute("memory", op="store", key="greeting", value="hello world")
        assert r.ok

        r = registry.execute("memory", op="recall", key="greeting")
        assert r.ok
        assert "hello world" in r.output

        r = registry.execute("memory", op="search", query="hello")
        assert r.ok
        assert "greeting" in r.output

    def test_tool_execution_unknown(self, registry):
        result = registry.execute("nonexistent")
        assert not result.ok
        assert "Unknown tool" in result.error

    def test_tool_manifest(self, registry):
        manifest = registry.manifest()
        assert "[TOOL read" in manifest
        assert "[TOOL bash" in manifest
        assert "[TOOL grep" in manifest
        assert "[TOOL memory" in manifest

    def test_pipeline_multiple_tools(self, registry):
        text = """
        Read: [TOOL read path="test.txt"][/TOOL]
        Bash: [TOOL bash cmd="echo hello" timeout=5][/TOOL]
        """
        from aether_tools.parser import strip_tool_tags
        clean = strip_tool_tags(text)
        assert "Read:" in clean
        assert "Bash:" in clean
        assert "[TOOL" not in clean

class TestE2E_Skills:
    def test_skill_manager(self, tmp_dir):
        skills_dir = tmp_dir / "skills"
        skills_dir.mkdir()
        (skills_dir / "debug.md").write_text("""\
---
name: debug
trigger: bug
uses: 10
success_rate: 0.9
---
Debug steps here""")

        sm = SkillManager(skills_dir)
        assert len(sm._skills) == 1

        m = sm.match("there is a bug")
        assert len(m) == 1
        assert m[0].name == "debug"

        m = sm.match("hello world")
        assert len(m) == 0

        suffix = sm.format_prompt_suffix("fix this bug")
        assert "Relevant skills:" in suffix
        assert "debug" in suffix

class TestE2E_Gateway:
    def test_server_module_imports(self):
        import aether_gateway.api.server
        assert aether_gateway.api.server.start_server is not None

    def test_telegram_bot_adapter_imports(self):
        from aether_gateway.adapters.telegram_bot import TelegramBotAdapter
        assert TelegramBotAdapter is not None

    def test_mcp_server_imports(self):
        pytest.importorskip("mcp")
        import aether_gateway.mcp.server
        assert aether_gateway.mcp.server.mcp is not None
