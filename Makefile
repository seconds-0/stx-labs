.PHONY: setup lab test notebook lint clean

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

clean:
	rm -rf data/raw/* out/*
