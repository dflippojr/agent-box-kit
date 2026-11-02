from target import tax


def test_candidate():
    assert tax(250.0) == 20.0
