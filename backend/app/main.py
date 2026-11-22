"""서버 진입점.  실행: .venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000"""
from app.api.app import create_app

app = create_app()
