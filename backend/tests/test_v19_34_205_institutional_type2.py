"""v19.34.205 — IB ReportsOwnership -> institutional ownership % (type-2)."""
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


def test_sums_only_type2():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_000_000_000)
    assert out["num_institutional_holders"] == 2
    assert out["total_institutional_shares"] == 700_000_000.0
    assert out["institutional_ownership_percent"] == 70.0


def test_falls_back_to_float_denom():
    out = parse_reports_ownership(_OWNERSHIP)
    assert out["institutional_ownership_percent"] == 70.0


def test_pct_capped_at_100():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=500_000_000)
    assert out["institutional_ownership_percent"] == 100.0


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
