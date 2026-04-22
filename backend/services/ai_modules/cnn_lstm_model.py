"""
CNN-LSTM — Temporal Chart Pattern Recognition
==============================================
Upgrade of the existing ResNet-18 CNN (chart_pattern_cnn.py) with an LSTM layer
that captures temporal evolution of chart patterns over a sequence of windows.

Architecture:
    ResNet-18 Backbone: Extracts spatial features from each chart window
    LSTM Layer: Processes sequence of chart features to capture pattern evolution
    Dual Heads:
        1. Direction Head → up / down / flat
        2. Win Probability Head → 0.0 - 1.0

Key Improvement Over CNN-Only:
    CNN sees: "This single chart window looks like a breakout"
    CNN-LSTM sees: "This breakout pattern has been building over 5 consecutive windows
                    with increasing volume — higher probability of follow-through"

Training: On Spark or PC GPU using pre-generated chart images from MongoDB bar data.
Prediction: Returns direction + win probability, replaces CNN in Confidence Gate Layer 8.
"""

import logging
import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SEQUENCE_LENGTH = 5  # Number of chart windows to look back
DIRECTIONS = ["down", "flat", "up"]  # Triple-barrier class order: -1/0/+1

# Triple-barrier hyperparameters (ATR multiples)
TB_PT_MULT = 2.0   # 2 × ATR profit target
TB_SL_MULT = 1.0   # 1 × ATR stop loss
TB_ATR_PERIOD = 14  # Lookback for ATR estimation


def _try_import_torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError:
        return None, None


