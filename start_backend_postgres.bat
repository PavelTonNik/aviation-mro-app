@echo off
REM Start backend using PostgreSQL connection string
IF "%DATABASE_URL%"=="" (
  echo Please set DATABASE_URL environment variable, e.g.
  echo   set DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/engapp
  echo Or edit this script to hardcode it.
  goto :run
)
:run
cd backend
python -m uvicorn main:app --reload
