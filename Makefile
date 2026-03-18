# =============================================================================
# Makefile — convenience targets for the Zabbix local lab
# =============================================================================

.PHONY: help up down reset logs status bootstrap send-test

# Default target
help:
	@echo ""
	@echo "  Zabbix Local Lab — available commands"
	@echo "  ========================================"
	@echo "  make up          Start the full Zabbix stack"
	@echo "  make down        Stop all containers (data preserved)"
	@echo "  make reset       Stop + remove all data (full wipe)"
	@echo "  make logs        Follow container logs"
	@echo "  make status      Show container health status"
	@echo "  make bootstrap   Provision host + items + triggers via API"
	@echo "  make send-test   Send sample values from Python client"
	@echo ""

up:
	@bash scripts/start.sh

down:
	@bash scripts/stop.sh

reset:
	@bash scripts/reset.sh

logs:
	docker compose logs -f

status:
	docker compose ps

bootstrap:
	@python3 scripts/bootstrap.py

send-test:
	@cd client && python3 -m zabbix_sender.cli \
		--host macos-local-sender \
		--key macos.heartbeat \
		--value 1 \
		--verbose
