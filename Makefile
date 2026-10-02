.PHONY: install build run dev dev-backend dev-frontend test lint desktop

ROOT := $(abspath .)
DESKTOP_FILE := $(HOME)/.local/share/applications/smart-meeting.desktop

install: ## Install backend (with CUDA libs) and frontend dependencies, then build the UI
	cd backend && uv sync --extra cuda
	cd frontend && npm ci
	$(MAKE) build

build: ## Build the frontend, served by the backend in normal mode
	cd frontend && npm run build

run: ## Normal mode: one process, opens the app window
	./smart-meeting

dev: ## Development: backend with auto-reload + Vite dev server (http://127.0.0.1:5173)
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uv run --extra cuda uvicorn smart_meeting.main:app --host 127.0.0.1 --port 8000 --reload

dev-frontend:
	cd frontend && npm run dev

test: ## Backend unit tests + frontend type check
	cd backend && uv run pytest -q
	cd frontend && npm run typecheck

lint:
	cd backend && uv run ruff check src tests && uv run ruff format --check src tests

desktop: ## Add Smart Meeting to the GNOME applications menu
	mkdir -p $(dir $(DESKTOP_FILE))
	sed "s|@ROOT@|$(ROOT)|g" packaging/smart-meeting.desktop > $(DESKTOP_FILE)
	@echo "Installed $(DESKTOP_FILE)"
