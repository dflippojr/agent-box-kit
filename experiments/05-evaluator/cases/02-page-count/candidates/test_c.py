from target import page_count


def test_candidate():
    assert page_count(25, 10) == 3
