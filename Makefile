test:
	uv run coverage run -m unittest discover -s .

report:
	uv run coverage report