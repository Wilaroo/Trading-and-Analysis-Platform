"""v19.34.176 — Stage A: IB-native sector tagging.

Replaces the Finnhub-based sector-tag fallback with IB
``reqContractDetailsAsync`` (Client 11, which IS connected on this
DGX rig). The Finnhub call is kept as the LAST fallback for cases
where IB doesn't return contract details (rare — usually delisted
or non-US symbols).

Two file changes:
  1. ``backend/services/ib_direct_service.py`` — adds new method
     ``async get_contract_industry(symbol)`` that returns IB's
     Reuters-sourced ``{industry, category, subcategory}`` triple.
  2. ``backend/services/sector_tag_service.py`` — inserts an IB
     lookup step between the Mongo cache and the Finnhub fallback.

Architecture per the file header comment that's been in
`sector_tag_service.py` since 2026-04-30:
    "Future: an IB `reqContractDetails`-based fallback can populate
     untagged symbols on-demand (a separate optional code path —
     kept out of this commit so the feature ships without IB
     dependency)."
The future is now.

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
IBD = os.path.join(ROOT, "services", "ib_direct_service.py")
STS = os.path.join(ROOT, "services", "sector_tag_service.py")


# ── ib_direct_service insertion ──────────────────────────────────
IBD_MARKER = "# ── v19.34.40 — Native MKT-close for EOD / manual / safety flatten ──"
IBD_INSERT = '''
    # ── v19.34.176 — IB-native industry / category lookup (Stage A) ──
    # Used by `sector_tag_service` to replace the Finnhub-based industry
    # fallback. IB's reqContractDetails returns a `category`/`industry`/
    # `subcategory` triple sourced from Reuters classifications. Free-form
    # strings — same shape as Finnhub — fed back through the existing
    # `_industry_to_etf` resolver, so the GICS→SPDR mapping is unchanged.
    async def get_contract_industry(self, symbol):
        """Return ``{'industry': str, 'category': str, 'subcategory': str}``
        for ``symbol`` via IB ``reqContractDetailsAsync``, or ``None`` on
        miss / error.
        """
        if not self._connected or not self._ib:
            return None
        try:
            from ib_async import Stock
        except ImportError:
            return None
        try:
            contract = Stock(symbol.upper(), "SMART", "USD")
            details = await self._ib.reqContractDetailsAsync(contract)
            if not details:
                return None
            cd = details[0]
            out = {
                "industry":    (getattr(cd, "industry", "") or "").strip(),
                "category":    (getattr(cd, "category", "") or "").strip(),
                "subcategory": (getattr(cd, "subcategory", "") or "").strip(),
            }
            if not any(out.values()):
                return None
            return out
        except Exception as exc:
            logger.debug(
                "[v19.34.176 get_contract_industry] %s lookup failed: %s",
                symbol, exc,
            )
            return None


'''


# ── sector_tag_service edit ──────────────────────────────────────
STS_ANCHOR_OLD = "        # 3. Finnhub fallback (network call). Gated behind a try/except —"
STS_ANCHOR_NEW = '''        # 3. v19.34.176 — IB-native `reqContractDetails` lookup BEFORE
        # Finnhub. Uses Client 11 (`ib_direct_service`, which IS
        # connected on this DGX rig). Returns IB's Reuters-sourced
        # `industry` / `category` / `subcategory` triple — same shape
        # as Finnhub, fed through the same `_industry_to_etf` resolver.
        # Results persisted to `symbol_adv_cache.sector` so future
        # lookups hit step 2 (Mongo cache) instantly.
        try:
            from services.ib_direct_service import get_ib_direct_service
            ib_direct = get_ib_direct_service()
            if ib_direct is not None:
                triple = await ib_direct.get_contract_industry(sym)
                if triple:
                    for key in ("category", "industry", "subcategory"):
                        ib_label = triple.get(key)
                        if not ib_label:
                            continue
                        etf = _industry_to_etf(ib_label)
                        if etf:
                            self._map[sym] = etf
                            if self.db is not None:
                                try:
                                    self.db["symbol_adv_cache"].update_one(
                                        {"symbol": sym},
                                        {"$set": {
                                            "sector": etf,
                                            "sector_name": SECTOR_ETFS.get(etf, etf),
                                            "sector_source": "ib_contract_details",
                                            "sector_source_industry": ib_label,
                                            "sector_source_triple": triple,
                                        }},
                                        upsert=True,
                                    )
                                except Exception as e:
                                    logger.debug(
                                        f"tag_symbol_async IB persist failed for {sym}: {e}"
                                    )
                            logger.info(
                                f"[SECTOR IB] {sym} \u2192 {etf} via IB {key} "
                                f"'{ib_label}' (persisted)"
                            )
                            return etf
        except Exception as e:
            logger.debug(f"tag_symbol_async IB lookup failed for {sym}: {e}")

        # 4. Finnhub fallback (network call). Gated behind a try/except —'''


def _backup(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v176.{stamp}"
    shutil.copy2(path, dst)
    return dst


def patch_ibd():
    with open(IBD, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.176 — IB-native industry / category lookup" in src:
        print("  - ib_direct_service.py already on v176 — skipping")
        return False
    if IBD_MARKER not in src:
        print(f"ERROR: marker not found in {IBD}")
        sys.exit(2)
    bak = _backup(IBD)
    print(f"  - Backup: {bak}")
    # Insert IBD_INSERT immediately before the marker line.
    src = src.replace(IBD_MARKER, IBD_INSERT.lstrip() + "    " + IBD_MARKER, 1)
    with open(IBD, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - ib_direct_service.py patched (added get_contract_industry)")
    return True


def patch_sts():
    with open(STS, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.176 — IB-native `reqContractDetails` lookup BEFORE" in src:
        print("  - sector_tag_service.py already on v176 — skipping")
        return False
    if STS_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {STS}")
        sys.exit(3)
    bak = _backup(STS)
    print(f"  - Backup: {bak}")
    src = src.replace(STS_ANCHOR_OLD, STS_ANCHOR_NEW, 1)
    with open(STS, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - sector_tag_service.py patched (IB lookup step inserted)")
    return True


def main():
    print("=" * 60)
    print("v19.34.176 — Stage A: IB-native sector tagging")
    print("=" * 60)
    a = patch_ibd()
    b = patch_sts()
    print()
    print(f"ib_direct_service.py changed:    {a}")
    print(f"sector_tag_service.py changed:   {b}")
    print()
    # Parse-check both
    import ast
    for p in (IBD, STS):
        with open(p, "r", encoding="utf-8") as f:
            ast.parse(f.read())
    print("  - syntax check: OK")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'v19.34.176: IB-native sector tagging' && git push")
    print("  2. Restart backend (fire your .bat from Windows)")
    print("  3. After ~30s verify:")
    print("     grep -c '[SECTOR IB]' /tmp/backend.log     # should grow as new symbols evaluated")
    print("     grep -c '[SECTOR FALLBACK]' /tmp/backend.log # Finnhub usage — should plateau / shrink")


if __name__ == "__main__":
    main()
