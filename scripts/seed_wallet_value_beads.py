#!/usr/bin/env python3
"""Seed Wallet Value epics, issues, and dependencies into beads.

Idempotent: re-running will only create missing items and (re)apply deps.

Usage:
  python scripts/seed_wallet_value_beads.py

Notes:
- Requires `bd` CLI on PATH and initialized in repo (.beads/ exists).
- Uses issue titles as stable keys; do not rename titles unless updating this script.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def list_items() -> list[dict]:
    out = run(["bd", "list", "--json"]).stdout
    try:
        return json.loads(out)
    except Exception as exc:  # tolerate warnings printed before JSON
        # Attempt to parse trailing JSON object/array
        payload = out[out.find("{") :]
        if payload:
            return json.loads(payload)
        raise RuntimeError(f"Failed to parse bd list JSON: {exc}\nOUT=\n{out}")


def ensure_issue(
    *,
    title: str,
    issue_type: str,
    priority: str,
    labels: str,
    description: str,
    acceptance: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> str:
    items = list_items()
    existing = next((it for it in items if it.get("title") == title), None)
    if existing:
        return existing["id"]
    cmd = [
        "bd",
        "create",
        "--force",
        "--type",
        issue_type,
        "--priority",
        priority,
        "--labels",
        labels,
        "--title",
        title,
        "--description",
        description,
    ]
    if acceptance:
        cmd += ["--acceptance", acceptance]
    if parent_id:
        cmd += ["--parent", parent_id]
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"bd create failed for {title}: {res.stderr or res.stdout}")
    # Fetch created ID via list
    items = list_items()
    created = next((it for it in items if it.get("title") == title), None)
    if not created:
        raise RuntimeError(f"Created issue not found by title: {title}")
    return created["id"]


def ensure_dep(child_title: str, parent_title: str) -> None:
    items = list_items()
    title_to_id = {it["title"]: it["id"] for it in items}
    a = title_to_id.get(child_title)
    b = title_to_id.get(parent_title)
    if not a or not b:
        return
    run(["bd", "dep", "add", a, b, "--type", "blocks"])  # idempotent


def main() -> int:
    if not shutil.which("bd"):
        print("ERROR: 'bd' CLI not found on PATH.", file=sys.stderr)
        return 1

    epics = {
        "Epic: Repo Hygiene & Environment (Wallet Value)": ("epic", "P1", "area:pipeline,prio:P1", "Ensure .env is synced across worktrees and venv is up to date; verify CI passes."),
        "Epic: Wallet Value MVP": ("epic", "P1", "area:wallets,prio:P1", "Compute NV/WALTV v1, classify wallets, generate dashboard."),
        "Epic: Activation Filter Refinement": ("epic", "P2", "area:wallets,prio:P2", "Define and implement non-trivial activation criteria and recompute cohorts."),
        "Epic: sBTC Funded Signal": ("epic", "P2", "area:wallets,prio:P2", "Detect sBTC mint events and include in funded classification."),
        "Epic: Derived Activity Value & Incentives (WALTV)": ("epic", "P2", "area:wallets,prio:P2", "Add derived downstream value and incentives offsets into WALTV."),
        "Epic: App Mapping & Reporting": ("epic", "P3", "area:dashboards,prio:P3", "Map contracts to apps and add app-level funnels and value views."),
        "Epic: Performance & Reliability": ("epic", "P2", "area:pipeline,prio:P2", "Improve long-running backfill and price resilience."),
        "Epic: Dashboard UX Polish": ("epic", "P2", "area:dashboards,prio:P2", "Funnel viz, toggles, and copy."),
        "Epic: Data Governance & Scheduling": ("epic", "P3", "area:data,prio:P3", "Cache retention policies and scheduled refresh jobs."),
        "Epic: Documentation & Handoff": ("epic", "P2", "area:docs,prio:P2", "Keep plan up to date; add operator runbook."),
    }
    epic_ids: Dict[str, str] = {}
    for title, (typ, prio, labels, desc) in epics.items():
        epic_ids[title] = ensure_issue(
            title=title, issue_type=typ, priority=prio, labels=labels, description=desc
        )

    def parent(epic_title: str) -> str:
        return epic_ids[epic_title]

    planned: list[Tuple[str, str, str, str, str, str, str]] = [
        (
            "Sync .env across all worktrees",
            "chore",
            "P1",
            "area:pipeline,type:chore,prio:P1",
            "Run ./scripts/sync_env.sh; verify .env exists in main repo and .conductor/* worktrees. Commands: ls -la .env; for each worktree: cat .env.",
            "All active worktrees contain .env with HIRO_API_KEY; sync script verified.",
            "Epic: Repo Hygiene & Environment (Wallet Value)",
        ),
        (
            "Ensure venv is up to date in target worktree",
            "chore",
            "P1",
            "area:pipeline,type:chore,prio:P1",
            "Run make setup to (re)create venv and install deps in current worktree.",
            "make setup completes; make test runs without import errors.",
            "Epic: Repo Hygiene & Environment (Wallet Value)",
        ),
        (
            "Baseline CI sanity (tests + lint)",
            "chore",
            "P2",
            "area:pipeline,type:chore,prio:P2",
            "Run make test and make lint; capture failures (outside scope to fix unrelated repo-wide lint).",
            "make test passes; make lint runs; unrelated lint warnings acceptable.",
            "Epic: Repo Hygiene & Environment (Wallet Value)",
        ),
        (
            "Adopt wallet_value pipeline API",
            "feature",
            "P1",
            "area:wallets,type:feat,prio:P1",
            "Review src/wallet_value.py functions and usage; exercise compute_value_pipeline in REPL with a small window.",
            "compute_value_pipeline(max_days=60) returns non-empty frames with backfilled data.",
            "Epic: Wallet Value MVP",
        ),
        (
            "Verify Hiro balances endpoint caching for funded classification",
            "feature",
            "P1",
            "area:wallets,type:feat,prio:P1",
            "Use src/hiro.py:fetch_address_balances; test a few addresses; confirm TTL behavior.",
            "Repeated fetches of a sample address hit cache (data/raw/hiro_address_balances_* updated once within TTL).",
            "Epic: Wallet Value MVP",
        ),
        (
            "Backfill wallet transactions (365 days)",
            "feature",
            "P1",
            "area:pipeline,type:feat,prio:P1",
            "Run python scripts/backfill_wallet_history.py --target-days 365 --max-iterations 100; monitor with make backfill-status and backfill-tail.",
            "DuckDB min(block_time) <= now-365d; wallet_count above baseline; backfill logs show progress.",
            "Epic: Wallet Value MVP",
        ),
        (
            "Validate STX/BTC price panel coverage",
            "chore",
            "P1",
            "area:prices,type:chore,prio:P1",
            "Use src/prices.load_price_panel to inspect coverage across backfilled activity window.",
            "load_price_panel(start,end) covers the activity range; no fatal gaps; interpolation warnings acceptable.",
            "Epic: Wallet Value MVP",
        ),
        (
            "Generate dashboards (wallet, value, macro)",
            "feature",
            "P1",
            "area:dashboards,type:feat,prio:P1",
            "Run python scripts/build_dashboards.py --wallet-max-days 180 --value-windows 15 30 60 90; verify outputs.",
            "public/wallet/index.html, public/value/index.html, public/macro/index.html exist and render without JS errors.",
            "Epic: Wallet Value MVP",
        ),
        (
            "Tests green (>=80% coverage baseline)",
            "chore",
            "P1",
            "area:wallets,type:chore,prio:P1",
            "Execute make test; capture summary and address regressions if found.",
            "make test passes fully; new tests test_wallet_value.py pass.",
            "Epic: Wallet Value MVP",
        ),
        (
            "Decide non-trivial activation rule",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Propose activation filter: tx types, min transfer threshold, sBTC mint; review with team and document.",
            "Definition approved and recorded in docs/wallet_value_plan.md.",
            "Epic: Activation Filter Refinement",
        ),
        (
            "Implement activation filter in first-seen logic",
            "feature",
            "P2",
            "area:pipeline,type:feat,prio:P2",
            "Extend wallet_metrics ingestion to capture required tx fields; filter in compute_activation/update_first_seen accordingly.",
            "first_seen excludes trivial txs per approved rule; unit tests updated.",
            "Epic: Activation Filter Refinement",
        ),
        (
            "Recompute first_seen and cohorts",
            "chore",
            "P2",
            "area:wallets,type:chore,prio:P2",
            "Invalidate FIRST_SEEN cache if needed; rerun update_first_seen_cache with activity; record cohort deltas.",
            "first_seen parquet refreshed; new_wallets/active_wallets charts reflect rule; diffs documented.",
            "Epic: Activation Filter Refinement",
        ),
        (
            "Research sBTC mint event detection",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Inspect Hiro tx payloads for sBTC mints; document detection logic and required fields.",
            "ABI/function signatures and event shapes identified for sBTC mint threshold.",
            "Epic: sBTC Funded Signal",
        ),
        (
            "Capture contract_id/function in ingestion",
            "feature",
            "P2",
            "area:pipeline,type:feat,prio:P2",
            "Extend schema and _prepare_transactions to persist contract details; migrate existing data as feasible.",
            "DuckDB transactions table contains contract_id/function for contract_call txs; backfilled for recent history.",
            "Epic: sBTC Funded Signal",
        ),
        (
            "Add sBTC minted threshold to funded classification",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Modify classify_wallets to include sBTC criterion in addition to STX balance.",
            "Wallets with sBTC mint ≥ 0.001 BTC qualify as funded; tests cover examples.",
            "Epic: sBTC Funded Signal",
        ),
        (
            "Decide derived value attribution method",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Propose approach with pros/cons and complexity; choose a pragmatic v1.",
            "Method approved (first-touch/equal-share/etc.), documented in docs/wallet_value_plan.md.",
            "Epic: Derived Activity Value & Incentives (WALTV)",
        ),
        (
            "Aggregate downstream fees by contract post-activation",
            "feature",
            "P2",
            "area:pipeline,type:feat,prio:P2",
            "Using captured contract_id/function, compute fees occurring after activation on those contracts for a time window.",
            "Table/view summarizing downstream fees per activation_contract and window exists; tests validate aggregation.",
            "Epic: Derived Activity Value & Incentives (WALTV)",
        ),
        (
            "Apply WALTV = NV + derived − incentives",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Join derived and incentives inputs into compute_wallet_windows; update dashboard to display WALTV.",
            "WALTV columns available in windows output and visualized; tests pass.",
            "Epic: Derived Activity Value & Incentives (WALTV)",
        ),
        (
            "Ingest incentives (off-chain) for WALTV offsets",
            "feature",
            "P2",
            "area:wallets,type:feat,prio:P2",
            "Define schema and loader; secure storage for incentive data.",
            "Incentives loaded from CSV/JSON and joined to wallets; WALTV subtracts values.",
            "Epic: Derived Activity Value & Incentives (WALTV)",
        ),
        (
            "Create contract→app mapping",
            "feature",
            "P3",
            "area:dashboards,type:feat,prio:P3",
            "Seed mapping from known apps; design extensible structure (YAML/JSON).",
            "Mapping file checked in; unit tests ensure lookups; regularly updated.",
            "Epic: App Mapping & Reporting",
        ),
        (
            "Add app-level funnels and value views",
            "feature",
            "P3",
            "area:dashboards,type:feat,prio:P3",
            "Group windows and classifications by app; add charts and summary tables.",
            "Dashboard sections with per-app funnels and NV/WALTV; top apps ranked by value.",
            "Epic: App Mapping & Reporting",
        ),
        (
            "Tune backfill throughput and stability",
            "chore",
            "P2",
            "area:pipeline,type:chore,prio:P2",
            "Experiment with --max-pages and TTLs; consider batch sizes; measure end-to-end throughput.",
            "Sustained pages/min without throttling; recommended max-pages/TTL documented.",
            "Epic: Performance & Reliability",
        ),
        (
            "Validate price fallback behavior",
            "chore",
            "P2",
            "area:prices,type:chore,prio:P2",
            "Force CG failure and verify fallback path; update warnings/messages if needed.",
            "CoinGecko failure path triggers Signal21 fallback; no empty panels; errors clearly surfaced when both fail.",
            "Epic: Performance & Reliability",
        ),
        (
            "Add conversion funnel visualization",
            "feature",
            "P2",
            "area:dashboards,type:feat,prio:P2",
            "Implement a funnel visualization; ensure interactivity and tooltips with definitions.",
            "Funnel chart/progress bars per window; clear Funded→Active→Value conversion.",
            "Epic: Dashboard UX Polish",
        ),
        (
            "Add price join method toggle (nearest vs start-of-day)",
            "feature",
            "P3",
            "area:dashboards,type:feat,prio:P3",
            "Add control and recomputation path in dashboard build function.",
            "NV recalculates with chosen method; default remains nearest; performance acceptable.",
            "Epic: Dashboard UX Polish",
        ),
        (
            "Polish tooltips and copy for KPI definitions",
            "chore",
            "P2",
            "area:dashboards,type:chore,prio:P2",
            "Audit hover text and section notes; align with docs definitions.",
            "Hover templates and notes match docs; terminology consistent.",
            "Epic: Dashboard UX Polish",
        ),
        (
            "Define cache retention policy and cleanup scripts",
            "chore",
            "P3",
            "area:data,type:chore,prio:P3",
            "Decide retention windows; write cleanup utilities; document safeguards.",
            "Retention documented; scripts to prune data/raw and cache directories safely.",
            "Epic: Data Governance & Scheduling",
        ),
        (
            "Add scheduled dashboard refresh",
            "feature",
            "P3",
            "area:pipeline,type:feat,prio:P3",
            "Use cron/systemd/CI to run build_dashboards with deltas only; copy to public/; notify on failure.",
            "Nightly/weekly job runs deltas and publishes dashboards; basic monitoring/logging in place.",
            "Epic: Data Governance & Scheduling",
        ),
        (
            "Keep wallet_value_plan.md updated",
            "chore",
            "P2",
            "area:docs,type:chore,prio:P2",
            "Revise docs/wallet_value_plan.md as decisions land; PR review to confirm clarity.",
            "Plan doc reflects activation rule and WALTV v2 decisions; reviewed quarterly.",
            "Epic: Documentation & Handoff",
        ),
        (
            "Add operator runbook for backfills and dashboards",
            "chore",
            "P2",
            "area:docs,type:chore,prio:P2",
            "Write step-by-step runbook with commands: backfill, status, dashboard build, common errors.",
            "docs/runbook_wallet_value.md contains commands and troubleshooting; team can run without assistance.",
            "Epic: Documentation & Handoff",
        ),
    ]

    created: list[str] = []
    for title, typ, prio, labels, desc, acc, epic_title in planned:
        pid = parent(epic_title)
        ensure_issue(
            title=title,
            issue_type=typ,
            priority=prio,
            labels=labels,
            description=desc,
            acceptance=acc,
            parent_id=pid,
        )
        created.append(title)

    # Dependencies
    deps = [
        ("Backfill wallet transactions (365 days)", "Sync .env across all worktrees"),
        ("Backfill wallet transactions (365 days)", "Ensure venv is up to date in target worktree"),
        ("Validate STX/BTC price panel coverage", "Backfill wallet transactions (365 days)"),
        ("Generate dashboards (wallet, value, macro)", "Validate STX/BTC price panel coverage"),
        ("Tests green (>=80% coverage baseline)", "Generate dashboards (wallet, value, macro)"),
        ("Implement activation filter in first-seen logic", "Decide non-trivial activation rule"),
        ("Implement activation filter in first-seen logic", "Backfill wallet transactions (365 days)"),
        ("Recompute first_seen and cohorts", "Implement activation filter in first-seen logic"),
        ("Capture contract_id/function in ingestion", "Research sBTC mint event detection"),
        ("Add sBTC minted threshold to funded classification", "Capture contract_id/function in ingestion"),
        ("Aggregate downstream fees by contract post-activation", "Decide derived value attribution method"),
        ("Aggregate downstream fees by contract post-activation", "Capture contract_id/function in ingestion"),
        ("Apply WALTV = NV + derived − incentives", "Aggregate downstream fees by contract post-activation"),
        ("Ingest incentives (off-chain) for WALTV offsets", "Decide derived value attribution method"),
        ("Add app-level funnels and value views", "Create contract→app mapping"),
        ("Add app-level funnels and value views", "Capture contract_id/function in ingestion"),
        ("Tune backfill throughput and stability", "Backfill wallet transactions (365 days)"),
        ("Validate price fallback behavior", "Backfill wallet transactions (365 days)"),
        ("Add conversion funnel visualization", "Generate dashboards (wallet, value, macro)"),
        ("Add price join method toggle (nearest vs start-of-day)", "Generate dashboards (wallet, value, macro)"),
        ("Polish tooltips and copy for KPI definitions", "Generate dashboards (wallet, value, macro)"),
        ("Define cache retention policy and cleanup scripts", "Backfill wallet transactions (365 days)"),
        ("Add scheduled dashboard refresh", "Generate dashboards (wallet, value, macro)"),
        ("Add scheduled dashboard refresh", "Define cache retention policy and cleanup scripts"),
        ("Add operator runbook for backfills and dashboards", "Generate dashboards (wallet, value, macro)"),
    ]
    for a, b in deps:
        ensure_dep(a, b)

    print("Seed complete. Issues ensured:")
    for title in created:
        print(" -", title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
