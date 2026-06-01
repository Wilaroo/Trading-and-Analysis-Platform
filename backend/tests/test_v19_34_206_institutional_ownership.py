"""v19.34.206 — IB ReportsOwnership -> institutional ownership %.

Sums type-2 (13F investment-advisor) holdings, EXCLUDING any single holder
whose quantity exceeds 50% of shares-outstanding (control-stake / stale
parent-stake artifacts like AXA in AB at 182% or HNA in AAMI at 64%), then
caps the aggregate at 100%.
"""
from services.ib_fundamentals_parser import parse_reports_ownership

_OWNERSHIP = """<OwnershipDetails>
   <floatShares asofDate="2026-03-19">1000000000</floatShares>
   <Owner ownerId="A"><type>2</type><name>BlackRock</name>
      <quantity asofDate="2026-03-31">400000000</quantity></Owner>
   <Owner ownerId="B"><type>2</type><name>Vanguard</name>
      <quantity asofDate="2026-03-31">300000000</quantity></Owner>
   <Owner ownerId="C"><type>5</type><name>Vanguard 500 Fund</name>
      <quantity asofDate="2026-03-31">250000000</quantity></Owner>
   <Owner ownerId="D"><type>1</type><name>CEO</name>
      <quantity asofDate="2026-03-31">50000000</quantity></Owner>
</OwnershipDetails>"""

# Mirrors the real AB/AAMI failure mode: a single corrupt control-stake holder
# that pushes the naive sum past 100%.
_OWNERSHIP_CONTROL_ARTIFACT = """<OwnershipDetails>
   <floatShares asofDate="2026-02-25">90000000</floatShares>
   <Owner ownerId="AXA"><type>2</type><name>AXA Financial Inc.</name>
      <quantity asofDate="2025-09-30">170000000</quantity></Owner>
   <Owner ownerId="FID"><type>2</type><name>Fidelity</name>
      <quantity asofDate="2026-03-31">20000000</quantity></Owner>
   <Owner ownerId="JAN"><type>2</type><name>Janus</name>
      <quantity asofDate="2026-03-31">9000000</quantity></Owner>
</OwnershipDetails>"""


def test_sums_only_type2():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_000_000_000)
    assert out["num_institutional_holders"] == 2
    assert out["total_institutional_shares"] == 700_000_000.0
    assert out["institutional_ownership_percent"] == 70.0
    assert out["excluded_control_holders"] == 0


def test_falls_back_to_float_denom():
    out = parse_reports_ownership(_OWNERSHIP)
    assert out["institutional_ownership_percent"] == 70.0


def test_pct_capped_at_100():
    # shares_out=600M: BlackRock(400M) is 66% > 50% cap -> excluded as a
    # control stake; Vanguard(300M)=50% kept -> 50%.
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=600_000_000)
    assert out["excluded_control_holders"] == 1
    assert out["num_institutional_holders"] == 1
    assert out["institutional_ownership_percent"] == 50.0


def test_configurable_type():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_000_000_000,
                                  institutional_type="5")
    assert out["total_institutional_shares"] == 250_000_000.0
    assert out["institutional_ownership_percent"] == 25.0


def test_bad_xml_returns_empty():
    assert parse_reports_ownership("<not valid") == {}


def test_no_type2_no_pct():
    out = parse_reports_ownership(
        "<OwnershipDetails><floatShares>100</floatShares>"
        "<Owner><type>5</type><quantity>10</quantity></Owner></OwnershipDetails>",
        shares_outstanding=1000)
    assert "institutional_ownership_percent" not in out
    assert out["num_institutional_holders"] == 0


def test_excludes_control_stake_artifact():
    """The real AB/AAMI bug: a single >50% holder (AXA at 189%) must be
    dropped so the figure reflects free-float institutional ownership."""
    out = parse_reports_ownership(_OWNERSHIP_CONTROL_ARTIFACT,
                                  shares_outstanding=90_000_000)
    # AXA (170M = 189% of 90M) excluded; Fidelity(20M)+Janus(9M)=29M kept.
    assert out["excluded_control_holders"] == 1
    assert out["num_institutional_holders"] == 2
    assert out["total_institutional_shares"] == 29_000_000.0
    assert out["institutional_ownership_percent"] == round(100 * 29 / 90, 2)


def test_custom_holder_cap_fraction():
    # With a stricter 25% cap, Vanguard(300M=30%) and BlackRock(400M=40%) on a
    # 1B float are both excluded -> no institutional holders remain.
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_000_000_000,
                                  max_single_holder_frac=0.25)
    assert out["excluded_control_holders"] == 2
    assert out["num_institutional_holders"] == 0
