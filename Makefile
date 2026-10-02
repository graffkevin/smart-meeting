# Works on Linux, macOS and Windows (GNU make: `winget install ezwinports.make` on Windows).
# `make run` is all a user needs: missing pieces (uv, Bun, Ollama, models) are installed on first run.

ifeq ($(OS),Windows_NT)
  PLATFORM := windows
  NULL := NUL
  UV_LOCAL := $(USERPROFILE)/.local/bin/uv.exe
  INSTALL_UV := powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
else
  PLATFORM := $(shell uname -s | tr A-Z a-z)
  NULL := /dev/null
  UV_LOCAL := $(HOME)/.local/bin/uv
  INSTALL_UV := curl -LsSf https://astral.sh/uv/install.sh | sh
endif

# uv from the PATH, else where its installer puts it.
UV := $(if $(shell uv --version 2>$(NULL)),uv,$(UV_LOCAL))
# CUDA libraries only with an NVIDIA GPU.
EXTRAS := $(if $(shell nvidia-smi -L 2>$(NULL)),--extra cuda,)
BACKEND := $(UV) run --directory backend $(EXTRAS)

.PHONY: run install uv build dev dev-backend dev-frontend test lint check api desktop info

run: uv ## Start Smart Meeting (installs what is missing on first run)
	$(BACKEND) smart-meeting

install: uv ## Install everything without starting (optional: `make run` does it)
	$(UV) sync --directory backend $(EXTRAS)
	cd frontend && bun install --frozen-lockfile && bun run build

uv:
ifeq ($(shell $(UV) --version 2>$(NULL)),)
	@echo "Installation de uv..."
	$(INSTALL_UV)
endif

info: ## Show what was detected
	@echo "Système : $(PLATFORM)"
	@echo "uv      : $(UV)"
	@echo "GPU     : $(if $(EXTRAS),NVIDIA (CUDA),aucun (CPU))"

build: ## Build the web interface
	cd frontend && bun run build

dev: ## Development: backend with auto-reload + Vite dev server (http://127.0.0.1:5173)
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend: uv
	$(BACKEND) uvicorn smart_meeting.main:app --host 127.0.0.1 --port 8417 --reload

dev-frontend:
	cd frontend && bun run dev

test: uv ## Backend and frontend tests
	$(UV) run --directory backend pytest -q
	cd frontend && bun run test

lint: uv ## Every check: Ruff, Biome, frontend rules and types
	$(UV) run --directory backend ruff check src tests
	$(UV) run --directory backend ruff format --check src tests
	cd frontend && bunx biome check && bun run check:rules && bun run typecheck

check: lint test ## Everything to run before committing

api: uv ## Regenerate the frontend API client from the backend OpenAPI schema
	$(UV) run --directory backend python -c "import json; from smart_meeting.main import app; print(json.dumps(app.openapi(), indent=2))" > frontend/openapi/smart-meeting.openapi.json
	cd frontend && bun run api:generate

desktop: ## Linux: add Smart Meeting to the applications menu
ifeq ($(PLATFORM),linux)
	mkdir -p $(HOME)/.local/share/applications
	sed "s|@ROOT@|$(CURDIR)|g" packaging/smart-meeting.desktop > $(HOME)/.local/share/applications/smart-meeting.desktop
	@echo "Ajouté au menu des applications."
else
	@echo "make desktop n'est disponible que sous Linux ; lancez Smart Meeting avec : make run"
endif
