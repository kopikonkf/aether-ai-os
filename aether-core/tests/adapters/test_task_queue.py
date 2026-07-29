from pathlib import Path
from aether.adapters.task_queue import TaskQueue


def test_enqueue_and_list(tmp_path: Path):
    q = TaskQueue(tmp_path)
    tid = q.enqueue(goal="scan market niches", max_amount_usd=0)
    assert tid
    items = q.list_pending()
    assert len(items) == 1
    assert items[0]["goal"] == "scan market niches"


def test_mark_done(tmp_path: Path):
    q = TaskQueue(tmp_path)
    tid = q.enqueue(goal="x")
    q.complete(tid, result="ok")
    assert q.list_pending() == []
