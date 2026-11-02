from target import parse_size


def test_candidate():
    assert parse_size('1GB') == 1000000000
