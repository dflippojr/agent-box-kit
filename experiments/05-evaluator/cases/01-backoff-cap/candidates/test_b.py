from target import backoff


def test_candidate():
    assert backoff(5, 3.0, 45) == 45
