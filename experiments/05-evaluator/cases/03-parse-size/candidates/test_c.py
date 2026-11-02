from target import parse_size


def test_candidate():
    assert parse_size('2.5GB') == 2500000000
