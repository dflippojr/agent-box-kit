from target import safe_filename


def test_candidate():
    assert safe_filename('a/b ') == 'a_b'
