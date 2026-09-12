from agentic_trade.execution.ids import MAX_LEN, new_client_order_id


def test_ids_are_venue_legal():
    for intent in (1, 42, 999_999, 2**31):
        cid = new_client_order_id(intent, "ENTRY")
        assert cid.isalnum() and 1 <= len(cid) <= MAX_LEN


def test_ids_are_unique_across_calls():
    ids = {new_client_order_id(7, "ENTRY") for _ in range(500)}
    assert len(ids) == 500


def test_purpose_is_encoded():
    assert new_client_order_id(5, "ENTRY") != new_client_order_id(5, "STOP")
    assert new_client_order_id(5, "STOP")[:4] == new_client_order_id(5, "STOP")[:4]
