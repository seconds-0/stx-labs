.PHONY: setup lab test notebook smoke-notebook notebook-bg notebook-status notebook-tail notebook-stop refresh-prices notebook-macro notebook-macro-bg lint clean backfill-wallet backfill-status backfill-bg backfill-stop backfill-tmux backfill-tmux-start backfill-tmux-attach backfill-tmux-stop backfill-tmux-status backfill-tmux-logs backfill-health

VENV?=.venv
PYTHON?=$(VENV)/bin/python
PIP?=$(VENV)/bin/pip
JUPYTER?=$(VENV)/bin/jupyter
NOTEBOOK_LOG?=out/notebook.log
NOTEBOOK_PID?=out/notebook.pid
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

notebook-macro:
	mkdir -p out
	$(PYTHON) -m papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb -p HISTORY_DAYS $(HISTORY_DAYS) -p FORCE_REFRESH $(FORCE_REFRESH)

notebook-macro-bg:
	mkdir -p out
	nohup $(PYTHON) -m papermill notebooks/stx_btc_macro_correlations.ipynb out/stx_btc_macro_correlations_output.ipynb -p HISTORY_DAYS $(HISTORY_DAYS) -p FORCE_REFRESH $(FORCE_REFRESH) > out/macro_notebook.log 2>&1 &
	@echo "Macro analysis running in background. Monitor with: tail -f out/macro_notebook.log"

clean:
	rm -rf data/raw/* out/*

# Wallet transaction history backfill targets
BACKFILL_LOG?=out/backfill.log
BACKFILL_PID?=out/backfill.pid
TARGET_DAYS?=365
MAX_PAGES?=5000
MAX_ITERATIONS?=0

backfill-wallet:
	$(PYTHON) scripts/backfill_wallet_history.py --target-days $(TARGET_DAYS) --max-pages 2000

backfill-status:
	@$(PYTHON) scripts/check_backfill_status.py --target-days $(TARGET_DAYS) || true

backfill-bg:
	@mkdir -p $(dir $(BACKFILL_LOG))
	@echo "Launching wallet backfill in background; logging to $(BACKFILL_LOG)"
	( (set -o pipefail; caffeinate -i $(PYTHON) -u scripts/backfill_wallet_history.py --target-days $(TARGET_DAYS) --max-pages 2000) 2>&1 | tee $(BACKFILL_LOG) ) &
	@printf "%s\n" $$! > $(BACKFILL_PID)
	@echo "Background PID $$!"
	@echo "Using caffeinate to prevent sleep during backfill"
	@echo "Max pages per iteration: 2000 (safer, faster iterations)"
	@echo "Monitor with: make backfill-tail"
	@echo "Check status with: make backfill-status"

backfill-tail:
	@if [ -f $(BACKFILL_LOG) ]; then \
		echo "Tailing $(BACKFILL_LOG) (Ctrl+C to stop)"; \
		tail -f $(BACKFILL_LOG); \
	else \
		echo "Backfill log not found at $(BACKFILL_LOG)"; \
	fi

backfill-stop:
	@if [ -f $(BACKFILL_PID) ]; then \
		pid=$$(cat $(BACKFILL_PID)); \
		if ps -p $$pid >/dev/null 2>&1; then \
			kill $$pid && echo "Stopped backfill (PID $$pid)"; \
		else \
			echo "Backfill not running (last PID $$pid)"; \
		fi; \
		rm -f $(BACKFILL_PID); \
	else \
		echo "No backfill PID file found (expected at $(BACKFILL_PID))"; \
	fi

# Tmux-based backfill targets (uninterruptible, SSH-persistent)
backfill-tmux:
	@echo "Starting/attaching to uninterruptible backfill session..."
	@echo "Target: $(TARGET_DAYS) days | Max pages: $(MAX_PAGES) | Max iterations: $(MAX_ITERATIONS) (0=infinite)"
	@echo ""
	TARGET_DAYS=$(TARGET_DAYS) MAX_PAGES=$(MAX_PAGES) MAX_ITERATIONS=$(MAX_ITERATIONS) ./scripts/backfill_tmux.sh

backfill-tmux-start:
	@echo "Creating NEW tmux session for backfill..."
	@echo "Target: $(TARGET_DAYS) days | Max pages: $(MAX_PAGES) | Max iterations: $(MAX_ITERATIONS)"
	@echo ""
	TARGET_DAYS=$(TARGET_DAYS) MAX_PAGES=$(MAX_PAGES) MAX_ITERATIONS=$(MAX_ITERATIONS) ./scripts/backfill_tmux.sh start

backfill-tmux-attach:
	@echo "Attaching to existing tmux session..."
	./scripts/backfill_tmux.sh attach

backfill-tmux-stop:
	@echo "Stopping tmux backfill session..."
	./scripts/backfill_tmux.sh stop

backfill-tmux-status:
	@./scripts/backfill_tmux.sh status

backfill-tmux-logs:
	@echo "Recent backfill logs (Ctrl+C to stop):"
	@echo "================================================================================"
	@tail -30 $(BACKFILL_LOG) 2>/dev/null || echo "No logs found at $(BACKFILL_LOG)"

backfill-health:
	@echo "Running health check..."
	@./scripts/backfill_health_check.sh --target-days $(TARGET_DAYS)
