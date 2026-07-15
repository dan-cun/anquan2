from ledger.jsonl_store import JsonlLedgerStore


def test_ledger_hash_chain(tmp_path):
    store = JsonlLedgerStore(tmp_path, snapshot_interval=2)
    first = store.append("flow-1", event_type="one", actor="test", payload={"n": 1})
    second = store.append("flow-1", event_type="two", actor="test", payload={"n": 2})

    assert first.seq == 1
    assert second.seq == 2
    assert second.prev_hash == first.hash

    verification = store.verify("flow-1")
    assert verification.valid is True
    assert verification.entries_checked == 2
    assert verification.anchors_checked == 1


def test_ledger_after_sequence_cursor(tmp_path):
    store = JsonlLedgerStore(tmp_path)
    for number in range(1, 4):
        store.append("flow-1", event_type="item", actor="test", payload={"n": number})

    entries = store.list_entries("flow-1", after_sequence=1)

    assert [entry.seq for entry in entries] == [2, 3]
