.PHONY: test cicd hooks-install hooks-run

test:
	uv run pytest -n auto --cov=src --cov-report=term-missing

cicd:
	@echo "==> [1/4] Ruff lint"
	@uv run ruff check . --no-fix || { echo ""; echo "FAIL: Ruff lint"; exit 1; }
	@echo ""
	@echo "==> [2/4] Ruff format check"
	@uv run ruff format --check . || { echo ""; echo "FAIL: Ruff format"; exit 1; }
	@echo ""
	@echo "==> [3/4] Pyright (type check)"
	@uv run pyright src/ || { echo ""; echo "FAIL: Pyright type check"; exit 1; }
	@echo ""
	@echo "==> [4/4] Tests + coverage (pytest -n auto, fail_under=80)"
	@uv run pytest -n auto --cov=src --cov-report=term-missing || { echo ""; echo "FAIL: Tests or coverage"; exit 1; }
	@echo ""
	@echo "OK: all CI checks passed"

hooks-install:
	uv sync
	uv run pre-commit install

hooks-run:
	uv run pre-commit run --all-files
