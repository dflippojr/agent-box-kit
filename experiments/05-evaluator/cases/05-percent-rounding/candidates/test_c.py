from target import fmt_percent


def test_candidate():
    assert fmt_percent(0.0625) == '6.3%'
