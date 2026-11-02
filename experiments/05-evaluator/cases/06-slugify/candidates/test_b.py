from target import slugify


def test_candidate():
    assert slugify('Hello, World!') == 'hello-world'
