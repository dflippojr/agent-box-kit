def apply_discount(subtotal):
    if subtotal >= 120:
        return round(subtotal * 0.90, 2)
    return subtotal
