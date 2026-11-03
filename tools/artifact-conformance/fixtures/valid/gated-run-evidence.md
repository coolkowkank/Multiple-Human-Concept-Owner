# Gated run evidence

| Field | Value |
| --- | --- |
| Decision record | DR-003 |
| Target and scope | hosted smoke run, synthetic project, initialization only |
| Environment | hosted + synthetic test account |
| Counts before / after | 0 rows before, 3 rows after |
| Test identity | ./team verify @ 0123456789abcdef0123456789abcdef01234567 |
| Rows / objects touched | 3 synthetic rows |
| Cleanup | deleted all 3 synthetic rows; observed count back to 0 |
| Not proven | endurance, concurrent seats, owner-account permissions |
| No-secrets check | no credentials or private data in repo, logs or evidence |
