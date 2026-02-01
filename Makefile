# =============================================================================
# Coinr Market Metrics - Makefile
# =============================================================================

.PHONY: help setup infra-up infra-down services-up services-down up down logs logs-app logs-scanner logs-infra build clean status

help:
	@echo "Coinr Market Metrics"
	@echo ""
	@echo "Usage:"
	@echo "  make setup         - Create .env from template"
	@echo "  make infra-up      - Start infrastructure (MongoDB, Redis)"
	@echo "  make infra-down    - Stop infrastructure"
	@echo "  make services-up   - Start API + market scanner"
	@echo "  make services-down - Stop services"
	@echo "  make up            - Start everything"
	@echo "  make down          - Stop everything"
	@echo "  make logs          - Follow service logs"
	@echo "  make logs-app      - Follow API logs"
	@echo "  make logs-scanner  - Follow market scanner logs"
	@echo "  make logs-infra    - Follow infra logs"
	@echo "  make build         - Rebuild service images"
	@echo "  make clean         - Remove containers and volumes"
	@echo "  make status        - Show running containers"
	@echo ""

setup:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from template"; fi
	@echo "Edit .env with your Binance API keys"

infra-up:
	docker compose -f docker-compose.infra.yml up -d
	@echo "Infrastructure started"

infra-down:
	docker compose -f docker-compose.infra.yml down

services-up:
	docker compose -f docker-compose.yml up -d

services-down:
	docker compose -f docker-compose.yml down

up: infra-up
	@sleep 5
	@echo "Starting services..."
	@make services-up


down:
	docker compose -f docker-compose.yml down
	docker compose -f docker-compose.infra.yml down

logs:
	docker compose -f docker-compose.yml logs -f

logs-app:
	docker compose -f docker-compose.yml logs -f app

logs-scanner:
	docker compose -f docker-compose.yml logs -f market-scanner

logs-infra:
	docker compose -f docker-compose.infra.yml logs -f

build:
	docker compose -f docker-compose.yml build --no-cache

clean:
	docker compose -f docker-compose.yml down -v --rmi local
	docker compose -f docker-compose.infra.yml down -v

status:
	@echo "=== Infrastructure ==="
	@docker compose -f docker-compose.infra.yml ps
	@echo ""
	@echo "=== Services ==="
	@docker compose -f docker-compose.yml ps
