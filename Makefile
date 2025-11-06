.PHONY: setup lab test notebook smoke-notebook notebook-bg notebook-status notebook-tail notebook-stop refresh-prices lint clean

VENV?=.venv
PYTHON?=$(VENV)/bin/python
PIP?=$(VENV)/bin/pip
JUPYTER?=$(VENV)/bin/jupyter
NOTEBOOK_LOG?=out/notebook.log
NOTEBOOK_PID?=out/notebook.pid

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

lab: 
	$(JUPYTER) lab

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m black src tests
	$(PYTHON) -m ruff check src tests

notebook:
	$(PYTHON) -m papermill notebooks/stx_pox_flywheel.ipynb out/stx_pox_flywheel_run.ipynb

smoke-notebook:
	$(PYTHON) -m papermill notebooks/stx_pox_flywheel.ipynb out/smoke_run.ipynb -p HISTORY_DAYS 30 -p FORCE_REFRESH False

notebook-bg:
	@mkdir -p $(dir $(NOTEBOOK_LOG))
	@echo "Launching papermill in background; logging to $(NOTEBOOK_LOG)"
	( (set -o pipefail; $(PYTHON) -m papermill notebooks/stx_pox_flywheel.ipynb out/stx_pox_flywheel_run.ipynb --log-output --progress-bar) 2>&1 | tee $(NOTEBOOK_LOG) ) &
	@printf "%s\n" $$! > $(NOTEBOOK_PID)
	@echo "Background PID $$!"

notebook-status:
	@if [ -f $(NOTEBOOK_PID) ]; then \
		pid=$$(cat $(NOTEBOOK_PID)); \
		if ps -p $$pid >/dev/null 2>&1; then \
			echo "Papermill running (PID $$pid)"; \
		else \
			echo "Papermill not running (last PID $$pid)"; \
		fi; \
	else \
		echo "No notebook PID file found (expected at $(NOTEBOOK_PID))"; \
	fi

notebook-tail:
	@if [ -f $(NOTEBOOK_LOG) ]; then \
		echo "Tailing $(NOTEBOOK_LOG) (Ctrl+C to stop)"; \
		tail -f $(NOTEBOOK_LOG); \
	else \
		echo "Notebook log not found at $(NOTEBOOK_LOG)"; \
	fi

notebook-stop:
	@if [ -f $(NOTEBOOK_PID) ]; then \
		pid=$$(cat $(NOTEBOOK_PID)); \
		if ps -p $$pid >/dev/null 2>&1; then \
			kill $$pid && echo "Stopped papermill (PID $$pid)"; \
		else \
			echo "Papermill not running (last PID $$pid)"; \
		fi; \
		rm -f $(NOTEBOOK_PID); \
	else \
		echo "No notebook PID file found (expected at $(NOTEBOOK_PID))"; \
	fi

refresh-prices:
	rm -f data/cache/prices/*.parquet

clean:
	rm -rf data/raw/* out/*
