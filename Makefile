# Post-Surgical Recovery Companion — developer commands (everything runs in Docker)
COMPOSE ?= docker compose

.PHONY: dev up down logs build test test-unit test-api test-safety e2e ui-smoke demo seed reset reindex jobs fe-check openapi clean ps android

dev: ## Build and start the full stack (db + api + web) in the foreground
	@test -f .env || cp .env.example .env
	$(COMPOSE) up --build

up: ## Start in the background
	@test -f .env || cp .env.example .env
	$(COMPOSE) up --build -d
	@echo "App: http://localhost:$${WEB_PORT:-8080}   API docs: http://localhost:$${WEB_PORT:-8080}/api/docs"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f backend

build:
	$(COMPOSE) build

ps:
	$(COMPOSE) ps

test: ## Full backend suite (unit + API + safety + RAG + RBAC) against the test database
	$(COMPOSE) run --rm -e APP_ENV=test -e ENABLE_SCHEDULER=false -e SEED_ON_STARTUP=false -e LLM_PROVIDER=extractive backend pytest

test-unit:
	$(COMPOSE) run --rm -e APP_ENV=test backend pytest tests/unit

test-api:
	$(COMPOSE) run --rm -e APP_ENV=test -e LLM_PROVIDER=extractive backend pytest tests/api

test-safety:
	$(COMPOSE) run --rm -e APP_ENV=test -e LLM_PROVIDER=extractive backend pytest tests/safety -v

e2e: ## End-to-end HTTP tests against the running stack (make up first)
	$(COMPOSE) exec -e E2E_BASE_URL=http://frontend:80/api backend pytest tests/e2e -v

ui-smoke: ## Headless-browser smoke test of every page for every role (stack must be up)
	docker run --rm --network recovery-companion_default -v $(PWD)/tests/e2e:/e2e -w /e2e \
	  mcr.microsoft.com/playwright/python:v1.48.0-jammy sh -c "pip install -q playwright==1.48.0 && python ui_smoke.py"

openapi: ## Export the OpenAPI contract to docs/openapi.json
	$(COMPOSE) exec backend python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > docs/openapi.json

demo: ## Run all 8 demo scenarios via the API and print results
	$(COMPOSE) exec backend python scripts/run_demo.py --base-url http://frontend:80/api

seed: ## Seed synthetic data if empty
	$(COMPOSE) exec backend python -m app.seed

reset: ## Drop and reseed all synthetic data
	$(COMPOSE) exec backend python -m app.seed --reset

reindex: ## Re-chunk and re-embed all documents (after changing EMBEDDING_PROVIDER)
	$(COMPOSE) exec backend python scripts/reindex.py

jobs: ## Run scheduled jobs now (missed check-ins, reminders, SLA)
	$(COMPOSE) exec backend python -c "from app.core.database import SessionLocal; from app.services.scheduler import run_all_jobs; print(run_all_jobs(SessionLocal()))"

fe-check: ## Type-check and build the frontend
	docker run --rm -v $(PWD)/frontend:/web -w /web node:20-alpine sh -c "npm install --no-audit --no-fund && npm run build"

# Android app. Default API address is the Android emulator's view of this machine (WEB_PORT 8081);
# for a phone on the same Wi-Fi use e.g. API_BASE=http://192.168.1.20:8081/api, for production an https URL.
API_BASE ?= http://10.0.2.2:8081/api
ANDROID_ALLOW_HTTP ?= $(if $(filter http://%,$(API_BASE)),true,false)
android: ## Build the Android app (APK + Android Studio project) in Docker → dist/android/
	docker buildx build --platform linux/amd64 -f docker/android.Dockerfile --target apk \
	  --build-arg API_BASE=$(API_BASE) --build-arg ANDROID_ALLOW_HTTP=$(ANDROID_ALLOW_HTTP) \
	  --output type=local,dest=dist/android .
	@echo "APK: dist/android/recovery-companion-debug.apk  (API: $(API_BASE))"

clean: ## Remove containers and the database volume
	$(COMPOSE) down -v
