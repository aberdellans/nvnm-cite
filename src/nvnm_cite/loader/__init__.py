"""Corpus pipeline: CourtListener bulk data in, testnet registries out.

courtlistener.py  three-pass streaming join -> corpus.sqlite   (task 2.1)
bulk_load.py      checkpointed chain writer                    (task 2.4)
reconcile.py      corpus vs chain-index diff                   (task 2.5)

Case data comes from CourtListener bulk data, a Free Law Project service
(courtlistener.com); attribution travels in README, registry metadata,
and demos.
"""
