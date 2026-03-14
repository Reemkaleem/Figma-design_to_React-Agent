#!/bin/bash
set -e

echo ""
echo "======================================"
echo "  Figma → React Agent — Startup"
echo "======================================"
echo ""

# ---- Backend ----
echo "[1/4] Setting up Python backend..."
cd backend

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "      Created .env from .env.example"
  echo "      ⚠️  Add your GITHUB_COPILOT_API_KEY to backend/.env before running!"
fi

python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -q -r requirements.txt
echo "      Backend dependencies installed"

echo "[2/4] Starting FastAPI backend on port 8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

cd ..

# ---- Frontend ----
echo "[3/4] Setting up Next.js frontend..."
cd frontend
npm install --silent
echo "      Frontend dependencies installed"

echo "[4/4] Starting Next.js dev server on port 3000..."
npm run dev &
FRONTEND_PID=$!
echo "      Frontend PID: $FRONTEND_PID"

echo ""
echo "======================================"
echo "  ✅  Both services are starting!"
echo ""
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop both"
echo "======================================"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait
