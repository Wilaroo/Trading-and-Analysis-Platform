import React from "react";

/**
 * Model Scorecard — the "bundle judge" display.
 *
 * Shows the 15 key metrics + composite grade (A-F) for a single trained model.
 * Color-coded against published López de Prado thresholds so a glance tells you
 * whether the model is tradeable, borderline, or failing.
 *
 * Props:
 *   scorecard: object from /api/ai-training/scorecard/:model_name
 *   onClose?:  optional close handler when embedded in a modal/expander
 */

const GRADE_COLORS = {
  A: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5",
  B: "text-sky-400 border-sky-500/40 bg-sky-500/5",
  C: "text-amber-400 border-amber-500/40 bg-amber-500/5",
  D: "text-orange-400 border-orange-500/40 bg-orange-500/5",
  F: "text-rose-400 border-rose-500/40 bg-rose-500/5",
};

function Metric({ label, value, suffix = "", threshold = null, invert = false, testid }) {
  let color = "text-zinc-300";
  if (threshold && typeof value === "number" && Number.isFinite(value)) {
    const [bad, mid, good] = threshold;
    const ok = invert ? value <= good : value >= good;
    const warn = invert ? value <= mid : value >= mid;
    const fail = invert ? value > bad : value < bad;
    if (ok) color = "text-emerald-400";
    else if (warn) color = "text-amber-400";
    else if (fail) color = "text-rose-400";
  }
  const formatted =
    typeof value === "number" && Number.isFinite(value)
      ? value.toFixed(value < 10 && Math.abs(value) > 0 ? 2 : 1)
      : "—";
  return (
    <div className="flex justify-between text-[11px] py-0.5" data-testid={testid}>
      <span className="text-zinc-500">{label}</span>
      <span className={color}>
        {formatted}
        {suffix}
      </span>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 border-b border-zinc-800/40 pb-0.5">
        {title}
      </div>
      {children}
    </div>
  );
}

export default function ModelScorecard({ scorecard, onClose }) {
  if (!scorecard || Object.keys(scorecard).length === 0) {
    return (
      <div className="text-xs text-zinc-500 p-3 italic" data-testid="scorecard-empty">
        No scorecard yet — model has not been validated.
      </div>
    );
  }

  const g = scorecard.composite_grade || "F";
  const gradeStyle = GRADE_COLORS[g] || GRADE_COLORS.F;
  const redLines = scorecard.red_line_failures || [];

  return (
    <div
      className="bg-zinc-950/80 border border-zinc-800/60 rounded-lg p-3 text-zinc-300 backdrop-blur-sm"
      data-testid="model-scorecard"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-2 pb-2 border-b border-zinc-800/60">
        <div>
          <div className="text-sm font-medium">
            {scorecard.setup_type} / {scorecard.bar_size}
            <span className="text-zinc-600 ml-1 text-[10px]">
              ({scorecard.trade_side || "long"})
            </span>
          </div>
          <div className="text-[10px] text-zinc-500">
            {scorecard.model_name}{" "}
            {scorecard.version && <span>· {scorecard.version}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`text-center px-2 py-1 rounded border ${gradeStyle}`}
            data-testid="scorecard-grade"
          >
            <div className="text-xs font-medium">Grade</div>
            <div className="text-lg leading-none font-bold">{g}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-zinc-500">Composite</div>
            <div className="text-sm font-bold text-zinc-200" data-testid="scorecard-score">
              {(scorecard.composite_score || 0).toFixed(0)}
              <span className="text-zinc-600 text-[10px]">/100</span>
            </div>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="text-zinc-500 hover:text-zinc-300 text-xs ml-1"
              data-testid="scorecard-close"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Red lines banner */}
      {redLines.length > 0 && (
        <div
          className="mb-2 text-[10px] text-rose-400 bg-rose-500/5 border border-rose-500/20 rounded px-2 py-1"
          data-testid="scorecard-redlines"
        >
          ⚠ Red-line failures: {redLines.join(", ")}
        </div>
      )}

      {/* Metrics grid */}
      <div className="grid grid-cols-3 gap-3">
        <Section title="Risk-Adjusted">
          <Metric
            label="Sharpe"
            value={scorecard.sharpe}
            threshold={[0.5, 1.0, 1.5]}
            testid="metric-sharpe"
          />
          <Metric
            label="Sortino"
            value={scorecard.sortino}
            threshold={[0.5, 1.5, 2.5]}
            testid="metric-sortino"
          />
          <Metric
            label="Calmar"
            value={scorecard.calmar}
            threshold={[0.5, 1.0, 2.0]}
            testid="metric-calmar"
          />
          <Metric
            label="DSR"
            value={scorecard.deflated_sharpe}
            threshold={[0.5, 1.0, 1.5]}
            testid="metric-dsr"
          />
          <Metric
            label="DSR p"
            value={scorecard.dsr_p_value}
            threshold={[0.5, 0.9, 0.95]}
            testid="metric-dsr-p"
          />
        </Section>

        <Section title="Returns & Risk">
          <Metric
            label="Return"
            value={scorecard.total_return_pct}
            suffix="%"
            threshold={[0, 10, 25]}
            testid="metric-total-return"
          />
          <Metric
            label="Hit rate"
            value={(scorecard.hit_rate || 0) * 100}
            suffix="%"
            threshold={[45, 52, 58]}
            testid="metric-hit-rate"
          />
          <Metric
            label="PF"
            value={scorecard.profit_factor}
            threshold={[1.0, 1.4, 2.0]}
            testid="metric-pf"
          />
          <Metric
            label="Max DD"
            value={scorecard.max_drawdown_pct}
            suffix="%"
            threshold={[50, 25, 10]}
            invert
            testid="metric-max-dd"
          />
          <Metric
            label="P(ruin)"
            value={(scorecard.prob_of_ruin || 0) * 100}
            suffix="%"
            threshold={[20, 10, 2]}
            invert
            testid="metric-ruin"
          />
        </Section>

        <Section title="Robustness & Edge">
          <Metric
            label="Walk-fwd"
            value={(scorecard.walk_forward_efficiency || 0) * 100}
            suffix="%"
            threshold={[50, 80, 95]}
            testid="metric-wf"
          />
          <Metric
            label="OOS Sharpe"
            value={scorecard.oos_sharpe}
            threshold={[0.3, 0.8, 1.3]}
            testid="metric-oos"
          />
          <Metric
            label="Edge"
            value={scorecard.ai_vs_setup_edge_pp}
            suffix="pp"
            threshold={[0, 5, 10]}
            testid="metric-edge"
          />
          <Metric label="Trades" value={scorecard.num_trades} testid="metric-trades" />
          <Metric
            label="Trials"
            value={scorecard.num_trials}
            testid="metric-trials"
          />
        </Section>
      </div>

      {/* Footer */}
      {scorecard.validated_at && (
        <div className="mt-2 pt-1 border-t border-zinc-800/40 text-[9px] text-zinc-600 flex justify-between">
          <span>Validated {new Date(scorecard.validated_at).toLocaleString()}</span>
          {scorecard.is_statistically_significant ? (
            <span className="text-emerald-500/70">✓ Statistically significant</span>
          ) : (
            <span className="text-amber-500/70">⚠ Not yet statistically significant</span>
          )}
        </div>
      )}
    </div>
  );
}
