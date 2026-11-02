from target import parse_size


def test_candidate():
    assert parse_size('10MB') == 10000000
