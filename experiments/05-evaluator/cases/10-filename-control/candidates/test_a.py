from target import safe_filename


def test_candidate():
    assert safe_filename('report.txt ') == 'report.txt'
