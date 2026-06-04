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
    max_single_holder_frac: float = 0.5,
) -> Dict[str, Any]:
    """v19.34.206 -- parse IB ``ReportsOwnership`` XML into institutional ownership.

    The doc is multi-MB (thousands of ``<Owner>`` holdings) and groups holders
    by a ``<type>`` code. We sum ONLY the institutional bucket ``type==2``
    (Investment Advisor / 13F institution -- the standard "institutional
    ownership" figure; AMD = 75.5% vs ~70% publicly reported).

        <OwnershipDetails>
          <floatShares asofDate="...">1623418512</floatShares>
          <Owner ownerId="..."><type>2</type><name>...</name>
            <quantity asofDate="...">505377</quantity></Owner>
          ...
        </OwnershipDetails>

    **Control-stake / stale-artifact guard (v19.34.206).** IB's Refinitiv feed
    carries stale "controlling stake" holdings that inflate the sum past 100%
    of shares-outstanding -- e.g. AB shows ``AXA Financial`` at 182% (a divested
    parent stake on the operating partnership, mis-tagged onto the public
    units) and AAMI shows ``HNA Capital Group`` at 64% (a divested former
    parent). Both are single holders far above any plausible free-float 13F
    position. We therefore EXCLUDE any single type-2 holder whose quantity
    exceeds ``max_single_holder_frac`` (default 50%) of the denominator -- a
    >50% single "institution" is a control/strategic stake, not free-float
    institutional ownership. Clean large-caps (AMD, largest holder ~8%) are
    unaffected.

    institutional ownership % = sum(in-bound type-2 quantities) /
    shares-outstanding (falls back to / floatShares), capped at 100%. Streams
    via ``iterparse`` + ``elem.clear()``. Returns {} on parse failure.
    """
    import io

    quantities = []  # raw type-2 holder quantities (pre-filter)
    float_shares: Optional[float] = None
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
                            quantities.append(float((q_el.text or "0").strip()))
                        except (TypeError, ValueError):
                            pass
                elem.clear()
    except ET.ParseError as exc:
        logger.debug("parse_reports_ownership failed: %s", exc)
        return {}

    denom = shares_outstanding or float_shares
    cap = (max_single_holder_frac * denom) if (denom and denom > 0) else None

    total_shares = 0.0
    holders = 0
    excluded = 0
    for q in quantities:
        if cap is not None and q > cap:
            excluded += 1
            continue
        total_shares += q
        holders += 1

    out: Dict[str, Any] = {
        "total_institutional_shares": total_shares,
        "num_institutional_holders": holders,
        "excluded_control_holders": excluded,
    }
    if float_shares:
        out["float_shares"] = float_shares
    if denom and denom > 0 and total_shares > 0:
        out["institutional_ownership_percent"] = min(
            round(100.0 * total_shares / denom, 2), 100.0
        )
    return out
