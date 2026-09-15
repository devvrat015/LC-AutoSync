#!/bin/bash
cd "$(dirname "$0")/service" || exit 1
source venv/bin/activate
exec uvicorn main:app --host 127.0.0.1 --port 7337
