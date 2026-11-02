from target import safe_filename


def test_candidate():
    assert safe_filename('notes ') == 'notes'
