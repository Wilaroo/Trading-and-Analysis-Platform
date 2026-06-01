"""IB ReportSnapshot XML → structured dict (v19.34.177).

ReportSnapshot is an XML document with this rough shape:

    <ReportSnapshot>
      <CoIDs> ... </CoIDs>
      <CoGeneralInfo>
        <CompanyHeadquarters HeadquartersCountry="US" ... />
        <CommonShares>...</CommonShares>
        ...
      </CoGeneralInfo>
      <Ratios>
        <Group ID="Income Statement">
          <Ratio FieldName="PEEXCLXOR">28.4</Ratio>
          ...
        </Group>
        <Group ID="Valuation">
          <Ratio FieldName="MKTCAP">3500000.0</Ratio>
          <Ratio FieldName="PR2BK">45.2</Ratio>
          ...
        </Group>
        <Group ID="Per Share Data">...</Group>
      </Ratios>
      <ForecastData>...</ForecastData>
    </ReportSnapshot>

We parse only the fields actually consumed downstream:
  pe_ratio, market_cap, beta, price_to_book, dividend_yield,
  eps_growth, roe, high_52w, low_52w, employees, country,
  industry, sector.

Short interest, float shares, and institutional ownership are NOT in
ReportSnapshot — they come from `ReportsOwnership` (separate report)
or Finnhub fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# Map IB FieldName -> our canonical key + type
_RATIO_FIELDS = {
    "PEEXCLXOR":   ("pe_ratio", float),
    "MKTCAP":      ("market_cap_millions", float),
    "BETA":        ("beta", float),
    "PR2BK":       ("price_to_book", float),
    "DivYieldPCT": ("dividend_yield_pct", float),
    "EPSCHANGE":   ("eps_change_pct", float),
    "ROEPCT":      ("roe_pct", float),
    "NHIG":        ("high_52w", float),  # 52-week high
    "NLOW":        ("low_52w", float),
    "VOL10DAVG":   ("vol_10d_avg", float),
    "TTMNIPEREM":  ("net_margin_pct", float),
    "QCURRATIO":   ("current_ratio", float),
    "QTOTD2EQ":    ("debt_to_equity", float),
}


def parse_report_snapshot(xml_str: Optional[str]) -> Dict[str, Any]:
    """Parse IB ReportSnapshot XML into a flat dict. Tolerates empty /
    malformed input — returns {} on any parse error.
    """
    if not xml_str or not isinstance(xml_str, str):
        return {}
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        logger.debug("ReportSnapshot parse failed: %s", exc)
        return {}

    out: Dict[str, Any] = {}

    # Ratios (the main numeric block)
    for ratio in root.iter("Ratio"):
        field = ratio.get("FieldName")
        if not field or field not in _RATIO_FIELDS:
            continue
        canonical, caster = _RATIO_FIELDS[field]
        txt = (ratio.text or "").strip()
        if not txt:
            continue
        try:
            out[canonical] = caster(txt)
        except (TypeError, ValueError):
            continue

    # CoGeneralInfo — country, employees, etc.
    for hq in root.iter("CompanyHeadquarters"):
        country = hq.get("HeadquartersCountry")
        if country:
            out["country"] = country.strip()

    employees = root.find(".//Employees")
    if employees is not None and employees.text:
        try:
            out["employees"] = int(float(employees.text.strip()))
        except (TypeError, ValueError):
            pass

    # CoGeneralInfo/SharesOut → shares outstanding (text) + float (TotalFloat
    # attr). v19.34.202 — e.g. <SharesOut TotalFloat="1623871179.0">1630600639.0</SharesOut>
    shares_out = root.find(".//CoGeneralInfo/SharesOut")
    if shares_out is not None:
        txt = (shares_out.text or "").strip()
        if txt:
            try:
                out["shares_outstanding"] = float(txt)
            except (TypeError, ValueError):
                pass
        total_float = shares_out.get("TotalFloat")
        if total_float:
            try:
                out["float_shares"] = float(total_float)
            except (TypeError, ValueError):
                pass

    # Reuters industry / sector
    for indinfo in root.iter("Industry"):
        # IB tags Industry nodes with a `type` attribute ("TRBC", "NAICS", etc.)
        if indinfo.get("type", "").upper() == "TRBC":
            txt = (indinfo.text or "").strip()
            if txt:
                out["industry_trbc"] = txt
        elif indinfo.get("type", "").upper() == "NAICS":
            txt = (indinfo.text or "").strip()
            if txt:
                out["industry_naics"] = txt

    # Issue / Exchange
    issue = root.find(".//Issue")
    if issue is not None:
        exch = issue.get("type", "")
        if exch:
            out["issue_type"] = exch

    # Multiply MKTCAP up to absolute dollars (IB reports in millions)
    if "market_cap_millions" in out:
        out["market_cap"] = out["market_cap_millions"] * 1_000_000

    # Convert dividend yield to decimal (IB reports as PCT)
    if "dividend_yield_pct" in out and "dividend_yield" not in out:
        out["dividend_yield"] = out["dividend_yield_pct"] / 100.0

    return out


def parse_reports_ownership(
    xml: str, shares_outstanding: Optional[float] = None,
    institutional_type: str = "2",
) -> Dict[str, Any]:
    """v19.34.205 — parse IB ``ReportsOwnership`` XML -> institutional ownership.

    The doc groups holders by a ``<type>`` code. Summing ALL types double-counts
    (a mutual fund's shares are also counted inside its parent investment
    advisor's 13F) -> ~2x shares-outstanding. We sum ONLY ``type==2``
    (Investment Advisor / 13F institution; AMD = 75.5% vs ~70% reported).

    institutional ownership % = sum(type-2 quantities) / shares-outstanding
    (falls back to / floatShares), capped at 100%. Streams via iterparse +
    elem.clear(). Returns {} on parse failure.
    """
    import io

    total_shares = 0.0
    holders = 0
    float_shares = None
    try:
        for _event, elem in ET.iterparse(io.StringIO(xml), events=("end",)):
            tag = elem.tag
            if tag == "floatShares":
                try:
                    float_shares = float((elem.text or "").strip())
                except (TypeError, ValueError):
                    pass
                elem.clear()
            elif tag == "Owner":
                t_el = elem.find("type")
                otype = (t_el.text or "").strip() if t_el is not None else ""
                if otype == institutional_type:
                    q_el = elem.find("quantity")
                    if q_el is not None:
                        try:
                            total_shares += float((q_el.text or "0").strip())
                            holders += 1
                        except (TypeError, ValueError):
                            pass
                elem.clear()
    except ET.ParseError as exc:
        logger.debug("parse_reports_ownership failed: %s", exc)
        return {}

    out = {
        "total_institutional_shares": total_shares,
        "num_institutional_holders": holders,
    }
    if float_shares:
        out["float_shares"] = float_shares
    denom = shares_outstanding or float_shares
    if denom and denom > 0 and total_shares > 0:
        out["institutional_ownership_percent"] = min(
            round(100.0 * total_shares / denom, 2), 100.0
        )
    return out
