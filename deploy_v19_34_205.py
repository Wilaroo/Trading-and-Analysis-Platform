#!/usr/bin/env python3
"""
deploy_v19_34_205.py — fix institutional ownership (type-2 only, accurate denom).

The v204 parser summed ALL owner <type>s → ~2x shares-out → 100% for every
symbol. This sums only type==2 (Investment Advisor / 13F institution) and
fetches shares-outstanding for the denominator when it's not cached.

Robust deploy: replaces the WHOLE parse_reports_ownership() by slicing from its
signature to EOF (so it doesn't matter what the old body looked like), and
anchors a small insert into refresh_institutional_ownership. Transactional.

Run (DGX, from repo root):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python /tmp/deploy_v19_34_205.py
Then, if ✅ ALL VERIFIED:
    git add -A && git commit -m "v19.34.205 institutional ownership type-2 fix" && git push && ./start_backend.sh --force
"""
import os
import py_compile
import subprocess
import sys

ROOT = os.path.expanduser("~/Trading-and-Analysis-Platform")
B = os.path.join(ROOT, "backend")
PARSER = os.path.join(B, "services/ib_fundamentals_parser.py")
CACHE = os.path.join(B, "services/unified_fundamentals_cache.py")
TEST_NEW = os.path.join(B, "tests/test_v19_34_205_institutional_type2.py")
TEST_OLD = os.path.join(B, "tests/test_v19_34_204_institutional_ownership.py")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


NEW_OWNERSHIP_FUNC = '''def parse_reports_ownership(
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
'''

CACHE_OLD = '''        if cached:
            shares_out = cached.get("shares_outstanding")

        xml = await ibd.get_fundamental_report(symbol, "ReportsOwnership",'''
CACHE_NEW = '''        if cached:
            shares_out = cached.get("shares_outstanding")
        if not shares_out:
            # v19.34.205 — fetch ReportSnapshot (~10KB) for an accurate
            # institutional-% denominator when shares-out isn't cached yet.
            snap = await ibd.get_fundamental_report(symbol, "ReportSnapshot")
            if snap:
                from services.ib_fundamentals_parser import parse_report_snapshot
                shares_out = parse_report_snapshot(snap).get("shares_outstanding")

        xml = await ibd.get_fundamental_report(symbol, "ReportsOwnership",'''

TEST_BODY = '''"""v19.34.205 — IB ReportsOwnership -> institutional ownership % (type-2)."""
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
'''


def main():
    # ---- stage parser: replace whole function from signature to EOF ----
    if not os.path.exists(PARSER):
        print(f"🔴 ABORT: missing {PARSER}")
        return 1
    ps = read(PARSER)
    if 'institutional_type: str = "2"' in ps:
        print("  ↩ parser: type-2 version already present (skip)")
        parser_new = ps
    else:
        idx = ps.find("def parse_reports_ownership(")
        if idx == -1:
            print("🔴 ABORT: parse_reports_ownership not found in parser")
            return 1
        # keep everything up to (and incl) the blank line(s) before the def
        head = ps[:idx].rstrip("\n")
        parser_new = head + "\n\n\n" + NEW_OWNERSHIP_FUNC

    # ---- stage cache: insert shares-out fetch ----
    if not os.path.exists(CACHE):
        print(f"🔴 ABORT: missing {CACHE}")
        return 1
    cs = read(CACHE)
    if "v19.34.205 — fetch ReportSnapshot" in cs:
        print("  ↩ cache: shares-out fetch already present (skip)")
        cache_new = cs
    elif CACHE_OLD in cs:
        cache_new = cs.replace(CACHE_OLD, CACHE_NEW, 1)
    else:
        print("🔴 ABORT: refresh anchor not found in unified_fundamentals_cache.py")
        print("   → paste me that file and I'll regenerate.")
        return 1

    # ---- commit to disk ----
    with open(PARSER, "w", encoding="utf-8") as f:
        f.write(parser_new)
    print("  ✓ wrote services/ib_fundamentals_parser.py")
    with open(CACHE, "w", encoding="utf-8") as f:
        f.write(cache_new)
    print("  ✓ wrote services/unified_fundamentals_cache.py")
    with open(TEST_NEW, "w", encoding="utf-8") as f:
        f.write(TEST_BODY)
    print("  ✓ wrote tests/test_v19_34_205_institutional_type2.py")
    if os.path.exists(TEST_OLD):
        os.remove(TEST_OLD)
        print("  ✓ removed stale tests/test_v19_34_204_institutional_ownership.py")

    print("\n── py_compile ──")
    for path in (PARSER, CACHE, TEST_NEW):
        try:
            py_compile.compile(path, doraise=True)
            print(f"  ✓ {os.path.basename(path)}")
        except py_compile.PyCompileError as e:
            print(f"🔴 COMPILE FAILED: {e}")
            return 1

    print("\n── pytest ──")
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_v19_34_205_institutional_type2.py", "-q"], cwd=B)
    if r.returncode != 0:
        print("🔴 pytest FAILED")
        return 1

    print("\n✅ ALL VERIFIED. Now commit + restart:")
    print('  git add -A && git commit -m "v19.34.205 institutional ownership '
          'type-2 fix" && git push && ./start_backend.sh --force')
    print("\n  Then re-run the refresh to overwrite the bad 100% rows:")
    print("  curl -s -X POST http://localhost:8001/api/scheduler/run/"
          "institutional_ownership_refresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