class CNNLSTMModel:
    """
    CNN-LSTM for temporal chart pattern recognition.
    Uses ResNet-18 backbone + LSTM for temporal sequence awareness.
    """

    MODEL_NAME = "cnn_lstm_chart"
    COLLECTION = "dl_models"

    def __init__(self, db=None):
        self._db = db
        self._model = None
        self._device = None
        self._trained = False
        self._version = "v0.1.0"
        self._accuracy = 0.0
        self._win_rate = 0.0
        self._training_samples = 0

    def _build_model(self):
        """Build the CNN-LSTM PyTorch model."""
        torch, nn = _try_import_torch()
        if torch is None:
            raise ImportError("PyTorch not installed")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        class CNNLSTM(nn.Module):
            def __init__(self, cnn_feature_dim=512, lstm_hidden=128, n_layers=2, seq_len=SEQUENCE_LENGTH):
                super().__init__()

                # CNN Backbone — lightweight feature extractor from OHLCV sequences
                # Instead of full ResNet on images, we use a 1D CNN on bar features
                # This is more efficient and doesn't require chart image generation
                self.feature_dim = 46  # Same features as XGBoost for consistency
                self.cnn = nn.Sequential(
                    nn.Conv1d(1, 64, kernel_size=5, padding=2),
                    nn.BatchNorm1d(64),
                    nn.GELU(),
                    nn.Conv1d(64, 128, kernel_size=3, padding=1),
                    nn.BatchNorm1d(128),
                    nn.GELU(),
                    nn.AdaptiveAvgPool1d(16),
                    nn.Flatten(),
                    nn.Linear(128 * 16, cnn_feature_dim),
                    nn.GELU(),
                    nn.Dropout(0.2),
                )

                # LSTM processes sequence of CNN features
                self.lstm = nn.LSTM(
                    input_size=cnn_feature_dim,
                    hidden_size=lstm_hidden,
                    num_layers=n_layers,
                    batch_first=True,
                    dropout=0.2 if n_layers > 1 else 0,
                    bidirectional=False,
                )

                # Attention over LSTM outputs
                self.attention = nn.Sequential(
                    nn.Linear(lstm_hidden, 64),
                    nn.Tanh(),
                    nn.Linear(64, 1),
                )

                # Direction head
                self.direction_head = nn.Sequential(
                    nn.Linear(lstm_hidden, 64),
                    nn.GELU(),
                    nn.Dropout(0.2),
                    nn.Linear(64, 3),  # triple-barrier: down / flat / up
                )

                # Win probability head
                self.win_head = nn.Sequential(
                    nn.Linear(lstm_hidden, 64),
                    nn.GELU(),
                    nn.Linear(64, 1),
                    nn.Sigmoid(),
                )

            def forward(self, x):
                # x: (batch, seq_len, feature_dim)
                batch_size, seq_len, feat_dim = x.shape

                # Process each timestep through CNN
                cnn_features = []
                for t in range(seq_len):
                    # (batch, feature_dim) → (batch, 1, feature_dim) for Conv1d
                    xt = x[:, t, :].unsqueeze(1)
                    cnn_feat = self.cnn(xt)
                    cnn_features.append(cnn_feat)

                # Stack: (batch, seq_len, cnn_feature_dim)
                cnn_seq = torch.stack(cnn_features, dim=1)

                # LSTM
                lstm_out, (hidden, cell) = self.lstm(cnn_seq)
                # lstm_out: (batch, seq_len, lstm_hidden)

                # Attention
                attn_weights = self.attention(lstm_out)  # (batch, seq_len, 1)
                attn_weights = torch.softmax(attn_weights, dim=1)
                context = (lstm_out * attn_weights).sum(dim=1)  # (batch, lstm_hidden)

                direction = self.direction_head(context)
                win_prob = self.win_head(context)

                return direction, win_prob, attn_weights.squeeze(-1)

        self._model = CNNLSTM().to(self._device)
        n_params = sum(p.numel() for p in self._model.parameters())
        logger.info(f"CNN-LSTM model built on {self._device} ({n_params:,} params)")
        return self._model

    def extract_sequence_features(self, bars: List[Dict], lookback: int = 50,
                                   forecast_horizon: int = 5,
                                   return_intervals: bool = False) -> tuple:
        """
        Extract sequential feature windows for CNN-LSTM training.
        
        Creates overlapping sequences of feature windows where each sequence
        captures the evolution of technical indicators over SEQUENCE_LENGTH steps.
        
        Returns:
            (features, targets) when return_intervals=False (default — legacy)
            (features, targets, entry_indices, n_bars) when return_intervals=True
                entry_indices: np.ndarray (n_samples,) — entry bar in local `closes` axis
                n_bars:        int — total bars used for this symbol (needed by event_intervals)
        """
        if len(bars) < lookback + SEQUENCE_LENGTH + forecast_horizon:
            return (None, None, None, 0) if return_intervals else (None, None)

        closes = np.array([b["close"] for b in bars], dtype=np.float32)
        highs = np.array([b["high"] for b in bars], dtype=np.float32)
        lows = np.array([b["low"] for b in bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)

        n = len(closes)

        # Extract features for each bar position (simplified 46-feature set matching XGBoost)
        all_bar_features = []
        for i in range(lookback, n):
            feat = np.zeros(46, dtype=np.float32)
            window = closes[max(0, i - lookback):i + 1]

            # Price returns at various lookbacks
            for j, lb in enumerate([1, 2, 3, 5, 10, 20]):
                if i >= lb:
                    feat[j] = (closes[i] / closes[i - lb] - 1) * 100

            # Volatility
            ret_10 = np.diff(np.log(closes[max(0, i - 10):i + 1]))
            feat[6] = np.std(ret_10) * 100 if len(ret_10) > 1 else 0

            # RSI
            deltas = np.diff(window[-15:])
            gains = np.maximum(deltas, 0)
            losses = np.maximum(-deltas, 0)
            avg_g = np.mean(gains) if len(gains) > 0 else 0
            avg_l = np.mean(losses) if len(losses) > 0 else 0.001
            feat[7] = 100 - (100 / (1 + avg_g / avg_l)) if avg_l > 0 else 50

            # SMA distances
            for j, period in enumerate([5, 10, 20, 50]):
                sma = np.mean(closes[max(0, i - period):i + 1])
                feat[8 + j] = (closes[i] / sma - 1) * 100

            # Volume ratio
            vol5 = np.mean(volumes[max(0, i - 5):i + 1])
            vol20 = np.mean(volumes[max(0, i - 20):i + 1])
            feat[12] = vol5 / vol20 if vol20 > 0 else 1.0

            # High-low range
            feat[13] = (highs[i] - lows[i]) / closes[i] * 100

            # Fill remaining features with derived indicators
            feat[14] = (closes[i] - lows[i]) / (highs[i] - lows[i]) if (highs[i] - lows[i]) > 0 else 0.5
            feat[15] = closes[i] - np.mean(closes[max(0, i - 20):i + 1])  # distance from SMA20

            all_bar_features.append(feat)

        all_bar_features = np.array(all_bar_features, dtype=np.float32)

        # Create sequences with triple-barrier labels
        from services.ai_modules.triple_barrier_labeler import (
            triple_barrier_label_single, atr as _atr, label_to_class_index
        )

        atr_series = _atr(highs, lows, closes, period=TB_ATR_PERIOD)

        sequences = []
        targets = []
        entry_indices: List[int] = []
        n_feats = len(all_bar_features)

        for i in range(SEQUENCE_LENGTH, n_feats - forecast_horizon):
            seq = all_bar_features[i - SEQUENCE_LENGTH:i]

            # Target: triple-barrier label from entry at current bar.
            # Horizon for max_bars uses forecast_horizon so callers control it.
            current_close_idx = lookback + i
            if current_close_idx >= len(atr_series):
                continue
            atr_val = atr_series[current_close_idx]
            if not np.isfinite(atr_val) or atr_val <= 0:
                continue

            tb_label = triple_barrier_label_single(
                highs, lows, closes,
                entry_idx=current_close_idx,
                pt_atr_mult=TB_PT_MULT,
                sl_atr_mult=TB_SL_MULT,
                max_bars=forecast_horizon,
                atr_value=float(atr_val),
            )
            sequences.append(seq)
            targets.append(label_to_class_index(tb_label))  # -1/0/+1 → 0/1/2
            entry_indices.append(int(current_close_idx))

        if not sequences:
            return (None, None, None, 0) if return_intervals else (None, None)

        seq_arr = np.array(sequences, dtype=np.float32)
        tgt_arr = np.array(targets, dtype=np.int64)

        if return_intervals:
            return seq_arr, tgt_arr, np.array(entry_indices, dtype=np.int64), int(n)
        return seq_arr, tgt_arr

    async def train(self, db=None, max_symbols: int = 200, epochs: int = 30, batch_size: int = 256) -> Dict[str, Any]:
        """Train CNN-LSTM on sequential bar data from MongoDB."""
        torch, nn = _try_import_torch()
        if torch is None:
            return {"success": False, "error": "PyTorch not installed"}

        db = db if db is not None else self._db
        if db is not None:
            self._db = db
        if db is None:
            return {"success": False, "error": "No database connection"}

        logger.info("[CNN-LSTM] Starting training...")

        # Get symbols with enough daily data
        pipeline = [
            {"$match": {"bar_size": "1 day"}},
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gte": 200}}},
            {"$sort": {"count": -1}},
            {"$limit": max_symbols},
        ]
        symbols = [r["_id"] for r in db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True)]
        logger.info(f"[CNN-LSTM] Found {len(symbols)} symbols")

        all_sequences = []
        all_targets = []
        # Phase-1-for-DL: per-symbol event intervals (López de Prado uniqueness
        # + purged split). Kept per-symbol because concurrency counts only make
        # sense on a single symbol's bar axis. Concat later with a global offset.
        per_symbol_intervals: List[np.ndarray] = []
        per_symbol_n_bars: List[int] = []
        global_intervals_chunks: List[np.ndarray] = []
        _cumulative_bar_offset = 0
        symbols_used = 0

        # Lazy import here (keeps top-of-file imports minimal)
        from services.ai_modules.event_intervals import (
            build_event_intervals_from_triple_barrier,
        )

        for sym_idx, symbol in enumerate(symbols):
            if sym_idx % 50 == 0:
                logger.info(f"[CNN-LSTM] Processing {sym_idx + 1}/{len(symbols)}: {symbol}")

            cursor = db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": "1 day"},
                {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
            ).sort("date", -1).limit(5000).max_time_ms(60000)
            bars = list(cursor)
            bars.reverse()  # Back to chronological order

            if len(bars) < 100:
                continue

            seqs, tgts, entry_idxs, n_bars_sym = self.extract_sequence_features(
                bars, return_intervals=True,
            )
            if seqs is not None and len(seqs) > 10:
                # Build event intervals in that symbol's local `closes` axis
                highs_arr = np.array([b["high"] for b in bars], dtype=np.float64)
                lows_arr = np.array([b["low"] for b in bars], dtype=np.float64)
                closes_arr = np.array([b["close"] for b in bars], dtype=np.float64)
                local_intervals = build_event_intervals_from_triple_barrier(
                    highs_arr, lows_arr, closes_arr,
                    entry_indices=entry_idxs,
                    pt_atr_mult=TB_PT_MULT, sl_atr_mult=TB_SL_MULT,
                    max_bars=5, atr_period=TB_ATR_PERIOD,
                )
                per_symbol_intervals.append(local_intervals)
                per_symbol_n_bars.append(int(n_bars_sym))
                if len(local_intervals) > 0:
                    global_intervals_chunks.append(local_intervals + _cumulative_bar_offset)
                _cumulative_bar_offset += int(n_bars_sym) + 1000  # buffer > embargo

                all_sequences.append(seqs)
                all_targets.append(tgts)
                symbols_used += 1

        if not all_sequences:
            return {"success": False, "error": "No training data extracted"}

        X = np.vstack(all_sequences)
        y = np.concatenate(all_targets)

        logger.info(f"[CNN-LSTM] Training data: {X.shape[0]:,} sequences from {symbols_used} symbols")
        logger.info(f"[CNN-LSTM] Sequence shape: {X.shape} (samples, seq_len={SEQUENCE_LENGTH}, features=46)")

        # Class balance diagnostic — detects majority-class collapse.
        # With triple-barrier targets, there are 3 classes: 0=down (SL hit),
        # 1=flat (time exit), 2=up (PT hit). Healthy distribution has all three
        # classes with flat often dominating (30-60%). If any single class
        # exceeds ~55%, the model will likely collapse onto it.
        class_counts = np.bincount(y, minlength=3)
        majority_pct = class_counts.max() / len(y) if len(y) > 0 else 0.5
        logger.info(
            f"[CNN-LSTM] Class balance (triple-barrier): "
            f"down={class_counts[0]}, flat={class_counts[1]}, up={class_counts[2]}, "
            f"majority={majority_pct:.3%} (always-predict-majority baseline)"
        )
        if majority_pct > 0.55:
            logger.warning(
                f"[CNN-LSTM] Heavy class imbalance ({majority_pct:.1%}) — consider tightening "
                f"PT/SL multiples (current: PT={TB_PT_MULT}x ATR, SL={TB_SL_MULT}x ATR, "
                f"horizon={X.shape[0] // max(symbols_used,1)} samples/symbol)"
            )

        # Normalize features
        X_flat = X.reshape(-1, X.shape[-1])
        self._scaler_mean = X_flat.mean(axis=0).astype(np.float32)
        self._scaler_std = (X_flat.std(axis=0) + 1e-8).astype(np.float32)
        X_norm = (X - self._scaler_mean) / self._scaler_std

        # ── Phase-1-for-DL helpers: class weights + sample uniqueness + purged split ──
        from services.ai_modules.dl_training_utils import (
            compute_balanced_class_weights,
            compute_sample_weights_from_intervals,
            purged_chronological_split,
            dl_cpcv_folds_from_env,
            run_cpcv_accuracy_stability,
            build_dl_scorecard,
            get_class_weight_scheme,
        )

        class_w_np = compute_balanced_class_weights(
            y, num_classes=3, clip_ratio=5.0, scheme=get_class_weight_scheme(),
        )
        sample_w_np = compute_sample_weights_from_intervals(
            per_symbol_intervals, per_symbol_n_bars,
        )
        if len(sample_w_np) != len(y):
            sample_w_np = np.ones(len(y), dtype=np.float32)
        global_intervals = (
            np.vstack(global_intervals_chunks).astype(np.int64)
            if global_intervals_chunks else None
        )
        if global_intervals is not None and len(global_intervals) != len(y):
            global_intervals = None

        train_idx, val_idx = purged_chronological_split(
            intervals=global_intervals,
            n_samples=len(y),
            split_frac=0.8,
            embargo_bars=5,
        )
        if len(train_idx) == 0 or len(val_idx) == 0:
            split_idx = int(len(X_norm) * 0.8)
            train_idx = np.arange(split_idx, dtype=np.int64)
            val_idx = np.arange(split_idx, len(X_norm), dtype=np.int64)
        logger.info(
            f"[CNN-LSTM] Purged split: train={len(train_idx)} val={len(val_idx)} "
            f"class_weights={class_w_np.tolist()} sample_w_mean={float(sample_w_np.mean()):.3f}"
        )

        X_train, X_val = X_norm[train_idx], X_norm[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        sample_w_train = sample_w_np[train_idx]

        self._build_model()

        X_train_t = torch.tensor(X_train, dtype=torch.float32, device=self._device)
        y_train_t = torch.tensor(y_train, dtype=torch.long, device=self._device)
        X_val_t = torch.tensor(X_val, dtype=torch.float32, device=self._device)
        y_val_t = torch.tensor(y_val, dtype=torch.long, device=self._device)
        sample_w_train_t = torch.tensor(sample_w_train, dtype=torch.float32, device=self._device)
        class_weights_t = torch.tensor(class_w_np, dtype=torch.float32, device=self._device)

        optimizer = torch.optim.AdamW(self._model.parameters(), lr=5e-4, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        # Class-weighted CE with per-sample uniqueness. Auxiliary win-prob head
        # is kept unweighted for class (it's a binary classifier) but still gets
        # sample-weight scaling.
        criterion = nn.CrossEntropyLoss(weight=class_weights_t, reduction='none')

        best_val_acc = 0
        best_state = None

        for epoch in range(epochs):
            self._model.train()
            perm = torch.randperm(len(X_train_t))
            total_loss = 0
            n_batches = 0

            for i in range(0, len(X_train_t), batch_size):
                batch_idx = perm[i:i + batch_size]
                batch_x = X_train_t[batch_idx]
                batch_y = y_train_t[batch_idx]
                batch_sw = sample_w_train_t[batch_idx]

                direction, win_prob, attn = self._model(batch_x)
                per_sample_loss = criterion(direction, batch_y)
                loss = (per_sample_loss * batch_sw).mean()

                # Add win probability auxiliary loss.
                # Triple-barrier class 2 = "up" = profit target hit = win.
                # Class 1 = flat (time exit) and 0 = down (stop hit) are not wins.
                win_target = (batch_y == 2).float().unsqueeze(-1)
                aux_per_sample = nn.functional.binary_cross_entropy(
                    win_prob, win_target, reduction='none'
                ).squeeze(-1)
                loss = loss + 0.3 * (aux_per_sample * batch_sw).mean()

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
                optimizer.step()

                total_loss += loss.item()
                n_batches += 1

            scheduler.step()

            # Validate
            self._model.eval()
            with torch.no_grad():
                val_dir, _val_win, _ = self._model(X_val_t)
                val_pred = torch.argmax(val_dir, dim=-1)
                val_acc = (val_pred == y_val_t).float().mean().item()

            if epoch % 5 == 0:
                logger.info(f"[CNN-LSTM] Epoch {epoch}/{epochs} — loss: {total_loss / n_batches:.4f}, val_acc: {val_acc:.4f}")

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_state = {k: v.clone() for k, v in self._model.state_dict().items()}

        if best_state:
            self._model.load_state_dict(best_state)

        self._trained = True
        self._accuracy = best_val_acc
        self._training_samples = len(X)
        self._version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        self._save_model()

        # ── Optional CPCV stability pass (opt-in via TB_DL_CPCV_FOLDS env) ──
        cpcv_stab: Dict[str, float] = {
            "mean": 0.0, "std": 0.0, "negative_pct": 0.0, "n": 0, "scores": [],
        }
        cpcv_n = dl_cpcv_folds_from_env()
        if cpcv_n >= 3 and global_intervals is not None:
            logger.info(f"[CNN-LSTM] Running CPCV stability with n_splits={cpcv_n}")
            cpcv_epochs = max(3, epochs // 5)

            def _lightweight_train_eval(tr_idx: np.ndarray, te_idx: np.ndarray) -> float:
                self._build_model()
                opt2 = torch.optim.AdamW(self._model.parameters(), lr=5e-4, weight_decay=1e-4)
                crit2 = nn.CrossEntropyLoss(weight=class_weights_t, reduction='none')
                Xt = torch.tensor(X_norm[tr_idx], dtype=torch.float32, device=self._device)
                yt = torch.tensor(y[tr_idx], dtype=torch.long, device=self._device)
                swt = torch.tensor(sample_w_np[tr_idx], dtype=torch.float32, device=self._device)
                Xv = torch.tensor(X_norm[te_idx], dtype=torch.float32, device=self._device)
                yv = torch.tensor(y[te_idx], dtype=torch.long, device=self._device)
                for _ in range(cpcv_epochs):
                    self._model.train()
                    p = torch.randperm(len(Xt))
                    for j in range(0, len(Xt), batch_size):
                        bi = p[j:j + batch_size]
                        d, _w, _a = self._model(Xt[bi])
                        lo = (crit2(d, yt[bi]) * swt[bi]).mean()
                        opt2.zero_grad()
                        lo.backward()
                        opt2.step()
                self._model.eval()
                with torch.no_grad():
                    vd, _, _ = self._model(Xv)
                    pred = torch.argmax(vd, dim=-1)
                    return float((pred == yv).float().mean().item())

            try:
                cpcv_stab = run_cpcv_accuracy_stability(
                    _lightweight_train_eval,
                    intervals=global_intervals,
                    n_samples=len(y),
                    n_splits=cpcv_n,
                    n_test_splits=max(1, cpcv_n // 3),
                    embargo_bars=5,
                )
                logger.info(
                    f"[CNN-LSTM] CPCV stability: mean={cpcv_stab['mean']:.4f} "
                    f"std={cpcv_stab['std']:.4f} n={cpcv_stab['n']}"
                )
            except Exception as e:
                logger.warning(f"[CNN-LSTM] CPCV run failed (non-fatal): {e}")
            finally:
                if best_state:
                    self._build_model()
                    self._model.load_state_dict(best_state)

        class_counts_dict = {
            "down": int(class_counts[0]),
            "flat": int(class_counts[1]),
            "up": int(class_counts[2]),
        }
        scorecard = build_dl_scorecard(
            model_name=self.MODEL_NAME,
            version=self._version,
            num_samples=len(X),
            best_val_acc=float(best_val_acc),
            majority_baseline=float(majority_pct),
            class_counts=class_counts_dict,
            cpcv_stability=cpcv_stab,
            bar_size="1 day",
            trade_side="both",
            setup_type="GENERAL",
        )
        try:
            if self._db is not None:
                self._db[self.COLLECTION].update_one(
                    {"name": self.MODEL_NAME},
                    {"$set": {"scorecard": scorecard}},
                )
        except Exception as e:
            logger.warning(f"[CNN-LSTM] Failed to persist scorecard (non-fatal): {e}")

        # Edge above majority-class baseline — detects "always predict up" collapse.
        edge_vs_baseline = best_val_acc - majority_pct
        if edge_vs_baseline <= 0.01:
            logger.warning(
                f"[CNN-LSTM] ⚠️  val_acc={best_val_acc:.4f} is at/below majority baseline "
                f"({majority_pct:.4f}). Model likely collapsed to always predicting majority class — "
                f"DO NOT PROMOTE."
            )
        else:
            logger.info(
                f"[CNN-LSTM] val_acc={best_val_acc:.4f}, majority_baseline={majority_pct:.4f}, "
                f"edge_above_baseline={edge_vs_baseline:+.4f}"
            )

        return {
            "success": True,
            "model": self.MODEL_NAME,
            "version": self._version,
            "accuracy": best_val_acc,
            "majority_baseline": float(majority_pct),
            "edge_above_baseline": float(edge_vs_baseline),
            "class_counts": {
                "down": int(class_counts[0]),
                "flat": int(class_counts[1]),
                "up": int(class_counts[2]),
            },
            "training_samples": len(X),
            "symbols_used": symbols_used,
            "device": str(self._device),
            "label_scheme": "triple_barrier_atr",
            "label_params": {
                "pt_atr_mult": TB_PT_MULT,
                "sl_atr_mult": TB_SL_MULT,
                "atr_period": TB_ATR_PERIOD,
            },
            "class_weights": class_w_np.tolist(),
            "sample_weight_mean": float(sample_w_np.mean()) if len(sample_w_np) else 1.0,
            "purged_split": {
                "embargo_bars": 5,
                "train_samples": int(len(train_idx)),
                "val_samples": int(len(val_idx)),
            },
            "cpcv_stability": cpcv_stab,
            "scorecard": scorecard,
        }

    def predict(self, bars: List[Dict], symbol: str = "UNKNOWN") -> Dict[str, Any]:
        """
        Predict direction and win probability from recent bar data.
        
        Args:
            bars: Recent bars (need at least 50 + SEQUENCE_LENGTH)
            symbol: Stock symbol for logging
        """
        torch, _ = _try_import_torch()
        if torch is None or not self._trained or self._model is None:
            return {"has_prediction": False, "direction": "flat", "win_probability": 0.5, "confidence": 0.0}

        seqs, _ = self.extract_sequence_features(bars, forecast_horizon=0)
        if seqs is None or len(seqs) == 0:
            return {"has_prediction": False, "direction": "flat", "win_probability": 0.5, "confidence": 0.0}

        # Use the most recent sequence
        latest = seqs[-1:]
        latest_norm = (latest - self._scaler_mean) / self._scaler_std

        self._model.eval()
        with torch.no_grad():
            x = torch.tensor(latest_norm, dtype=torch.float32, device=self._device)
            direction_logits, win_prob, attn_weights = self._model(x)

            probs = torch.softmax(direction_logits, dim=-1).cpu().numpy()[0]
            win_p = win_prob.cpu().item()
            attn = attn_weights.cpu().numpy()[0]

        pred_class = int(np.argmax(probs))
        direction = DIRECTIONS[pred_class] if pred_class < len(DIRECTIONS) else "flat"

        return {
            "has_prediction": True,
            "direction": direction,
            "win_probability": win_p,
            "confidence": float(max(probs)),
            "pattern_confidence": float(max(probs)),
            "pattern": f"cnn_lstm_{direction}",
            "temporal_attention": {f"t-{SEQUENCE_LENGTH - i}": float(a) for i, a in enumerate(attn)},
            "model": self.MODEL_NAME,
            "model_accuracy": self._accuracy,
        }

    def _save_model(self):
        """Save model to MongoDB."""
        torch, _ = _try_import_torch()
        if torch is None or self._model is None or self._db is None:
            return False

        try:
            import base64
            import io

            buffer = io.BytesIO()
            torch.save({
                "model_state_dict": self._model.state_dict(),
                "scaler_mean": self._scaler_mean.tolist() if self._scaler_mean is not None else [],
                "scaler_std": self._scaler_std.tolist() if self._scaler_std is not None else [],
                "version": self._version,
                "accuracy": self._accuracy,
                "training_samples": self._training_samples,
            }, buffer)
            model_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            self._db[self.COLLECTION].update_one(
                {"name": self.MODEL_NAME},
                {"$set": {
                    "name": self.MODEL_NAME,
                    "model_data": model_b64,
                    "model_type": "cnn_lstm",
                    "version": self._version,
                    "accuracy": self._accuracy,
                    "training_samples": self._training_samples,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True
            )
            logger.info(f"[CNN-LSTM] Saved model {self._version} (acc={self._accuracy:.4f})")
            return True
        except Exception as e:
            logger.error(f"[CNN-LSTM] Failed to save model: {e}")
            return False

    def load_model(self, db=None):
        """Load model from MongoDB."""
        torch, _ = _try_import_torch()
        if torch is None:
            return False

        db = db if db is not None else self._db
        if db is None:
            return False

        try:
            doc = db[self.COLLECTION].find_one({"name": self.MODEL_NAME}, {"_id": 0})
            if not doc or "model_data" not in doc:
                return False

            import base64
            import io

            model_bytes = base64.b64decode(doc["model_data"])
            self._build_model()
            checkpoint = torch.load(io.BytesIO(model_bytes), map_location=self._device, weights_only=False)

            self._model.load_state_dict(checkpoint["model_state_dict"])
            self._scaler_mean = np.array(checkpoint.get("scaler_mean", []), dtype=np.float32)
            self._scaler_std = np.array(checkpoint.get("scaler_std", [1]), dtype=np.float32)
            self._version = checkpoint.get("version", "v0.0.0")
            self._accuracy = checkpoint.get("accuracy", 0.0)
            self._training_samples = checkpoint.get("training_samples", 0)
            self._trained = True
            self._model.eval()

            logger.info(f"[CNN-LSTM] Loaded model {self._version} (acc={self._accuracy:.4f})")
            return True
        except Exception as e:
            logger.error(f"[CNN-LSTM] Failed to load model: {e}")
            return False
