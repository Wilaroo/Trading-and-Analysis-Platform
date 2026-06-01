"""v19.34.204 — IB ReportsOwnership -> institutional ownership % (R4)."""
from services.ib_fundamentals_parser import parse_reports_ownership

_OWNERSHIP = """<OwnershipDetails>
   <floatShares asofDate="2026-03-19">1000000000</floatShares>
   <Owner ownerId="A"><type>2</type><name>BlackRock</name>
      <quantity asofDate="2026-03-31">300000000</quantity></Owner>
   <Owner ownerId="B"><type>5</type><name>Vanguard</name>
      <quantity asofDate="2026-03-31">250000000</quantity></Owner>
   <Owner ownerId="C"><type>5</type><name>State Street</name>
      <quantity asofDate="2026-03-31">150000000</quantity></Owner>
</OwnershipDetails>"""


def test_sums_holders_and_pct():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_600_000_000)
    assert out["num_institutional_holders"] == 3
    assert out["total_institutional_shares"] == 700_000_000.0
    assert out["float_shares"] == 1_000_000_000.0
    assert out["institutional_ownership_percent"] == 43.75


def test_falls_back_to_float():
    out = parse_reports_ownership(_OWNERSHIP)
    assert out["institutional_ownership_percent"] == 70.0


def test_pct_capped_at_100():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=500_000_000)
    assert out["institutional_ownership_percent"] == 100.0


def test_bad_xml_returns_empty():
    assert parse_reports_ownership("<not valid") == {}


def test_no_owners_no_pct():
    out = parse_reports_ownership(
        "<OwnershipDetails><floatShares>100</floatShares></OwnershipDetails>",
        shares_outstanding=1000)
    assert "institutional_ownership_percent" not in out
    assert out["num_institutional_holders"] == 0
