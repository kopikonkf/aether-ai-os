from __future__ import annotations

from aether_gateway.adapters.telegram_presentation import TelegramPresentationAdapter


def test_renders_safe_basic_formatting_and_escapes_raw_html() -> None:
    renderer = TelegramPresentationAdapter()
    rendered = renderer.render(
        "# Status\n\n**Ready** and *stable* with `aether status`.\n"
        "- first\n- second\n\n[Docs](https://example.com) <script>alert(1)</script>"
    )

    assert len(rendered) == 1
    body = rendered[0].text
    assert "<b>Status</b>" in body
    assert "<b>Ready</b>" in body
    assert "<i>stable</i>" in body
    assert "<code>aether status</code>" in body
    assert "• first" in body
    assert '<a href="https://example.com">Docs</a>' in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert rendered[0].parse_mode == "HTML"


def test_rejects_unsafe_link_schemes() -> None:
    renderer = TelegramPresentationAdapter()
    body = renderer.render("[click](javascript:alert(1))")[0].text
    assert "<a " not in body
    assert "javascript:alert" in body


def test_splits_long_messages_and_preserves_fenced_code_shape() -> None:
    renderer = TelegramPresentationAdapter(message_limit=900)
    source = "Intro\n\n```python\n" + ("print('hello')\n" * 200) + "```\n\nDone"
    messages = renderer.render(source)

    assert len(messages) > 1
    assert all(len(item.text) <= 900 for item in messages)
    code_messages = [item for item in messages if "<pre><code" in item.text]
    assert code_messages
    assert all(item.text.count("<pre><code") == item.text.count("</code></pre>") for item in code_messages)


def test_capability_snapshot_does_not_claim_structured_rich_messages() -> None:
    snapshot = TelegramPresentationAdapter().capability_snapshot()
    assert snapshot["approval_buttons"] is True
    assert snapshot["basic_formatting"] is True
    assert snapshot["structured_rich_messages"] is False
    assert snapshot["streaming"] is False
