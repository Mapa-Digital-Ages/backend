test:
	uv run pytest -n auto --cov=src --cov-report=term-missing

report:
	uv run coverage report
