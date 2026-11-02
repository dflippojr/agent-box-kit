UNITS = {'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3}


def parse_size(text):
    for unit, factor in UNITS.items():
        if text.endswith(unit):
            return int(float(text[:-len(unit)]) * factor)
    return int(text)
