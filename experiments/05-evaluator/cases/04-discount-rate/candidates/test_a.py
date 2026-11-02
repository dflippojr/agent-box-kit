from target import apply_discount


def test_candidate():
    assert apply_discount(200) == 170.0
