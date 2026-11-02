from target import backoff


def test_candidate():
    assert backoff(4, 2.0, 20) == 20
