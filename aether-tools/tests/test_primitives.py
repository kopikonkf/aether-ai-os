import tempfile
from pathlib import Path

from aether_tools.base import Tool, ToolResult
from aether_tools.registry import ToolRegistry
from aether_tools.parser import parse_tool_tags, strip_tool_tags
from aether_tools.primitives.write import WriteTool
from aether_tools.primitives.read import ReadTool
from aether_tools.primitives.edit import EditTool
from aether_tools.primitives.grep import GrepTool
from aether_tools.primitives.glob import GlobTool
from aether_tools.primitives.bash import BashTool


class MockTool(Tool):
    name = "test"
    spec = 'msg="hello"'
    def __call__(self, msg="", **kw):
        return ToolResult(True, f"echo: {msg}")


class TestRegistry:
    def test_register_and_get(self):
        r = ToolRegistry()
        t = MockTool()
        r.register(t)
        assert r.get("test") is t
        assert r.get("nope") is None

    def test_execute(self):
        r = ToolRegistry()
        r.register(MockTool())
        res = r.execute("test", msg="halo")
        assert res.ok
        assert "halo" in res.output

    def test_execute_unknown(self):
        r = ToolRegistry()
        res = r.execute("nope")
        assert not res.ok
        assert "Unknown tool" in res.error

    def test_manifest(self):
        r = ToolRegistry()
        r.register(MockTool())
        m = r.manifest()
        assert "[TOOL test" in m
        assert "msg=" in m


class TestParser:
    def test_parse_simple(self):
        text = "[TOOL read path=test.txt][/TOOL]"
        calls = parse_tool_tags(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "read"
        assert calls[0]["args"]["path"] == "test.txt"

    def test_parse_with_body(self):
        text = "[TOOL write path=out.md]\nHello World\n[/TOOL]"
        calls = parse_tool_tags(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "write"
        assert calls[0]["args"]["_body"] == "Hello World"

    def test_parse_quoted_args(self):
        text = '[TOOL grep pattern="hello world" path=src/][/TOOL]'
        calls = parse_tool_tags(text)
        assert calls[0]["args"]["pattern"] == "hello world"
        assert calls[0]["args"]["path"] == "src/"

    def test_strip(self):
        text = "hello [TOOL read path=x][/TOOL] world"
        assert strip_tool_tags(text) == "hello  world"

    def test_voice_tag(self):
        text = "ok [VOICE]halo[/VOICE]"
        from aether_tools.parser import VOICE_TAG_RE
        m = VOICE_TAG_RE.search(text)
        assert m and m.group(1) == "halo"

    def test_write_tag(self):
        text = "[WRITE test.md]content[/WRITE]"
        from aether_tools.parser import WRITE_TAG_RE
        m = WRITE_TAG_RE.search(text)
        assert m and m.group(1) == "test.md" and m.group(2) == "content"


class TestReadWriteEdit:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.write_roots = [self.tmpdir]
        self.read_roots = [self.tmpdir]

    def test_write_and_read(self):
        w = WriteTool(self.write_roots)
        r = ReadTool(self.read_roots)

        target = str(self.tmpdir / "hello.txt")
        res = w(path=target, _body="Hello World")
        assert res.ok
        assert (self.tmpdir / "hello.txt").exists()

        res = r(path=target)
        assert res.ok
        assert "Hello World" in res.output

    def test_write_outside_scope(self):
        w = WriteTool(self.write_roots)
        res = w(path=str(Path.home() / "secret.txt"), _body="hack")
        assert not res.ok
        assert "denied" in res.error

    def test_edit(self):
        e = EditTool(self.write_roots)
        w = WriteTool(self.write_roots)
        target = str(self.tmpdir / "edit.txt")
        w(path=target, _body="foo bar baz")
        res = e(path=target, find="bar", replace="qux")
        assert res.ok
        text = (self.tmpdir / "edit.txt").read_text()
        assert "foo qux baz" in text

    def test_write_relative_path(self):
        w = WriteTool(self.write_roots)
        r = ReadTool(self.read_roots)
        res = w(path="relative.txt", _body="relative path test")
        assert res.ok
        assert (self.tmpdir / "relative.txt").exists()
        res = r(path="relative.txt")
        assert res.ok
        assert "relative path test" in res.output


class TestSearch:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / "sub").mkdir()
        (self.tmpdir / "sub" / "a.py").write_text("def hello(): pass\nx = 1\n")
        (self.tmpdir / "sub" / "b.py").write_text("def world(): pass\n")
        self.read_roots = [self.tmpdir]

    def test_grep(self):
        g = GrepTool(self.read_roots)
        res = g(pattern="hello", path=str(self.tmpdir))
        assert res.ok
        assert "hello" in res.output

    def test_glob(self):
        g = GlobTool(self.read_roots)
        res = g(pattern="*.py", path=str(self.tmpdir))
        assert res.ok
        assert "a.py" in res.output or "b.py" in res.output


class TestBash:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_echo(self):
        b = BashTool(cwd=self.tmpdir)
        res = b(cmd="echo hello")
        assert res.ok
        assert "hello" in res.output

    def test_blocked(self):
        b = BashTool(cwd=self.tmpdir, blocked=["rm"])
        res = b(cmd="rm -rf /")
        assert not res.ok
        assert "blocked" in res.error

    def test_fail(self):
        b = BashTool(cwd=self.tmpdir)
        res = b(cmd="exit 1")
        assert not res.ok


class TestToolResult:
    def test_defaults(self):
        r = ToolResult(ok=True, output="ok")
        assert r.error is None
        assert r.data is None

    def test_with_error(self):
        r = ToolResult(ok=False, output="", error="fail")
        assert r.error == "fail"


class TestToolBehavior:
    def test_subclass(self):
        class MyTool(Tool):
            name = "my"
            spec = "x=1"
            def __call__(self, **kw):
                return ToolResult(True, "done")
        t = MyTool()
        assert t.name == "my"
        res = t()
        assert res.ok


def test_write_accepts_native_content_argument(tmp_path: Path):
    tool = WriteTool([tmp_path])
    result = tool(path="native.md", content="native function payload")
    assert result.ok
    assert (tmp_path / "native.md").read_text(encoding="utf-8") == "native function payload"
    assert result.data["disposition"] == "created"
    assert result.data["size"] == len("native function payload".encode("utf-8"))
    assert len(result.data["sha256"]) == 64

    overwritten = tool(path="native.md", content="updated")
    assert overwritten.ok
    assert overwritten.data["disposition"] == "overwritten"
    assert (tmp_path / "native.md").read_text(encoding="utf-8") == "updated"


def test_registry_preflight_is_side_effect_free(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(WriteTool([tmp_path]))
    result = registry.validate("write", path="proof.md", content="hello")
    assert result.ok
    assert not (tmp_path / "proof.md").exists()
