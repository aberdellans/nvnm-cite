"""Filing receipts: the minimal, non-enumerating receipt v1 and the
per-firm-per-case registries that hold them (Phase 4).

A receipt records the document SHA-256 + provenance + a non-identifying
status tally — never the list of cited cases (DECISIONS 2026-06-13 items
2/2b). It lives in a registry owned by the filing party's own wallet, named
by the filer (item 3; naming format settled 2026-06-15). Anchoring is a
chain WRITE and happens only behind an explicit flag, after the plan is
shown and approved.
"""
