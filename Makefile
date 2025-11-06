.PHONY: setup lab test notebook smoke-notebook notebook-macro notebook-macro-bg lint clean

VENV?=.venv
PYTHON?=$(VENV)/bin/python
PIP?=$(VENV)/bin/pip
JUPYTER?=$(VENV)/bin/jupyter
HISTORY_DAYS?=730
FORCE_REFRESH?=False

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

notebook-macro:
	mkdir -p out
	$(PYTHON) -m papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb -p HISTORY_DAYS $(HISTORY_DAYS) -p FORCE_REFRESH $(FORCE_REFRESH)

notebook-macro-bg:
	mkdir -p out
	nohup $(PYTHON) -m papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb -p HISTORY_DAYS $(HISTORY_DAYS) -p FORCE_REFRESH $(FORCE_REFRESH) > out/macro_notebook.log 2>&1 &
	@echo "Macro analysis running in background. Monitor with: tail -f out/macro_notebook.log"

clean:
	rm -rf data/raw/* out/*
