from target import backoff


def test_candidate():
    assert backoff(10, 1.0, 30) == 30
