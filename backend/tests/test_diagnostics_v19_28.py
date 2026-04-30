"""
test_diagnostics_v19_28.py — pin v19.28 Diagnostics endpoints +
decision-trail join logic.

Operator asked for a unified place to bring shadow trades, real
trades, scans, evals, and AI reasoning together for tuning. v19.28
ships the data spine: `services/decision_trail.py` does cross-
collection joins and `routers/diagnostics.py` exposes them.

These tests pin:
  - The trail builder's join order and output shape
  - The recent-decisions list filtering
  - The module scorecard's kill-candidate logic
  - The pipeline funnel stage labels + counts
  - The markdown export structure (so when operator pastes the
    report into chat, the LLM gets a stable schema)
  - The endpoint registration on the diagnostics router
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─── helpers ─────────────────────────────────────────────────────────────

class _FakeCollection:
    """Minimal Mongo-like collection. Returns docs from a fixed list."""
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if self._match(d, query):
                return dict(d)
        return None

    def find(self, query, projection=None, sort=None, limit=None):
        out = [dict(d) for d in self.docs if self._match(d, query)]
        if sort:
            for key, direction in reversed(sort):
                out.sort(key=lambda x: x.get(key) or "", reverse=(direction == -1))
        if limit:
            out = out[:limit]
        return out

    def count_documents(self, query):
        return sum(1 for d in self.docs if self._match(d, query))

    def aggregate(self, pipeline):
        # We don't fully simulate aggregate — tests for module scorecard
        # mock the whole `db["shadow_module_performance"]` access chain.
        return iter([])

    @staticmethod
    def _match(doc, query):
        for k, v in (query or {}).items():
            if k == "$or":
                if not any(_FakeCollection._match(doc, sub) for sub in v):
                    return False
                continue
            if isinstance(v, dict) and any(op.startswith("$") for op in v.keys()):
                # Handle minimal $gte/$lte/$in/$nin/$regex/$gt
                doc_v = doc.get(k)
                for op, target in v.items():
                    if op == "$gte" and not (doc_v is not None and doc_v >= target):
                        return False
                    if op == "$lte" and not (doc_v is not None and doc_v <= target):
                        return False
                    if op == "$gt" and not (doc_v is not None and doc_v > target):
                        return False
                    if op == "$in" and doc_v not in target:
                        return False
                    if op == "$nin" and doc_v in target:
                        return False
                    if op == "$regex":
                        import re
                        if not isinstance(doc_v, str) or not re.search(target, doc_v, re.I):
                            return False
                continue
            if doc.get(k) != v:
                return False
        return True


def _fake_db(collections):
    """Wrap a dict {name: [docs]} into a mongo-like db."""
    db = MagicMock()
    fakes = {name: _FakeCollection(docs) for name, docs in collections.items()}
    db.__getitem__.side_effect = lambda name: fakes.setdefault(name, _FakeCollection())
    return db


# ─── 1. build_decision_trail ─────────────────────────────────────────────

def test_trail_resolves_by_trade_id():
    """Trail builder must locate a `bot_trades` doc by id and join the
    matching shadow + thoughts in window."""
    from services.decision_trail import build_decision_trail
    trade = {
        "id": "T-100",
        "alert_id": "A-50",
        "symbol": "SOFI",
        "setup_type": "squeeze",
        "status": "closed",
        "executed_at": "2026-05-01T15:30:00+00:00",
        "created_at": "2026-05-01T15:29:30+00:00",
        "realized_pnl": 350,
        "entry_context": {
            "scan_tier": "T1",
            "smb_grade": "A",
            "exit_rule": "trail at +1R",
            "reasoning": ["fired on volume thrust"],
        },
    }
    shadow = {
        "id": "S-1",
        "trade_id": "T-100",
        "symbol": "SOFI",
        "trigger_type": "squeeze",
        "trigger_time": "2026-05-01T15:29:00+00:00",
        "was_executed": True,
        "debate_result": {"consensus": "BUY", "confidence": 75, "summary": "bull"},
        "risk_assessment": {"recommendation": "ALLOW", "rationale": "ok"},
        "modules_used": ["debate", "risk_council"],
    }
    db = _fake_db({
        "bot_trades": [trade],
        "shadow_decisions": [shadow],
        "sentcom_thoughts": [{
            "symbol": "SOFI",
            "timestamp": "2026-05-01T15:30:05+00:00",
            "text": "filled SOFI long",
        }],
    })
    out = build_decision_trail(db, "T-100")
    assert out is not None
    assert out["identifier_type"] == "trade_id"
    assert out["trade"]["id"] == "T-100"
    assert out["shadow"]["id"] == "S-1"
    assert out["alert"]["symbol"] == "SOFI"
    assert out["meta"]["outcome"] == "win"  # realized_pnl > 0
    assert out["meta"]["has_thoughts"] is True
    # Module votes flattened
    modules = [v["module"] for v in out["module_votes"]]
    assert "debate" in modules
    assert "risk_council" in modules


def test_trail_resolves_by_alert_id_when_no_trade_id_match():
    """If identifier matches `bot_trade.alert_id` field directly, use it."""
    from services.decision_trail import build_decision_trail
    db = _fake_db({
        "bot_trades": [{
            "id": "T-200", "alert_id": "A-99",
            "symbol": "HOOD", "setup_type": "ORB", "status": "open",
            "executed_at": "2026-05-01T14:00:00+00:00",
        }],
        "shadow_decisions": [],
        "sentcom_thoughts": [],
    })
    out = build_decision_trail(db, "A-99")
    assert out is not None
    assert out["identifier_type"] == "alert_id"
    assert out["trade"]["id"] == "T-200"
    assert out["meta"]["outcome"] == "open"


def test_trail_returns_none_when_nothing_matches():
    from services.decision_trail import build_decision_trail
    db = _fake_db({"bot_trades": [], "shadow_decisions": [], "sentcom_thoughts": []})
    assert build_decision_trail(db, "DOESNT_EXIST") is None


def test_trail_handles_shadow_only_passed_setup():
    """Shadow-only path: bot DIDN'T fire, but shadow tracked the
    decision forward. Trail builder must surface this with `outcome:
    'shadow_*'` and `trade: None`."""
    from services.decision_trail import build_decision_trail
    db = _fake_db({
        "bot_trades": [],
        "shadow_decisions": [{
            "id": "S-7", "trade_id": "A-77", "symbol": "TSLA",
            "trigger_type": "fade", "trigger_time": "2026-05-01T16:00:00+00:00",
            "was_executed": False, "outcome_tracked": True,
            "hypothetical_pnl": -120,
            "combined_recommendation": "BUY", "confidence_score": 65,
            "modules_used": ["debate", "timeseries"],
            "debate_result": {"consensus": "BUY", "confidence": 60},
        }],
        "sentcom_thoughts": [],
    })
    out = build_decision_trail(db, "S-7")
    assert out is not None
    assert out["trade"] is None
    assert out["shadow"]["id"] == "S-7"
    assert out["meta"]["outcome"] == "shadow_loss"


def test_trail_outcome_derivation_corner_cases():
    """`_derive_outcome` must handle: open trade, scratch trade,
    pending shadow."""
    from services.decision_trail import _derive_outcome
    assert _derive_outcome({"status": "open"}, None) == "open"
    assert _derive_outcome({"status": "closed", "realized_pnl": 0}, None) == "scratch"
    assert _derive_outcome(None, {"outcome_tracked": False}) == "shadow_pending"


# ─── 2. list_recent_decisions filtering ──────────────────────────────────

def test_list_recent_decisions_filters_by_symbol_and_outcome():
    """Symbol + outcome filters narrow the result set correctly."""
    from services.decision_trail import list_recent_decisions
    db = _fake_db({
        "bot_trades": [
            {"id": "T1", "symbol": "SOFI", "setup_type": "ORB",
             "status": "closed", "realized_pnl": 100,
             "created_at": "2026-05-01T15:00:00"},
            {"id": "T2", "symbol": "HOOD", "setup_type": "fade",
             "status": "closed", "realized_pnl": -50,
             "created_at": "2026-05-01T14:00:00"},
            {"id": "T3", "symbol": "SOFI", "setup_type": "squeeze",
             "status": "closed", "realized_pnl": -200,
             "created_at": "2026-05-01T13:00:00"},
        ],
        "shadow_decisions": [],
    })
    rows = list_recent_decisions(db, symbol="SOFI", outcome="loss")
    assert len(rows) == 1
    assert rows[0]["identifier"] == "T3"


def test_list_recent_decisions_skips_executed_shadows():
    """If a shadow decision was executed (`was_executed=True`), the
    matching `bot_trades` row already covers it — skip the shadow
    in the listing to avoid double-counting."""
    from services.decision_trail import list_recent_decisions
    db = _fake_db({
        "bot_trades": [{
            "id": "T-1", "symbol": "AAPL", "setup_type": "trend",
            "status": "open", "created_at": "2026-05-01T10:00:00",
        }],
        "shadow_decisions": [{
            "id": "S-1", "trade_id": "T-1", "symbol": "AAPL",
            "trigger_type": "trend", "trigger_time": "2026-05-01T10:00:00",
            "was_executed": True, "modules_used": ["debate"],
        }],
    })
    rows = list_recent_decisions(db)
    # Only the trade row, not the shadow duplicate.
    assert len(rows) == 1
    assert rows[0]["identifier"] == "T-1"


def test_list_recent_decisions_disagreements_filter():
    """only_disagreements keeps shadow rows where debate consensus
    diverged from combined recommendation."""
    from services.decision_trail import list_recent_decisions
    db = _fake_db({
        "bot_trades": [],
        "shadow_decisions": [
            {"id": "S-A", "symbol": "X", "trigger_type": "z",
             "trigger_time": "2026-05-01T11:00:00",
             "was_executed": False, "combined_recommendation": "BUY",
             "debate_result": {"consensus": "BUY"}, "modules_used": []},
            {"id": "S-B", "symbol": "Y", "trigger_type": "z",
             "trigger_time": "2026-05-01T10:00:00",
             "was_executed": False, "combined_recommendation": "PASS",
             "debate_result": {"consensus": "BUY"}, "modules_used": []},
        ],
    })
    rows = list_recent_decisions(db, only_disagreements=True)
    assert len(rows) == 1
    assert rows[0]["identifier"] == "S-B"


# ─── 3. module scorecard ─────────────────────────────────────────────────

def test_module_scorecard_marks_kill_candidate():
    """Kill candidate = accuracy < 50% AND followed P&L < ignored P&L.
    Scorecard sorts kill candidates first so operator's eye is drawn."""
    from services.decision_trail import build_module_scorecard

    # Mock the aggregate output
    db = MagicMock()
    perf_coll = MagicMock()
    perf_coll.aggregate.return_value = iter([
        {"_id": "loser_module", "total_decisions": 100,
         "accuracy_rate": 35, "avg_pnl_when_followed": -20,
         "avg_pnl_when_ignored": 5, "updated_at": "2026-05-01T00:00:00"},
        {"_id": "winner_module", "total_decisions": 200,
         "accuracy_rate": 70, "avg_pnl_when_followed": 12,
         "avg_pnl_when_ignored": -3, "updated_at": "2026-05-01T00:00:00"},
    ])
    weights_coll = MagicMock()
    weights_coll.find.return_value = [
        {"module": "loser_module", "weight": 0.5},
        {"module": "winner_module", "weight": 1.4},
    ]
    db.__getitem__.side_effect = lambda name: {
        "shadow_module_performance": perf_coll,
        "shadow_module_weights": weights_coll,
    }.get(name, MagicMock())
    out = build_module_scorecard(db, days=7)
    assert len(out["modules"]) == 2
    # Kill candidate sorted first
    assert out["modules"][0]["module"] == "loser_module"
    assert out["modules"][0]["kill_candidate"] is True
    assert out["modules"][1]["kill_candidate"] is False


