# UI Implementation Rules (Strict Adherence to DESIGN.md)

1. **Strict Design Conformity**: When `DESIGN.md` is provided, all layout structures, spacing tokens, color palettes, and typography specified therein must be followed verbatim.
2. **Zero Inlined Tokens**: Never hardcode arbitrary colors or fonts if design tokens are defined in `DESIGN.md`.
3. **No Credential Fields in UI**: Never add form inputs or text boxes asking the user for API keys on the frontend. Everything must be securely handled on the backend.
4. **Independent Latency Timing**: Measure round-trip client latency AND raw backend engine latency separately to distinguish network overhead from model compute time.
5. **Fail-Safe Visual States**: If an engine fails or times out, display a clear error badge on that specific engine card without breaking the opposing engine's result.

---

## Git & GitHub Conventions (Workflow Policies & Restrictions)
- **Branch Protection Policies**: Never push directly to `main`. Always create a feature branch (`feat/*`, `fix/*`).
- **Commit Conventions**: Follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `perf:`). Never commit unverified binaries, `.parquet` datasets, or `.env` files.
- **PR Requirements**: Before opening a PR, ensure local linting passes and commit messages contain ticket IDs.
- **Merge Prohibitions**: Never use force push (`git push --force`) or destructive rebases on shared branches.
- **Worktree Isolation**: When creating worktrees, keep them as siblings outside the root (`../arena-*`).
