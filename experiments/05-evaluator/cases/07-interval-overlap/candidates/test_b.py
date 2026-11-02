from target import overlaps


def test_candidate():
    assert overlaps(540, 630, 630, 720) is False
