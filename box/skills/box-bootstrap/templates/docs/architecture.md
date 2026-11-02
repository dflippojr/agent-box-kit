Answers: how the application is structured, which components exist, how they are wired, what it depends on.
Read when: you need the overall shape before making a change.
Basis: read from code at <short sha>, <date>; nothing executed.

# Architecture

## What it is
<Type of application, entry point (`path/to/EntryPoint`), what it does in two sentences.>

## Components
| Component | Role | Where |
|---|---|---|
| `<Class or module>` | <what it owns> | `<path>` |

## How it is wired
<Configuration, dependency injection, multiple data sources or clients. Cite paths.>

## External dependencies
| Dependency | Provides | Owner (repo or team) | What to read there |
|---|---|---|---|
| `<lib or service>` | <what> | <who> | <path, or "unknown: ask <person>"> |

## Startup sequence
1. <step> (`<path>`)

## Unknown / owner to confirm
- <item>
