#!/bin/sh
# Fresh-environment recovery check. Clones a repo+ref into a new temp dir,
# builds a new venv with the pinned packages, scrubs the environment, runs
# handover_check.py env and every *_test.py. Needs network ONLY for git clone
# and pip (package and source download). It makes no model or provider
# request, reads no key, and uses a throwaway git identity (your global git
# config is not touched). HOME stays the account home on purpose: the reserve
# preflight and live_entry_test refuse a moved HOME.
#   sh handover_fresh_check.sh REPO_URL_OR_PATH REF
set -u
URL="${1:?repo url or path}"; REF="${2:?ref (branch, tag or commit)}"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
printf '[user]\n\tname = fresh-check\n\temail = fresh-check@example.invalid\n' > "$W/gitconfig"
CLEAN="env -i PATH=$PATH HOME=$HOME GIT_CONFIG_GLOBAL=$W/gitconfig LG_VERIFY_SANDBOX=1"
git clone -q "$URL" "$W/repo" && git -C "$W/repo" checkout -q "$REF" || { echo "FRESH-CHECK FAIL: clone/checkout"; exit 1; }
HEAD="$(git -C "$W/repo" rev-parse HEAD)"
python3 -m venv "$W/venv" || { echo "FRESH-CHECK FAIL: venv"; exit 1; }
"$W/venv/bin/pip" install -q langgraph==1.2.19 langgraph-checkpoint-sqlite==3.1.3 || { echo "FRESH-CHECK FAIL: pip"; exit 1; }
D="$W/repo/integration/langgraph"; cd "$D" || exit 1
$CLEAN "$W/venv/bin/python" handover_check.py env > "$W/env.json"; ENVRC=$?
ls *_test.py | xargs -P 8 -I{} sh -c "$CLEAN timeout 100 $W/venv/bin/python {} > $W/{}.out 2>&1; echo {} \$? >> $W/results.txt"
N=$(wc -l < "$W/results.txt"); BAD=$(awk '$2!=0' "$W/results.txt")
echo "ref=$REF head=$HEAD env_check_rc=$ENVRC test_files=$N"
if [ -n "$BAD" ]; then echo "FRESH-CHECK FAIL: $BAD"; exit 1; fi
[ "$ENVRC" -eq 0 ] || { echo "FRESH-CHECK FAIL: env check blocking, see handover_check.py env"; cat "$W/env.json"; exit 1; }
[ -d "$HOME/.lg-http-usage" ] && echo "NOTE: $HOME/.lg-http-usage exists (this script does not create it)"
echo "FRESH-CHECK OK: all $N test files exit 0 in a new clone and venv; no request was made. Offline only; not a live qualification."
