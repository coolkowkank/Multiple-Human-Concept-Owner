"""Shared disposable fixtures for runner lane tests (fake data only)."""
import json, os, tempfile
import ryan_cycle as rc
T0 = 1_800_000_000.0
PACKET = [{"id": "P1", "title": "t", "passage": "alpha passage text here"},
          {"id": "P2", "title": "t", "passage": "beta passage text here"}]
NEM, LING = "nvidia/nemotron-3-ultra-550b-a55b", "novita/ling-3.1-flash"
FRESH = {"fetched_at": rc.iso(T0 - 60), "source": "fixture", "data": [
    {"id": NEM, "input_price": 0, "output_price": 0, "model_lab": "nvidia"},
    {"id": LING, "input_price": 0, "output_price": 0, "model_lab": "novita"},
    {"id": "google/gemma-4-31b-it", "input_price": 0, "output_price": 0, "model_lab": "google"}]}
RECORD = {"provider_blocks": {}, "routes": [
    {"id": m, "provider": "requesty", "status": "working"}
    for m in (NEM, LING, "google/gemma-4-31b-it")]}
ASSIGN = {"models": {"researcher": NEM, "verifier": LING, "ryan": NEM},
          "why": {r: "fixture" for r in rc.ROLES}, "decided_by": "main"}
ALLOWED = frozenset({NEM, LING})
OPEN_Q = {"id": "q1", "status": "open", "attempts": {}, "question": "?", "packet": PACKET}
def root_with(q, assign, base):
    d = tempfile.mkdtemp(dir=base)
    rc.Store(d).save_queue({"questions": [dict(q)]})
    with open(os.path.join(d, "assignments.json"), "w") as f:
        json.dump(assign, f)
    return d