# ─── 4. pipeline funnel ──────────────────────────────────────────────────

def test_pipeline_funnel_computes_stages_and_conversion():
    """Funnel emits 5 stages with conversion % between each.
    Counts pulled from shadow_decisions + bot_trades."""
    from services.decision_trail import build_pipeline_funnel
    db = MagicMock()

    shadow_coll = MagicMock()
    shadow_coll.count_documents.side_effect = [
        100,  # emitted
        40,   # ai_passed
        20,   # risk_passed
    ]
    trade_coll = MagicMock()
    trade_coll.count_documents.side_effect = [
        15,  # fired
        9,   # winners
    ]
    db.__getitem__.side_effect = lambda name: {
        "shadow_decisions": shadow_coll,
        "bot_trades": trade_coll,
    }.get(name, MagicMock())

    out = build_pipeline_funnel(db, days=1)
    stages = out["stages"]
    assert [s["stage"] for s in stages] == [
        "emitted", "ai_passed", "risk_passed", "fired", "winners"
    ]
    assert [s["count"] for s in stages] == [100, 40, 20, 15, 9]
    # Conversion % present from stage 2 onward
    assert stages[0].get("conversion_pct") is None
    assert stages[1]["conversion_pct"] == 40.0
    assert stages[2]["conversion_pct"] == 50.0
    assert stages[3]["conversion_pct"] == 75.0
    assert stages[4]["conversion_pct"] == 60.0


