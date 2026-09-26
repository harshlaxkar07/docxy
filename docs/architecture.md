# System Architecture

## Core Architectural Principles

1. **Database-Backed Persistent Queueing**: Every job exists as a record in SQLite with unambiguous state transitions. FastAPI request handlers remain thin and return immediately after committing the initial record.
2. **Crash Resilience & Resumability**: If the server or worker crashes, jobs are detected via stale heartbeats on startup and resumed from the last checkpointed page rather than reprocessing from page 1.
3. **Native-First Efficiency**: Evaluating text density and character count ensures that digital pages (the vast majority of documents) are parsed in milliseconds via PyMuPDF without triggering Vision API latency or costs.
4. **Clean Abstractions**: S3 storage and Groq Vision providers are decoupled behind interface boundaries, allowing the system to run locally without cloud credentials.
5. **Persistent Rate Limiting**: Multi-window rate limiting stored in SQLite ensures that external API limits are respected across process restarts.

## Component Layout

```
app/
├── api/                  # FastAPI routers and route dependencies
│   └── routes/           # health, documents, jobs, settings
├── constants/            # Enum definitions for statuses and error codes
├── core/                 # Configuration, logging with secret masking, exceptions
├── db/                   # SQLite database manager, migrations, and repositories
│   └── repositories/     # Thin data access layer for documents, jobs, pages, results, logs, usage, rate limits
├── schemas/              # Pydantic request and response models
├── services/             # Core business logic: PDF inspection, extraction, OCR, S3, TXT aggregation, temp manager
├── utils/                # Hashing, file utilities, retry with exponential backoff
└── workers/              # Background polling worker, task processor, and crash recovery service
```
