from target import overlaps


def test_candidate():
    assert overlaps(1, 5, 5, 9) is False
