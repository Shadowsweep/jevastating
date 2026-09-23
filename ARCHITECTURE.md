# Architecture Specification: Guardrail Arena

## 1. System Topology
The platform consists of a three-tier asynchronous architecture:
- **Presentation Layer**: Client UI built per `DESIGN.md` consuming JSON over HTTP/SSE.
- **Application & Ingestion Gateway (FastAPI)**: Coordinates asynchronous batch execution, enforces rate limits, proxies upstream AI calls, and keeps credentials private.
- **Inference Adapters**:
  - `Laya Engine Adapter`: Direct in-process or local C++/Python bindings.
  - `Jev AI Adapter`: Secure outbound HTTPS worker connecting to TypeSafe AI's endpoint via server-held API tokens.
- **Storage & Ingestion**:
  - Parquet dataset loaded via **Polars** with memory-mapped (`mmap`) reads.
  - SQLite/DuckDB caching layer for benchmarking metrics.

```text
   +-------------------------------------------------------+
   |                  Client Browser (UI)                  |
   +-------------------------------------------------------+
                              |
               HTTPS / JSON   |   (No API Keys Exposed)
                              v
   +-------------------------------------------------------+
   |             FastAPI Gateway (Port 8000)               |
   |  - API Key Masking & Vault    - Input Validation       |
   |  - Concurrency Limiter        - Benchmark Logger       |
   +-------------------------------------------------------+
                |                             |
  (Local IPC / In-Process)          (Outbound TLS / Auth Header)
                |                             |
                v                             v
   +-------------------------+   +-------------------------+
   |   Laya Decision Engine  |   |   TypeSafe Jev AI API   |
   |     (Sub-40ms Noul)     |   |     (System-1 Cloud)    |
   +-------------------------+   +-------------------------+
                \                             /
                 \                           /
                  v                         v
   +-------------------------------------------------------+
   |               Polars Parquet Data Store               |
   |             (Air Dialogue / Railway PNRs)             |
   +-------------------------------------------------------+
```

## 2. Security Boundaries & Zero-Exposure Policy
1. **No Keys in Client**: Under no circumstance is the TypeSafe API token, OpenCode token, or any upstream credential sent to the browser.
2. **Server-Side Key Injection**: Outbound client calls inject the authorization header inside FastAPI using environment variables (`TYPESAFE_API_KEY`).
3. **Payload Sanitization**: Incoming user prompts are truncated to 4,000 characters and stripped of null bytes prior to execution.
4. **CORS Isolation**: CORS is locked strictly to explicit local and deployed origins.
