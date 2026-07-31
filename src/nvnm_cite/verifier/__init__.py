"""Shared citation verifier: extract -> normalize -> live chain read -> status.

The one verification path, called by both ``nvnm-cite check`` (cli.py) and
the web app. Drafting-time checks read NVNM Chain LIVE via a keyed
``records()`` ``eth_call`` against the NVNM-operated RPC (item 0, DECISIONS
2026-06-13), so the answer is the chain's and is independently replayable;
the local index is only a rebuildable audit/cache, never the authority.
"""

from nvnm_cite.verifier.check import (
    AMBIGUOUS,
    CHAIN_SOURCE,
    EXPANDED_COVERAGE_CAUTION,
    FEDERAL_APPELLATE,
    NOT_COVERED,
    NOT_FOUND,
    STATUS_CHARS,
    STATUS_ORDER,
    UNPARSEABLE,
    VERIFIED,
    CheckError,
    check_document,
    check_text,
    default_registry_ids,
    name_check,
    record_cases,
    record_cluster,
    record_names,
    record_view,
)
from nvnm_cite.verifier.extract import Extraction, ExtractError, extract_text
from nvnm_cite.verifier.resolver import ChainResolver, Resolution, Resolver, records_query

__all__ = [
    "AMBIGUOUS",
    "CHAIN_SOURCE",
    "EXPANDED_COVERAGE_CAUTION",
    "FEDERAL_APPELLATE",
    "ChainResolver",
    "CheckError",
    "Extraction",
    "ExtractError",
    "NOT_COVERED",
    "NOT_FOUND",
    "Resolution",
    "Resolver",
    "STATUS_CHARS",
    "STATUS_ORDER",
    "UNPARSEABLE",
    "VERIFIED",
    "check_document",
    "check_text",
    "default_registry_ids",
    "extract_text",
    "name_check",
    "record_cases",
    "record_cluster",
    "record_names",
    "record_view",
    "records_query",
]
