.PHONY: setup lab test notebook smoke-notebook lint clean

VENV?=.venv
PYTHON?=$(VENV)/bin/python
PIP?=$(VENV)/bin/pip
JUPYTER?=$(VENV)/bin/jupyter

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

clean:
	rm -rf data/raw/* out/*