# ─── 5. markdown export ──────────────────────────────────────────────────

def test_export_report_markdown_has_all_sections():
    """Markdown must include: header, funnel table, scorecard table,
    recent decisions, paste-back footer. Operator pastes this into
    chat, so the schema needs to be stable for the LLM to parse."""
    from services.decision_trail import export_report_markdown
    db = _fake_db({
        "bot_trades": [{
            "id": "T1", "symbol": "SOFI", "setup_type": "ORB",
            "status": "closed", "realized_pnl": 100,
            "created_at": "2026-05-01T15:00:00",
        }],
        "shadow_decisions": [],
    })
    md = export_report_markdown(db, days=1)
    assert "# SentCom Diagnostics Report" in md
    assert "## 1. Pipeline Funnel" in md
    assert "## 2. Module Scorecard" in md
    assert "## 3. Recent Decisions" in md
    assert "Paste this into the chat for Emergent tuning suggestions." in md
    # Recent decisions row present
    assert "SOFI" in md


# ─── 6. Diagnostics router endpoints registered ──────────────────────────

def test_diagnostics_router_registers_all_endpoints():
    from routers.diagnostics import router
    paths = {r.path for r in router.routes}
    expected = {
        "/api/diagnostics/recent-decisions",
        "/api/diagnostics/decision-trail/{identifier}",
        "/api/diagnostics/module-scorecard",
        "/api/diagnostics/funnel",
        "/api/diagnostics/export-report",
    }
    missing = expected - paths
    assert not missing, f"Diagnostics router missing endpoints: {missing}"


