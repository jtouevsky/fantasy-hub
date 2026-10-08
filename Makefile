# Fantasy Hub: FastAPI backend + React (Vite) frontend.
PY ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn

.PHONY: setup dev start build test

setup:            ## one-time: Python + Node dependencies
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd web && npm install

dev:              ## backend (:8000, auto-reload) + frontend (:5173, hot reload). Open http://localhost:5173
	@trap 'kill 0' INT TERM EXIT; \
	$(UVICORN) server.main:app --reload --port 8000 & \
	(cd web && npm run dev) & \
	wait

build:            ## production build of the frontend into web/dist
	cd web && npm run build

start: build      ## one process: the API also serves the built frontend. Open http://localhost:8000
	$(UVICORN) server.main:app --port 8000

test:
	$(PY) -m pytest -q
	$(PY) tools/contrast.py > /dev/null
	cd web && npx tsc --noEmit
