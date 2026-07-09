.PHONY: test e2e docker-e2e lint

test:
	python -m pytest

e2e:
	python scripts/e2e_score.py --out e2e-results.json

docker-e2e:
	docker compose run --rm e2e

lint:
	python -m ruff check src tests scripts
