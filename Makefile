.PHONY: up down logs test check-keys

# Start the whole stack: backend http://localhost:8000, frontend http://localhost:3000
up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - put your real LLM_API_KEYS in it, then run 'make up' again." )
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

down:
	docker compose down

logs:
	docker compose logs -f

# Backend unit tests (no network, no keys needed)
test:
	cd backend && pip install -q -r requirements-dev.txt && python -m pytest -q

# Send one tiny request with each key to confirm keys + model work
check-keys:
	cd backend && set -a && . ../.env && set +a && python scripts/check_keys.py
