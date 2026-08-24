PYTHON_VERSION := 3.12
PYTHON ?= python$(PYTHON_VERSION)
UV ?= uv
VENV ?= .venv
PYTHON_BIN := $(VENV)/bin/python
PACKAGE := src/invest_service

.DEFAULT_GOAL := help

.PHONY: help venv lock-requirements deps lint format test clean \
	api worker beat compose-up compose-up-postgres compose-up-mysql compose-down

help:
	@echo "Available targets:"
	@echo "  venv                 Create $(VENV)"
	@echo "  lock-requirements    Regenerate requirements.txt from pyproject.toml"
	@echo "  deps                 Sync $(VENV) from requirements.txt and install the project"
	@echo "  lint                 Run Ruff and codespell"
	@echo "  format               Format and auto-fix Python sources"
	@echo "  test                 Run tests with coverage"
	@echo "  clean                Remove generated Python/test artifacts"
	@echo "  api|worker|beat      Start one local service process"
	@echo "  compose-up            Start the SQLite Compose stack"
	@echo "  compose-up-postgres   Start the PostgreSQL Compose stack"
	@echo "  compose-up-mysql      Start the MySQL Compose stack"
	@echo "  compose-down          Stop the SQLite Compose stack"

venv:
	@if ! test -x $(PYTHON_BIN) || ! $(PYTHON_BIN) -c \
		'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then \
		echo "Creating Python $(PYTHON_VERSION) virtual environment at $(VENV)"; \
		$(UV) venv --clear --python $(PYTHON) $(VENV); \
	fi

lock-requirements:
	$(UV) pip compile pyproject.toml --all-extras --python-version $(PYTHON_VERSION) --output-file requirements.txt

deps: venv lock-requirements
	$(UV) pip sync --python $(PYTHON_BIN) requirements.txt
	$(UV) pip install --python $(PYTHON_BIN) --no-deps --editable .

lint:
	$(PYTHON_BIN) -m ruff check .
	$(VENV)/bin/codespell

format:
	$(PYTHON_BIN) -m ruff check --fix .
	$(PYTHON_BIN) -m ruff format .

test:
	PYTHONPATH=src $(PYTHON_BIN) -m pytest --cov=invest_service --cov-report=term-missing tests/

clean:
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
	find src tests -type f -name '*.pyc' -delete
	rm -rf .coverage .pytest_cache .ruff_cache build dist
	rm -f coverage.xml cobertura.xml testresult.xml
	rm -rf ./*.egg-info src/*.egg-info

api:
	$(PYTHON_BIN) -m uvicorn invest_service.main:app --reload

worker:
	$(PYTHON_BIN) -m celery -A invest_service.celery_app:celery_app worker --loglevel=INFO

beat:
	$(PYTHON_BIN) -m celery -A invest_service.celery_app:celery_app beat --loglevel=INFO

compose-up:
	docker compose up --build -d

compose-up-postgres:
	docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d

compose-up-mysql:
	docker compose -f docker-compose.yml -f docker-compose.mysql.yml up --build -d

compose-down:
	docker compose down
