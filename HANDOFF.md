# Developer Handoff Document

## 1. Prerequisites
- Python 3.11+
- Virtual Environment (`venv` or `uv`)
- `google/air_dialogue` parquet file placed inside `./data/`

## 2. Directory Structure
```text
├── data/
│   └── flight_booking_metadata.parquet
├── static/
│   ├── index.html        <-- Built strictly to DESIGN.md
│   ├── css/
│   └── js/
├── app/
│   ├── __init__.py
│   ├── main.py           <-- FastAPI App & Routes
│   ├── config.py         <-- Env variable loading & validation
│   ├── engines/
│   │   ├── laya_engine.py
│   │   └── jev_engine.py
│   └── data_loader.py    <-- Polars parquet reader
├── .env.example
├── ARCHITECTURE.md
├── BACKEND.md
├── MEMORY.md
├── RULES.md
├── HANDOFF.md
└── requirements.txt
```

## 3. Next Steps
Share your DESIGN.md containing your desired UI/UX rules, layouts, and style tokens.

We will implement static/index.html and app/main.py directly according to those specifications.
