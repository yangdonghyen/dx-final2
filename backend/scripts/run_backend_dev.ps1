# Starts the FastAPI dev backend (no --reload) with UTF-8 console output.
Set-Location $PSScriptRoot\..
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -u -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug --access-log
