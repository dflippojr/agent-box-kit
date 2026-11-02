# Incident excerpt

```
WARN retry attempt=5 base=3.0 max_delay=45 delay=96.0
```

Spec: the delay must never exceed max_delay. The log line above shows it did; the delay should have been 45.
