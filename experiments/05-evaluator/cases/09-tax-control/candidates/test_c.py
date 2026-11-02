from target import tax


def test_candidate():
    assert tax(99.99) == 8.0