def test_diagnostics_router_accepts_set_db():
    """`set_db` is the late-binding hook server.py uses on startup."""
    from routers.diagnostics import set_db, _db
    fake = MagicMock()
    set_db(fake)
    # Re-import to read the freshly set module-level _db
    import routers.diagnostics as diag
    assert diag._db is fake


# ─── 7. Frontend wiring (source-level pins) ──────────────────────────────

def test_diagnostics_page_file_exists_with_required_subtabs():
    p = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "pages" / "DiagnosticsPage.jsx"
    src = p.read_text()
    # Each sub-tab is a top-level component
    assert "TrailExplorer" in src
    assert "ModuleScorecard" in src
    assert "PipelineFunnel" in src
    assert "ExportReport" in src
    # Hits all 5 backend endpoints
    assert "/api/diagnostics/recent-decisions" in src
    assert "/api/diagnostics/decision-trail" in src
    assert "/api/diagnostics/module-scorecard" in src
    assert "/api/diagnostics/funnel" in src
    assert "/api/diagnostics/export-report" in src


def test_sidebar_has_diagnostics_nav_entry():
    p = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "Sidebar.js"
    src = p.read_text()
    assert "id: 'diagnostics'" in src
    assert "Diagnostics" in src


def test_app_routes_diagnostics_tab():
    p = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.js"
    src = p.read_text()
    assert "DiagnosticsPage" in src
    assert "case 'diagnostics'" in src
