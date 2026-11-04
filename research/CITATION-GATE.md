# Citation gate for Researcher publications (enforced 2026-11-04)

Applies to everything under `research/**`. Motivation: in the 2026-11-04
seat trial, the Researcher model (Nemotron-3 Ultra 550B) produced a
fabricated citation (wrong authors, wrong title, dead URL, stated as high
confidence) and a real paper with a wrong DOI. Prompt wording alone is not
proof against fabrication; this gate is the enforcement layer.

## Rules
1. Packet-only citation. A finding may cite only sources in its source
   packet, by packet ID. The packet is supplied with the task; the model
   must not add sources from memory.
2. Packet entries come from actual reads. A packet entry records: title,
   authors, year, DOI or URL, read date, and the specific claims the source
   was verified to support. Generated metadata never creates a packet
   entry.
3. Verification is semantic, not transport. Before a citation is
   published, the coordinator checks: the source exists; authors/title/
   identifier match; and the cited passage supports the claim made. An
   HTTP 200 alone is not verification.
4. Explicit unknowns. Claims the packet does not support are labeled
   UNVERIFIED; needed but absent sources are reported as MISSING SOURCE
   naming the gap. Neither may be silently filled from model memory.
5. Publication block. A finding with an unchecked or failed citation is
   not published; it goes back with the failing citation marked.

## Trial evidence
- Trial 1 (no packet, 2026-11-04): 1 fabricated citation, 1 real paper
  with wrong DOI, 1 unverified URL out of 3 cited.
- Trial 2 (packet rule, 2026-11-04): 3/3 compliant - packet IDs cited
  correctly; unsupported questions answered UNVERIFIED; an out-of-packet
  citation request answered MISSING SOURCE. Details in
  findings/2026-11-04-nora-model-trial.md. One bounded trial does not
  prove the behavior is stable; the gate applies regardless.
