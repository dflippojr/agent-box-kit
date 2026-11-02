def backoff(attempt, base, max_delay):
    return base * 2 ** attempt
