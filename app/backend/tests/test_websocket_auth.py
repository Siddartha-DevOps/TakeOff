from websocket_auth import bearer_from_subprotocol_header


def test_token_is_read_from_websocket_subprotocol_header():
    assert bearer_from_subprotocol_header("takeoff-auth, abc.def.ghi") == "abc.def.ghi"


def test_missing_or_malformed_protocol_is_rejected():
    assert bearer_from_subprotocol_header(None) is None
    assert bearer_from_subprotocol_header("abc.def.ghi") is None
    assert bearer_from_subprotocol_header("wrong, abc.def.ghi") is None
    assert bearer_from_subprotocol_header("takeoff-auth, one, two") is None
