from target import slugify


def test_candidate():
    assert slugify('  Spaces  everywhere ') == 'spaces-everywhere'
