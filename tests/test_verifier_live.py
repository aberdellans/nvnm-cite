"""Live integration: the verifier core against the real NVNM testnet.

Phase 3 exit criterion. Reads are made against the NVNM-operated RPC; the
test is SKIPPED when that RPC is unreachable (offline CI) so the suite stays
green without network. Read-only: no writes, no gas. Demo gates baked in:
the fabricated Varghese cite (925 F.3d 1339) must come back NOT_FOUND, and a
real citation paired with an invented name must flag a name mismatch.
"""

from __future__ import annotations

import pytest

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc
from nvnm_cite.config import TESTNET_CHAIN_ID, load_dotenv
from nvnm_cite.config import testnet_rpc as _testnet_rpc  # aliased: 'test*' would be collected
from nvnm_cite.verifier.check import check_document
from nvnm_cite.verifier.resolver import ChainResolver


@pytest.fixture(scope="module")
def rpc_url() -> str:
    load_dotenv()
    url = _testnet_rpc()
    try:
        chain_id = EvmRpc(url, timeout=8).chain_id()
    except Exception as exc:  # offline / RPC down: skip, do not fail
        pytest.skip(f"NVNM testnet RPC unreachable: {exc}")
    if chain_id != TESTNET_CHAIN_ID:
        pytest.skip(f"unexpected chain id {chain_id} (wanted {TESTNET_CHAIN_ID})")
    return url


# Real first-page SCOTUS cites loaded in tranche 1 (us-scotus), a real-but-
# absent ca11 cite (the fabricated Varghese), a covered-but-wrong-name pair,
# an out-of-pilot circuit, a court-less reporter cite, and an orphan Id.
LIVE_BRIEF = """
Id. at 50. We start here. The right was recognized in Roe v. Wade,
410 U.S. 113 (1973). Segregation fell in Imaginary Plaintiff v.
Fictional Defendant, 347 U.S. 483 (1954). Defendants rely on Varghese v.
China Southern Airlines Co., 925 F.3d 1339 (11th Cir. 2019), which does
not exist. Out of circuit, see Smith v. Doe, 100 F.3d 200 (2d Cir. 1996).
And a court-less reporter cite, Foo v. Bar, 12 F.3d 34, ends it.
"""


def test_live_check_exercises_all_statuses(rpc_url: str):
    resolver = ChainResolver(lambda: EvmRpc(rpc_url))
    report = check_document(LIVE_BRIEF.encode(), "synthetic.txt", resolver)
    by = {c["canonical"] or c["as_written"]: c for c in report["citations"]}

    # VERIFIED against live chain state
    assert by["410 U.S. 113"]["status"] == "VERIFIED"
    assert by["410 U.S. 113"]["record"]["cases"], "a verified cite names a real case"
    # the exact, replayable query rides back with the verdict (non-repudiation)
    assert by["410 U.S. 113"]["query"]["params"][0]["to"] == pc.PRECOMPILE_ADDRESS

    # VERIFIED but the brief's parties do not match the chain's case name
    assert by["347 U.S. 483"]["status"] == "VERIFIED"
    assert by["347 U.S. 483"]["name_check"] == "mismatch"

    # the fabricated cite: real-looking, covered court, genuinely absent
    assert by["925 F.3d 1339"]["status"] == "NOT_FOUND"

    assert by["100 F.3d 200"]["status"] == "NOT_COVERED"  # 2d Cir., outside pilot
    assert by["12 F.3d 34"]["status"] == "AMBIGUOUS_JURISDICTION"  # no court parenthetical
    assert any(c["status"] == "UNPARSEABLE" for c in report["citations"])  # orphan Id.

    counts = report["summary"]["by_status"]
    assert counts["VERIFIED"] == 2
    assert counts["NOT_FOUND"] == 1
    assert counts["NOT_COVERED"] == 1
    assert report["summary"]["name_mismatches"] == 1
