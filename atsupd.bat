@echo off
git pull origin main --force
mypy .
mypy . --strict
mypy . --strict -n 10 --check-untyped-defs
mypy . --strict -n 10 --check-untyped-defs --exclude-gitignore --install-types --non-interactive --warn-incomplete-stub --pdb --show-traceback --no-fixed-format-cache --show-absolute-path --show-error-end --show-error-context --extra-checks

rem python -m pytest -n auto -vv -s --count=5 --full-trace --cache-clear -k "not gui_integration"
rd .mypy_cache /s /q
