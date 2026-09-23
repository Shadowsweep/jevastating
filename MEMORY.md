# Memory & Context Store

## 1. Project Context
- **Objective**: Create a comparative benchmarking platform for Laya (NandhaKishorM) and TypeSafe AI's Jev AI on flight/railway reservation guardrails.
- **Dataset**: `google/air_dialogue` stored locally as `.parquet`.
- **Primary Metrics**: Inference latency ($ms$), Decision Confidence ($P \in [0.0, 1.0]$), and Agreement/Consensus Rate.

## 2. Environment Variables (`.env`)
```bash
# Server Configuration
HOST=127.0.0.1
PORT=8000
ENVIRONMENT=development

# Private Engine Credentials (NEVER EXPOSE TO FRONTEND)
TYPESAFE_API_KEY="your-typesafe-api-key-here"
LAYA_MODEL_PATH="./weights/laya-base.bin"

# Dataset Location
DATASET_PATH="./data/flight_booking_metadata.parquet"
```

## 3. Decision Vector Rules
- **Noul Check**: Binary guardrail filter (`true`/`false`) detecting rule injection.
- **Choice Check**: Routing customer state across `['search', 'book', 'cancel', 'escalate']`.

---

## 4. Active Git Worktrees & Branches
- **Main Branch**: `main` (FastAPI orchestrator, root config)
- **Flight Worktree**: `../arena-flight` on branch `feat/flight-guardrails` (Port 8000)
- **Railway Worktree**: `../arena-railway` on branch `feat/railway-guardrails` (Port 8001)

## 5. Worktree Quick Commands & Runbooks
- **List worktrees**: `git worktree list`
- **Prune deleted worktrees**: `git worktree prune`
- **Remove railway worktree**: `git worktree remove ../arena-railway`

## 6. Quick Decision Matrix
| Item | Destination | Reasoning |
|---|---|---|
| Commit message format (`feat: ...`) | `RULES.md` | Universal rule across every commit. |
| Never commit secrets / `.env` | `RULES.md` | Inviolable security restriction. |
| Current branch name & active worktree paths | `MEMORY.md` | Dynamic workspace state that changes per task. |
| Exact shell commands to spin up arena-railway | `MEMORY.md` | Project-specific reference command / runbook. |
