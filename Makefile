.PHONY: check test build qa publish pypi

check:
	poetry check

test:
	poetry run pytest

build:
	rm -rf dist
	poetry build

qa: check test build

publish:
	poetry version minor
	@version=$$(poetry version -s); python -c "from pathlib import Path; p=Path('agentctx/__init__.py'); lines=p.read_text().splitlines(); p.write_text('\\n'.join(('__version__ = \\\"' + '$$version' + '\\\"') if line.startswith('__version__ = ') else line for line in lines) + '\\n')"
	rm -rf dist
	poetry check
	poetry run pytest
	poetry build
	poetry publish

pypi: publish
