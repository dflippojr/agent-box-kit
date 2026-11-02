from target import slugify


def test_candidate():
    assert slugify('Q3 Report - Final (v2)') == 'q3-report-final-v2'
