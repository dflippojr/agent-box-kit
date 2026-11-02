from target import tax


def test_candidate():
    assert tax(1000) == 80.0
