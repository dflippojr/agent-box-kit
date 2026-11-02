from target import apply_discount


def test_candidate():
    assert apply_discount(150.0) == 127.5
