Answers: what data is read and written, in which direction, how records are matched, what the key fields mean.
Read when: you are changing queries, fields or the data flow, or debugging a wrong result.
Basis: read from code at <short sha>, <date>; nothing executed.

# Data model

Shape and meaning only. No data values, no real identifiers.

## Flow direction
```
<source> --> <target>   (read-only / read-write)
```

## Source: `<table or object>`
| Field | Meaning | Used as | Notes |
|---|---|---|---|

## Target: `<table or object>`
| Field | Meaning | Used as | Notes |
|---|---|---|---|

## Matching and keys
<How records are matched. What happens with zero matches, one match, several matches (on both sides).>

## Write path
<How writes are made (ORM, SQL), what conditions cause a write, what causes a skip. Cite the method.>

## Behavior claims that were reasoned, not observed
- <claim> (inferred, not exercised)

## Unknown / owner to confirm
- <item>
