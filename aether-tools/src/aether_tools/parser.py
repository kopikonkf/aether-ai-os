import re

TOOL_TAG_RE = re.compile(
    r'\[TOOL\s+(\w+)((?:\s+\w+="[^"]*"|\s+\w+=\S+)*?)\](.*?)\[/TOOL\]',
    re.DOTALL,
)

VOICE_TAG_RE = re.compile(r'\[VOICE\](.*?)\[/VOICE\]', re.DOTALL)
WRITE_TAG_RE = re.compile(r'\[WRITE\s+(.+?)\](.*?)\[/WRITE\]', re.DOTALL)


def _parse_args(raw: str) -> dict:
    args = {}
    for m in re.finditer(r'(\w+)=(?:"([^"]*)"|(\S+))', raw):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        args[key] = val
    return args


def parse_tool_tags(text: str) -> list[dict]:
    calls = []
    for m in TOOL_TAG_RE.finditer(text):
        name, raw_args, body = m.group(1), m.group(2), m.group(3)
        args = _parse_args(raw_args)
        body = body.strip("\n")
        if body:
            args["_body"] = body
        calls.append({
            "name": name,
            "args": args,
            "start": m.start(),
            "end": m.end(),
        })
    return calls


def strip_tool_tags(text: str) -> str:
    result = TOOL_TAG_RE.sub("", text)
    result = VOICE_TAG_RE.sub("", result)
    result = WRITE_TAG_RE.sub("", result)
    return result.strip()
