# Git Worktree Merge - Quick Reference Card

## ⚠️ CRITICAL: Before Any Worktree Merge

```bash
# 1. CHECK: Does target worktree have .env?
ls -la /Users/alexanderhuth/Code/stx-labs/.conductor/stuttgart/.env

# 2. If missing, COPY IT FIRST:
cp /Users/alexanderhuth/Code/stx-labs/.env ./.env

# 3. Or use the sync script:
./scripts/sync_env.sh
```

## 📋 Pre-Merge Checklist

- [ ] ✅ Target worktree has `.env` file
- [ ] ✅ Target worktree venv is current (`make setup`)
- [ ] ✅ Tests pass in target (`make test`)
- [ ] ✅ No uncommitted changes in target

## 📋 Post-Merge Checklist

- [ ] ✅ Verify `.env` still exists (`cat .env`)
- [ ] ✅ Rebuild venv if deps changed (`make setup`)
- [ ] ✅ Run tests (`make test`)
- [ ] ✅ Optional: Smoke test (`make smoke-notebook`)

## 🆘 Common Issues & Fixes

| Problem | Fix |
|---------|-----|
| `HIRO_API_KEY` not found | `cp /Users/alexanderhuth/Code/stx-labs/.env ./.env` |
| Import errors after merge | `make setup` (rebuild venv) |
| Tests fail | Check if requirements.txt changed, run `make setup` |

## 🔧 Helper Script

```bash
# Sync .env to ALL worktrees automatically
./scripts/sync_env.sh
```

## 📍 Worktree Locations

```
/Users/alexanderhuth/Code/stx-labs/           # Main repo
/Users/alexanderhuth/Code/stx-labs/.conductor/
├── stuttgart/  # Main branch
└── kuwait/     # Feature branches
```

## 🎯 Why This Matters

**Git worktrees share commit history but NOT untracked files.**

Since `.env` is gitignored, each worktree needs its own copy. When you merge between worktrees, the `.env` doesn't automatically follow.

**Result**: After merge, the target worktree may be missing critical API keys.

**Solution**: Always check and copy `.env` before/after merging!

---

**See AGENTS.md** for full documentation and detailed troubleshooting.
