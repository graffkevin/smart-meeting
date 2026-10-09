# Development tasks (GNU make; on Windows `winget install ezwinports.make`). Users do not need make:
# `./smart-meeting` (`.\smart-meeting` on Windows) starts the app like `make run`, and installs
# what is missing on first run (uv, Bun, Ollama, models).

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

.PHONY: run install uv build dev dev-backend dev-frontend test lint check api desktop info deb mac release mac

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
	$(UV) run --directory backend ruff check src tests ../linux
	$(UV) run --directory backend ruff format --check src tests ../linux
	cd frontend && bunx biome check && bun run check:rules && bun run typecheck

check: lint test ## Everything to run before committing

api: uv ## Regenerate the frontend API client from the backend OpenAPI schema
	$(UV) run --directory backend python -c "import json; from smart_meeting.main import app; print(json.dumps(app.openapi(), indent=2))" > frontend/openapi/smart-meeting.openapi.json
	cd frontend && bun run api:generate

deb: ## Build the Linux (GNOME) app package, build/linux/smart-meeting_<version>_all.deb
	packaging/linux/build-deb.sh

mac: uv ## Build the macOS app and its disk image (build/macos/); DEVELOPER_ID and NOTARY_PROFILE to sign it
	packaging/macos/build.sh

release: ## Tag the version of backend/pyproject.toml and push it: GitHub builds the .deb and the signed .dmg into its release
	@version="$$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)"; \
	test "$$(git branch --show-current)" = main || { echo "Pas sur main"; exit 1; }; \
	test -z "$$(git status --porcelain)" || { echo "Des changements ne sont pas commités"; exit 1; }; \
	! git rev-parse -q --verify "refs/tags/v$$version" >/dev/null || { echo "v$$version existe déjà : changez la version"; exit 1; }; \
	git tag -a "v$$version" -m "Smart Meeting $$version" && git push origin main "v$$version" && \
	echo "v$$version poussé : GitHub construit le .deb et le .dmg (gh run watch), puis publiez la release :" && \
	echo "  gh release edit v$$version --notes-file notes.md --draft=false"

desktop: ## Add Smart Meeting to the applications (menu, Applications, Start menu), to pin it
	./smart-meeting --install
