"""
Temporal Fusion Transformer (TFT) — Multi-Timeframe Attention Model
====================================================================
A simplified TFT implementation that learns which timeframes matter most
for each symbol and market regime.

Architecture:
    Input: Features from multiple timeframes (1min, 5min, 15min, 1hour, 1day)
    Variable Selection Network: Learns feature importance per timeframe
    Temporal Self-Attention: Attends across timeframes
    Output: (direction, confidence, uncertainty)

Key Insight: Instead of treating each timeframe independently (like XGBoost does),
TFT learns cross-timeframe patterns. E.g., "daily trend up + 15min pullback to VWAP"
= high probability continuation.

Training: On Spark GPU using multi-timeframe bar data from MongoDB.
Prediction: Returns direction + confidence, used as additive voter in Confidence Gate.
"""

import logging
import numpy as np
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Timeframes used by TFT (ordered from fastest to slowest)
TFT_TIMEFRAMES = ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]
FEATURES_PER_TF = 12  # Features extracted per timeframe
TOTAL_INPUT_DIM = len(TFT_TIMEFRAMES) * FEATURES_PER_TF  # 60


def _try_import_torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError:
        return None, None


class TFTModel:
    """
    Wrapper for the Temporal Fusion Transformer.
    Handles training, prediction, and MongoDB persistence.
    """

    MODEL_NAME = "tft_multi_timeframe"
    COLLECTION = "dl_models"

    def __init__(self, db=None):
        self._db = db
        self._model = None
        self._device = None
        self._scaler_mean = None
        self._scaler_std = None
        self._trained = False
        self._version = "v0.1.0"
        self._accuracy = 0.0
        self._training_samples = 0

    def _build_model(self):
        """Build the TFT PyTorch model."""
        torch, nn = _try_import_torch()
        if torch is None:
            raise ImportError("PyTorch not installed")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        class VariableSelectionNetwork(nn.Module):
            """Learns which features within each timeframe are most important."""
            def __init__(self, input_dim, hidden_dim, n_vars):
                super().__init__()
                self.flattened_grn = nn.Sequential(
                    nn.Linear(input_dim, hidden_dim),
                    nn.GELU(),
                    nn.Linear(hidden_dim, n_vars),
                    nn.Softmax(dim=-1),
                )
                self.per_var_grns = nn.ModuleList([
                    nn.Sequential(
                        nn.Linear(input_dim // n_vars, hidden_dim),
                        nn.GELU(),
                        nn.Linear(hidden_dim, hidden_dim),
                    )
                    for _ in range(n_vars)
                ])
                self.n_vars = n_vars
                self.var_dim = input_dim // n_vars

            def forward(self, x):
                # x: (batch, input_dim)
                weights = self.flattened_grn(x)  # (batch, n_vars)
                var_outputs = []
                for i in range(self.n_vars):
                    var_input = x[:, i * self.var_dim:(i + 1) * self.var_dim]
                    var_outputs.append(self.per_var_grns[i](var_input))
                # Stack: (batch, n_vars, hidden_dim)
                var_stack = torch.stack(var_outputs, dim=1)
                # Weight and sum: (batch, hidden_dim)
                weighted = (var_stack * weights.unsqueeze(-1)).sum(dim=1)
                return weighted, weights

        class TemporalSelfAttention(nn.Module):
            """Multi-head attention across timeframe representations."""
            def __init__(self, d_model, n_heads=4):
                super().__init__()
                self.attention = nn.MultiheadAttention(d_model, n_heads, batch_first=True, dropout=0.1)
                self.norm = nn.LayerNorm(d_model)

            def forward(self, x):
                # x: (batch, n_timeframes, d_model)
                attn_out, attn_weights = self.attention(x, x, x)
                return self.norm(x + attn_out), attn_weights

        class TFT(nn.Module):
            def __init__(self, n_timeframes=5, features_per_tf=12, hidden_dim=64, n_heads=4):
                super().__init__()
                self.n_timeframes = n_timeframes
                self.features_per_tf = features_per_tf
                total_input = n_timeframes * features_per_tf

                # Variable selection: learns which features matter
                self.vsn = VariableSelectionNetwork(total_input, hidden_dim, n_timeframes)

                # Per-timeframe encoders
                self.tf_encoders = nn.ModuleList([
                    nn.Sequential(
                        nn.Linear(features_per_tf, hidden_dim),
                        nn.LayerNorm(hidden_dim),
                        nn.GELU(),
                    )
                    for _ in range(n_timeframes)
                ])

                # Temporal attention across timeframes
                self.temporal_attention = TemporalSelfAttention(hidden_dim, n_heads)

                # Output heads
                self.direction_head = nn.Sequential(
                    nn.Linear(hidden_dim * n_timeframes, hidden_dim),
                    nn.GELU(),
                    nn.Dropout(0.2),
                    nn.Linear(hidden_dim, 3),  # up, down, flat
                )

                self.confidence_head = nn.Sequential(
                    nn.Linear(hidden_dim * n_timeframes, hidden_dim),
                    nn.GELU(),
                    nn.Linear(hidden_dim, 1),
                    nn.Sigmoid(),
                )

            def forward(self, x):
                batch_size = x.size(0)

                # Variable selection
                vsn_out, tf_weights = self.vsn(x)

                # Encode each timeframe separately
                tf_encoded = []
                for i in range(self.n_timeframes):
                    tf_input = x[:, i * self.features_per_tf:(i + 1) * self.features_per_tf]
                    tf_encoded.append(self.tf_encoders[i](tf_input))

                # Stack timeframe encodings: (batch, n_timeframes, hidden_dim)
                tf_stack = torch.stack(tf_encoded, dim=1)

                # Apply temporal attention
                attended, attn_weights = self.temporal_attention(tf_stack)

                # Flatten for output heads
                flat = attended.reshape(batch_size, -1)

                direction = self.direction_head(flat)
                confidence = self.confidence_head(flat)

                return direction, confidence, tf_weights, attn_weights

        self._model = TFT().to(self._device)
        n_params = sum(p.numel() for p in self._model.parameters())
        logger.info(f"TFT model built on {self._device} ({n_params:,} params)")
        return self._model

    def extract_multi_tf_features(self, symbol: str, bars_by_tf: Dict[str, List[Dict]]) -> Optional[np.ndarray]:
        """
        Extract features for a single symbol across multiple timeframes.
        
        Args:
            symbol: Stock symbol
            bars_by_tf: Dict mapping timeframe to list of bars for this symbol
            
        Returns:
            np.ndarray of shape (n_samples, TOTAL_INPUT_DIM) or None
        """
        # Need at least 1 day and one intraday timeframe
        if "1 day" not in bars_by_tf or len(bars_by_tf["1 day"]) < 30:
            return None

        # Extract per-timeframe features (12 per TF)
        tf_features = {}
        min_samples = float("inf")

        for tf in TFT_TIMEFRAMES:
            bars = bars_by_tf.get(tf, [])
            if len(bars) < 20:
                # Pad with zeros if timeframe not available
                tf_features[tf] = None
                continue

            closes = np.array([b["close"] for b in bars], dtype=np.float32)
            highs = np.array([b["high"] for b in bars], dtype=np.float32)
            lows = np.array([b["low"] for b in bars], dtype=np.float32)
            volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)

            n = len(closes)
            feats = np.zeros((n - 20, FEATURES_PER_TF), dtype=np.float32)

            for i in range(20, n):
                idx = i - 20
                # Returns
                feats[idx, 0] = (closes[i] / closes[i - 1] - 1) * 100  # 1-bar return
                feats[idx, 1] = (closes[i] / closes[max(0, i - 5)] - 1) * 100  # 5-bar return
                feats[idx, 2] = (closes[i] / closes[max(0, i - 10)] - 1) * 100  # 10-bar return
                feats[idx, 3] = (closes[i] / closes[max(0, i - 20)] - 1) * 100  # 20-bar return

                # Volatility
                ret_window = np.diff(np.log(closes[max(0, i - 10):i + 1]))
                feats[idx, 4] = np.std(ret_window) * 100 if len(ret_window) > 1 else 0

                # RSI-14
                window = closes[max(0, i - 14):i + 1]
                deltas = np.diff(window)
                gains = np.maximum(deltas, 0)
                losses = np.maximum(-deltas, 0)
                avg_gain = np.mean(gains) if len(gains) > 0 else 0
                avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
                feats[idx, 5] = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 50

                # High-Low range
                feats[idx, 6] = (highs[i] - lows[i]) / closes[i] * 100

                # Close position in range
                hl_range = highs[i] - lows[i]
                feats[idx, 7] = (closes[i] - lows[i]) / hl_range if hl_range > 0 else 0.5

                # Volume ratio
                vol_5 = np.mean(volumes[max(0, i - 5):i + 1])
                vol_20 = np.mean(volumes[max(0, i - 20):i + 1])
                feats[idx, 8] = vol_5 / vol_20 if vol_20 > 0 else 1.0

                # SMA distance
                sma20 = np.mean(closes[max(0, i - 20):i + 1])
                feats[idx, 9] = (closes[i] / sma20 - 1) * 100

                # Momentum
                feats[idx, 10] = closes[i] - closes[max(0, i - 10)]

                # Trend strength (ADX-like)
                feats[idx, 11] = abs(feats[idx, 3]) / (feats[idx, 4] + 0.01)

            tf_features[tf] = feats
            min_samples = min(min_samples, len(feats))

        if min_samples == float("inf") or min_samples < 10:
            return None

        # Align all timeframes to the same number of samples (use last N from each)
        aligned = []
        for tf in TFT_TIMEFRAMES:
            if tf_features[tf] is None:
                aligned.append(np.zeros((min_samples, FEATURES_PER_TF), dtype=np.float32))
            else:
                aligned.append(tf_features[tf][-min_samples:])

        # Concatenate: (n_samples, 5 * 12 = 60)
        return np.hstack(aligned)

    async def train(self, db=None, max_symbols: int = 500, epochs: int = 50, batch_size: int = 512) -> Dict[str, Any]:
        """
        Train TFT on multi-timeframe data from MongoDB.
        """
        torch, nn = _try_import_torch()
        if torch is None:
            return {"success": False, "error": "PyTorch not installed"}

        db = db if db is not None else self._db
        if db is not None:
            self._db = db
        if db is None:
            return {"success": False, "error": "No database connection"}

        logger.info("[TFT] Starting multi-timeframe training...")

        # Get symbols that have data across multiple timeframes
        pipeline = [
            {"$match": {"bar_size": "1 day"}},
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gte": 100}}},
            {"$sort": {"count": -1}},
            {"$limit": max_symbols},
        ]
        symbols = [r["_id"] for r in db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True)]
        logger.info(f"[TFT] Found {len(symbols)} symbols with sufficient daily data")

        # Extract multi-timeframe features
        all_features = []
        all_targets = []
        symbols_used = 0

        for sym_idx, symbol in enumerate(symbols):
            if sym_idx % 100 == 0:
                logger.info(f"[TFT] Processing symbol {sym_idx + 1}/{len(symbols)}: {symbol}")

            bars_by_tf = {}
            for tf in TFT_TIMEFRAMES:
                cursor = db["ib_historical_data"].find(
                    {"symbol": symbol, "bar_size": tf},
                    {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
                ).sort("date", -1).limit(5000).max_time_ms(60000)
                bars = list(cursor)
                bars.reverse()  # Back to chronological order
                if bars:
                    bars_by_tf[tf] = bars

            features = self.extract_multi_tf_features(symbol, bars_by_tf)
            if features is None or len(features) < 10:
                continue

            # Target: direction of daily close 5 bars ahead
            daily_bars = bars_by_tf.get("1 day", [])
            daily_closes = np.array([b["close"] for b in daily_bars], dtype=np.float32)

            # Align targets with features (features start at bar 20)
            n_feats = len(features)
            n_daily = len(daily_closes)

            # Features are from bars[20:n], targets need bars[25:n+5]
            max_target_idx = min(n_daily, 20 + n_feats + 5)
            usable = min(n_feats, max_target_idx - 25)

            if usable < 10:
                continue

            targets = np.zeros(usable, dtype=np.int64)
            for i in range(usable):
                future_idx = 20 + i + 5
                current_idx = 20 + i
                if future_idx < n_daily:
                    targets[i] = 1 if daily_closes[future_idx] > daily_closes[current_idx] else 0

            all_features.append(features[:usable])
            all_targets.append(targets)
            symbols_used += 1

        if not all_features:
            return {"success": False, "error": "No usable multi-timeframe data found"}

        X = np.vstack(all_features)
        y = np.concatenate(all_targets)

        logger.info(f"[TFT] Training data: {X.shape[0]:,} samples from {symbols_used} symbols, {X.shape[1]} features")

        # Class balance diagnostic — detects majority-class collapse.
        # U.S. equities have a ~3% upward bias, so "always predict UP" gets ~52-53%.
        # If final val_acc ≤ majority_pct + 1%, the model learned nothing useful.
        class_counts = np.bincount(y, minlength=2)
        majority_pct = class_counts.max() / len(y) if len(y) > 0 else 0.5
        logger.info(
            f"[TFT] Class balance: down={class_counts[0]}, up={class_counts[1]}, "
            f"majority={majority_pct:.3%} (this is the 'always predict majority' baseline)"
        )

        # Normalize
        self._scaler_mean = X.mean(axis=0).astype(np.float32)
        self._scaler_std = (X.std(axis=0) + 1e-8).astype(np.float32)
        X_norm = (X - self._scaler_mean) / self._scaler_std

        # Split
        split_idx = int(len(X_norm) * 0.8)
        X_train, X_val = X_norm[:split_idx], X_norm[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        # Build model
        self._build_model()

        # Convert to tensors
        X_train_t = torch.tensor(X_train, dtype=torch.float32, device=self._device)
        y_train_t = torch.tensor(y_train, dtype=torch.long, device=self._device)
        X_val_t = torch.tensor(X_val, dtype=torch.float32, device=self._device)
        y_val_t = torch.tensor(y_val, dtype=torch.long, device=self._device)

        # Training
        optimizer = torch.optim.AdamW(self._model.parameters(), lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        criterion = nn.CrossEntropyLoss()

        best_val_acc = 0
        best_state = None

        for epoch in range(epochs):
            self._model.train()
            perm = torch.randperm(len(X_train_t))
            total_loss = 0
            n_batches = 0

            for i in range(0, len(X_train_t), batch_size):
                batch_x = X_train_t[perm[i:i + batch_size]]
                batch_y = y_train_t[perm[i:i + batch_size]]

                direction, confidence, tf_weights, attn_weights = self._model(batch_x)
                loss = criterion(direction, batch_y)

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
                val_dir, val_conf, _, _ = self._model(X_val_t)
                val_pred = torch.argmax(val_dir, dim=-1)
                val_acc = (val_pred == y_val_t).float().mean().item()

            if epoch % 10 == 0:
                logger.info(f"[TFT] Epoch {epoch}/{epochs} — loss: {total_loss / n_batches:.4f}, val_acc: {val_acc:.4f}")

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_state = {k: v.clone() for k, v in self._model.state_dict().items()}

        # Load best model
        if best_state:
            self._model.load_state_dict(best_state)

        self._trained = True
        self._accuracy = best_val_acc
        self._training_samples = len(X)
        self._version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Get timeframe importance
        self._model.eval()
        with torch.no_grad():
            _, _, tf_weights, _ = self._model(X_val_t[:100])
            avg_tf_weights = tf_weights.mean(dim=0).cpu().numpy()
        tf_importance = {tf: float(w) for tf, w in zip(TFT_TIMEFRAMES, avg_tf_weights)}

        self._save_model()

        # Edge above majority-class baseline — the ONLY number that matters.
        # If edge ≤ ~1%, the model just learned "predict majority class" (no real signal).
        edge_vs_baseline = best_val_acc - majority_pct
        if edge_vs_baseline <= 0.01:
            logger.warning(
                f"[TFT] ⚠️  val_acc={best_val_acc:.4f} is at/below majority baseline "
                f"({majority_pct:.4f}). Model likely collapsed to always predicting majority class — "
                f"DO NOT PROMOTE."
            )
        else:
            logger.info(
                f"[TFT] val_acc={best_val_acc:.4f}, majority_baseline={majority_pct:.4f}, "
                f"edge_above_baseline={edge_vs_baseline:+.4f}"
            )

        return {
            "success": True,
            "model": self.MODEL_NAME,
            "version": self._version,
            "accuracy": best_val_acc,
            "majority_baseline": float(majority_pct),
            "edge_above_baseline": float(edge_vs_baseline),
            "class_counts": {"down": int(class_counts[0]), "up": int(class_counts[1])},
            "training_samples": len(X),
            "symbols_used": symbols_used,
            "timeframe_importance": tf_importance,
            "device": str(self._device),
        }

    def predict(self, bars_by_tf: Dict[str, List[Dict]], symbol: str = "UNKNOWN") -> Dict[str, Any]:
        """
        Predict direction using multi-timeframe data.
        
        Args:
            bars_by_tf: Dict mapping timeframe to recent bars for the symbol
            symbol: Stock symbol (for logging)
            
        Returns:
            {
                "direction": "up" | "down" | "flat",
                "confidence": float,
                "timeframe_weights": dict,
            }
        """
        torch, _ = _try_import_torch()
        if torch is None or not self._trained or self._model is None:
            return {"direction": "flat", "confidence": 0.0, "has_prediction": False}

        features = self.extract_multi_tf_features(symbol, bars_by_tf)
        if features is None or len(features) == 0:
            return {"direction": "flat", "confidence": 0.0, "has_prediction": False}

        latest = features[-1:]
        latest_norm = (latest - self._scaler_mean) / self._scaler_std

        self._model.eval()
        with torch.no_grad():
            x = torch.tensor(latest_norm, dtype=torch.float32, device=self._device)
            direction_logits, confidence, tf_weights, _ = self._model(x)

            probs = torch.softmax(direction_logits, dim=-1).cpu().numpy()[0]
            conf = confidence.cpu().item()
            weights = tf_weights.cpu().numpy()[0]

        # Map to direction
        pred_class = int(np.argmax(probs))
        direction_map = {0: "down", 1: "up", 2: "flat"}
        direction = direction_map.get(pred_class, "flat")

        tf_importance = {tf: float(w) for tf, w in zip(TFT_TIMEFRAMES, weights)}

        return {
            "direction": direction,
            "confidence": conf,
            "probabilities": {"up": float(probs[1]), "down": float(probs[0]), "flat": float(probs[2]) if len(probs) > 2 else 0.0},
            "timeframe_weights": tf_importance,
            "has_prediction": True,
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
                "scaler_mean": self._scaler_mean.tolist(),
                "scaler_std": self._scaler_std.tolist(),
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
                    "model_type": "tft",
                    "version": self._version,
                    "accuracy": self._accuracy,
                    "training_samples": self._training_samples,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True
            )
            logger.info(f"[TFT] Saved model {self._version} (acc={self._accuracy:.4f})")
            return True
        except Exception as e:
            logger.error(f"[TFT] Failed to save model: {e}")
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
            self._scaler_mean = np.array(checkpoint["scaler_mean"], dtype=np.float32)
            self._scaler_std = np.array(checkpoint["scaler_std"], dtype=np.float32)
            self._version = checkpoint.get("version", "v0.0.0")
            self._accuracy = checkpoint.get("accuracy", 0.0)
            self._training_samples = checkpoint.get("training_samples", 0)
            self._trained = True
            self._model.eval()

            logger.info(f"[TFT] Loaded model {self._version} (acc={self._accuracy:.4f})")
            return True
        except Exception as e:
            logger.error(f"[TFT] Failed to load model: {e}")
            return False
