# v0.4 test results — local developer validation

- Python unit tests: **7 passed**
- Synthetic 15,000-record v0001 and v0002 generation: **passed**
- v0001 local content-addressed publish: **55 new, 4 reused blob references**
- v0002 local content-addressed publish: **1 new, 58 reused blob references**
- Deep audit across both versions: **passed**
- Rollback v0002 → v0001 and previous-version readback: **passed**
- Synthetic release marker title search record/year verification after rollback: **passed**
- JavaScript browser client syntax check (Node.js): **passed**
- GitHub Actions YAML parse: **passed**
- Git worktree `catalog-state` initial push and later restoration/push simulation: **passed**
- **Live GitHub Actions deployment of v0.4: not yet tested.**
- Real BookBridge catalog upload: **not performed**.
