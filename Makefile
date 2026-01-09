# Makefile for running portfolio backtests for all strategies
# using precomputed signal files in data/signals/*.parquet.
#
# For each strategy (parquet file), we run:
#   1) portfolio backtest with 0 commission / 0 slippage
#   2) portfolio backtest with realistic costs (5 + 5 bps per side)
#
# Results:
#   - Per-strategy summaries in data/backtests/<strategy>_portfolio_*.summary.txt
#   - Combined summary in data/backtests/ALL_SUMMARIES.txt (see `make report`)

PYTHON      ?= python
SIGNAL_DIR  := data/signals
BACKTEST_DIR := data/backtests

# Find all .parquet signal files and derive strategy names from filenames.
SIGNAL_PARQUETS := $(wildcard $(SIGNAL_DIR)/*.parquet)
STRATEGIES      := $(basename $(notdir $(SIGNAL_PARQUETS)))
TOP_STRATEGIES := momentum_252d_longonly momentum_120d_loose momentum_tsmom_120d

# Per-strategy summary files
FREE_SUMMARIES      := $(addprefix $(BACKTEST_DIR)/,$(addsuffix _portfolio_free.summary.txt,$(STRATEGIES)))
REALISTIC_SUMMARIES := $(addprefix $(BACKTEST_DIR)/,$(addsuffix _portfolio_realistic.summary.txt,$(STRATEGIES)))
BENCHMARK := data/processed/gpw/wig20.parquet

# Default target: run all backtests (free + realistic)
.PHONY: all
all: summaries

.PHONY: summaries
summaries: $(FREE_SUMMARIES) $(REALISTIC_SUMMARIES)

.PHONY: free realistic
free: $(FREE_SUMMARIES)
realistic: $(REALISTIC_SUMMARIES)

# Pattern rule: portfolio backtest with 0 commission / 0 slippage
# $* is the strategy name (basename of the .parquet file)
$(BACKTEST_DIR)/%_portfolio_free.summary.txt: $(SIGNAL_DIR)/%.parquet
	@mkdir -p $(BACKTEST_DIR)
	@echo "=== Strategy: $* | Mode: portfolio | Costs: FREE (0 bps) ===" > $@
	@$(PYTHON) -m backtest.run_backtest \
	    --signals $< \
	    --mode portfolio \
	    --initial-capital 100000 \
	    --commission-bps 0 \
	    --slippage-bps 0 >> $@

# Pattern rule: portfolio backtest with realistic costs (5 + 5 bps per side)
$(BACKTEST_DIR)/%_portfolio_realistic.summary.txt: $(SIGNAL_DIR)/%.parquet
	@mkdir -p $(BACKTEST_DIR)
	@echo "=== Strategy: $* | Mode: portfolio | Costs: REALISTIC (5+5 bps per side) ===" > $@
	@$(PYTHON) -m backtest.run_backtest \
	    --signals $< \
	    --mode portfolio \
	    --initial-capital 100000 \
	    --commission-bps 5 \
	    --slippage-bps 5 >> $@

# Combine all summaries into a single easy-to-read file
.PHONY: report
report: summaries
	@mkdir -p $(BACKTEST_DIR)
	@echo "Writing combined report to $(BACKTEST_DIR)/ALL_SUMMARIES.txt"
	@cat $(BACKTEST_DIR)/*_portfolio_*.summary.txt > $(BACKTEST_DIR)/ALL_SUMMARIES.txt

# Convenience: run backtests for a single strategy:
# Example: make one STRAT=momentum_tsmom_60d
.PHONY: one
one:
ifndef STRAT
	$(error Usage: make one STRAT=<strategy_name> (e.g. STRAT=momentum))
endif
	@mkdir -p $(BACKTEST_DIR)
	@echo "=== Strategy: $(STRAT) | Mode: portfolio | Costs: FREE (0 bps) ===" > $(BACKTEST_DIR)/$(STRAT)_portfolio_free.summary.txt
	@$(PYTHON) -m backtest.run_backtest \
	    --signals $(SIGNAL_DIR)/$(STRAT).parquet \
	    --mode portfolio \
	    --initial-capital 100000 \
	    --commission-bps 0 \
	    --slippage-bps 0 >> $(BACKTEST_DIR)/$(STRAT)_portfolio_free.summary.txt
	@echo "=== Strategy: $(STRAT) | Mode: portfolio | Costs: REALISTIC (5+5 bps per side) ===" > $(BACKTEST_DIR)/$(STRAT)_portfolio_realistic.summary.txt
	@$(PYTHON) -m backtest.run_backtest \
	    --signals $(SIGNAL_DIR)/$(STRAT).parquet \
	    --mode portfolio \
	    --initial-capital 100000 \
	    --commission-bps 5 \
	    --slippage-bps 5 >> $(BACKTEST_DIR)/$(STRAT)_portfolio_realistic.summary.txt

.PHONY: clean
clean:
	@echo "Removing backtest summaries in $(BACKTEST_DIR)..."
	@rm -f $(BACKTEST_DIR)/*_portfolio_*.summary.txt $(BACKTEST_DIR)/ALL_SUMMARIES.txt

.PHONY: stress
stress:
	@mkdir -p $(BACKTEST_DIR)/stress
	@echo "Running stress tests for top strategies..."
	@for strat in $(TOP_STRATEGIES); do \
	  for scenario in free realistic; do \
	    for period in full 2010 2015 2020; do \
	      if [ "$$period" = "full" ]; then \
	        START_FLAG=""; \
	        LABEL="full"; \
	      else \
	        START_FLAG="--start-date $$period-01-01"; \
	        LABEL="since_$$period"; \
	      fi; \
	      if [ "$$scenario" = "free" ]; then \
	        COMM=0; SLIP=0; COST_TAG="free"; \
	      else \
	        COMM=5; SLIP=5; COST_TAG="realistic"; \
	      fi; \
	      OUT="$(BACKTEST_DIR)/stress/$${strat}_$${LABEL}_$${COST_TAG}.summary.txt"; \
	      echo ">>> $$strat | $$LABEL | $$COST_TAG"; \
	      echo "=== Strategy: $$strat | Period: $$LABEL | Costs: $$COST_TAG ===" > $$OUT; \
	      $(PYTHON) -m backtest.run_backtest \
	        --signals $(SIGNAL_DIR)/$$strat.parquet \
	        --mode portfolio \
	        --initial-capital 100000 \
	        --commission-bps $$COMM \
	        --slippage-bps $$SLIP \
	        $$START_FLAG \
	        --benchmark $(BENCHMARK) >> $$OUT; \
	    done; \
	  done; \
	done

# Combine all stress-test summaries into a single report
.PHONY: report_stress
report_stress:
	@echo "Combining stress test summaries..."
	@mkdir -p $(BACKTEST_DIR)/stress
	@cat $(BACKTEST_DIR)/stress/*.summary.txt > $(BACKTEST_DIR)/stress/ALL_STRESS_SUMMARIES.txt
	@echo "Saved combined report to $(BACKTEST_DIR)/stress/ALL_STRESS_SUMMARIES.txt"
