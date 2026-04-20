#!/bin/bash
# ============================================================
#  ONE-SHOT PATCH: Fix CNN phase expected_models for CURRENT run
#  Safe to run while training is in flight — it only updates
#  the Mongo training_pipeline_status doc, no service restart.
#
#  Also backfills models_trained from completed_models so the
#  counter reflects reality.
# ============================================================

MONGO_CONTAINER="${MONGO_CONTAINER:-mongodb}"
DB_NAME="${DB_NAME:-tradecommand}"

sudo docker exec "$MONGO_CONTAINER" mongosh --quiet "$DB_NAME" --eval "
  let s = db.training_pipeline_status.findOne({_id:'pipeline'});
  if (!s) { print('No pipeline status doc found.'); quit(); }

  // 1) Fix CNN expected_models (13 -> 34)
  let cnn = (s.phase_history || {}).cnn_patterns;
  if (cnn) {
    let cnnModels = (s.completed_models || []).filter(m => (m.name||'').startsWith('cnn_'));
    let cnnDone = cnnModels.length;
    let totalAcc = cnnModels.reduce((a,m) => a + (m.accuracy||0), 0);
    db.training_pipeline_status.updateOne(
      {_id:'pipeline'},
      {\$set: {
        'phase_history.cnn_patterns.expected_models': 34,
        'phase_history.cnn_patterns.models_trained': cnnDone,
        'phase_history.cnn_patterns.total_accuracy': totalAcc,
        'phase_history.cnn_patterns.avg_accuracy': cnnDone > 0 ? (totalAcc/cnnDone) : 0,
      }}
    );
    print('Patched cnn_patterns: expected_models=34, models_trained=' + cnnDone);
  } else {
    print('cnn_patterns phase not found in phase_history (not started yet?).');
  }

  // 2) Fix models_total (129 -> 150) so overall ETA is accurate
  db.training_pipeline_status.updateOne(
    {_id:'pipeline'},
    {\$set: {models_total: 150}}
  );
  print('Patched models_total=150');
"
