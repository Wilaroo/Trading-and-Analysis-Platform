## v19.34.273 — UI Track A · A2 "provenance ring" — 2026-06-20
- Compact SVG ring on each scanner row: 5 equal arcs (setup · technical ·
  fundamental · context · execution), each colored by that pillar's grade, with
  the overall TQS grade in the center. Composition at a glance; the TQS badge
  still shows the precise number. Hover → all 5 pillar grades; click → TQS drawer.
- Frontend-only: the scanner payload already carries tqs_pillar_grades (asdict).
- NEW frontend/src/components/sentcom/v5/ProvenanceRing.jsx (SVG, grade-colored
  arcs, missing pillars render gray, renders nothing when no grades).
- v5/ScannerCardsV5.jsx: import + map tqs_pillar_grades (+tqs_grade) into the
  setup / alert / position cards + render <ProvenanceRing/> left of the symbol.
- VERIFIED: yarn build clean (no new warnings); ring geometry/colors confirmed
  via isolated render; patcher applied to a fresh clone (on the A1 base) →
  byte-identical to the dev build; rollback restores tracked tree to HEAD.
- Delivered: scripts/patch_a2_provenance_ring.py (paste.rs/e3ahx). Apply: --apply
  then cd frontend && yarn build. Rollback: --rollback.

