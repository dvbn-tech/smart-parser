.PHONY: up down migrate check test

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

migrate:
	uv run alembic -c infra/alembic.ini upgrade head

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest

test:
	uv run pytest --cov --cov-report=term-missing
