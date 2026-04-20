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
DIRECTIONS = ["down", "up", "flat"]


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
                    nn.Linear(64, 3),  # up, down, flat
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
                                   forecast_horizon: int = 5) -> tuple:
        """
        Extract sequential feature windows for CNN-LSTM training.
        
        Creates overlapping sequences of feature windows where each sequence
        captures the evolution of technical indicators over SEQUENCE_LENGTH steps.
        
        Returns:
            (features, targets) where:
                features: np.ndarray (n_samples, SEQUENCE_LENGTH, 46)
                targets: np.ndarray (n_samples,) with values 0=down, 1=up
        """
        if len(bars) < lookback + SEQUENCE_LENGTH + forecast_horizon:
            return None, None

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

        # Create sequences
        sequences = []
        targets = []
        n_feats = len(all_bar_features)

        for i in range(SEQUENCE_LENGTH, n_feats - forecast_horizon):
            seq = all_bar_features[i - SEQUENCE_LENGTH:i]
            sequences.append(seq)

            # Target: direction of close after forecast_horizon bars
            current_close_idx = lookback + i
            future_close_idx = current_close_idx + forecast_horizon
            if future_close_idx < n:
                targets.append(1 if closes[future_close_idx] > closes[current_close_idx] else 0)
            else:
                targets.append(0)

        if not sequences:
            return None, None

        return np.array(sequences, dtype=np.float32), np.array(targets, dtype=np.int64)

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
        symbols_used = 0

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

            seqs, tgts = self.extract_sequence_features(bars)
            if seqs is not None and len(seqs) > 10:
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
        # "Always predict UP" baseline on U.S. equities sits around 52-53%.
        class_counts = np.bincount(y, minlength=2)
        majority_pct = class_counts.max() / len(y) if len(y) > 0 else 0.5
        logger.info(
            f"[CNN-LSTM] Class balance: down={class_counts[0]}, up={class_counts[1]}, "
            f"majority={majority_pct:.3%} (always-predict-majority baseline)"
        )

        # Normalize features
        X_flat = X.reshape(-1, X.shape[-1])
        self._scaler_mean = X_flat.mean(axis=0).astype(np.float32)
        self._scaler_std = (X_flat.std(axis=0) + 1e-8).astype(np.float32)
        X_norm = (X - self._scaler_mean) / self._scaler_std

        # Split
        split_idx = int(len(X_norm) * 0.8)
        X_train, X_val = X_norm[:split_idx], X_norm[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        self._build_model()

        X_train_t = torch.tensor(X_train, dtype=torch.float32, device=self._device)
        y_train_t = torch.tensor(y_train, dtype=torch.long, device=self._device)
        X_val_t = torch.tensor(X_val, dtype=torch.float32, device=self._device)
        y_val_t = torch.tensor(y_val, dtype=torch.long, device=self._device)

        optimizer = torch.optim.AdamW(self._model.parameters(), lr=5e-4, weight_decay=1e-4)
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

                direction, win_prob, attn = self._model(batch_x)
                loss = criterion(direction, batch_y)

                # Add win probability auxiliary loss
                win_target = (batch_y == 1).float().unsqueeze(-1)
                loss += 0.3 * nn.functional.binary_cross_entropy(win_prob, win_target)

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
                val_dir, val_win, _ = self._model(X_val_t)
                val_pred = torch.argmax(val_dir, dim=-1)
                val_acc = (val_pred == y_val_t).float().mean().item()
                val_win_prob = val_win.squeeze(-1)

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
            "class_counts": {"down": int(class_counts[0]), "up": int(class_counts[1])},
            "training_samples": len(X),
            "symbols_used": symbols_used,
            "device": str(self._device),
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
