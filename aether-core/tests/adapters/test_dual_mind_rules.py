from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[2]


def test_body_silence_disables_background_review():
    text = (CORE_ROOT / "configs/body_silence.yaml").read_text(encoding="utf-8")
    assert "background_review" in text
    assert "enabled: false" in text


def test_soul_projection_forbids_hand_edit_banner():
    from aether.adapters.projection import project_soul
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = project_soul(Path(d))
        assert "DO NOT EDIT" in p.read_text(encoding="utf-8")


def test_memory_projection_has_no_belief_section_as_facts():
    from aether.adapters.projection import project_memory
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = project_memory(Path(d), facts=["tool path /x"])
        t = p.read_text(encoding="utf-8")
        assert "no beliefs" in t.lower() or "BELIEF" in t
