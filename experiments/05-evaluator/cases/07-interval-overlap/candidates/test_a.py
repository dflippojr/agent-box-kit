from target import overlaps


def test_candidate():
    assert overlaps(0, 10, 10, 20) is False
