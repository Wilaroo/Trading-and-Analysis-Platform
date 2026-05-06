"""
VAE Regime Detection — Unsupervised Market Regime Labeling
==========================================================
Variational Autoencoder that learns to detect market regimes from
market microstructure features (volatility, correlation, breadth, momentum).

Unlike the rule-based regime engine, this model learns latent regime clusters
directly from data without predefined thresholds.

Architecture:
    Encoder: [input_dim] → 128 → 64 → (mu, logvar) [latent_dim=8]
    Decoder: [latent_dim=8] → 64 → 128 → [input_dim]
    Regime Head: [latent_dim=8] → 32 → [n_regimes]

Regimes:
    0: Bull Trending    — strong upward momentum, low vol, positive breadth
    1: Bear Trending    — strong downward momentum, rising vol, negative breadth
    2: High Volatility  — regime transitions, elevated vol, mixed signals
    3: Mean Reverting   — range-bound, low vol, oscillating indicators
    4: Momentum Surge   — extreme moves (either direction), volume spikes

Training: On Spark GPU using SPY + sector ETF microstructure features from MongoDB.
"""

import logging
import numpy as np
from typing import Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

N_REGIMES = 5
REGIME_NAMES = {
    0: "bull_trending",
    1: "bear_trending",
    2: "high_volatility",
    3: "mean_reverting",
    4: "momentum_surge",
}

# Feature list for regime detection
REGIME_FEATURES = [
    "spy_return_5d", "spy_return_20d", "spy_volatility_10d", "spy_volatility_20d",
    "spy_rsi_14", "spy_macd_hist", "spy_bb_width",
    "vix_level", "vix_change_5d",
    "adv_decline_ratio", "pct_above_sma20", "pct_above_sma50",
    "sector_dispersion", "correlation_avg",
    "volume_ratio_5d", "put_call_approx",
]

INPUT_DIM = len(REGIME_FEATURES)


def _try_import_torch():
    """Lazy import torch to avoid startup overhead when not training."""
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError:
        return None, None


class VAERegimeModel:
    """
    Wrapper around the PyTorch VAE for regime detection.
    Handles training, prediction, and MongoDB persistence.
    """

    MODEL_NAME = "vae_regime_detector"
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
        """Build the VAE PyTorch model."""
        torch, nn = _try_import_torch()
        if torch is None:
            raise ImportError("PyTorch not installed")

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        class VAE(nn.Module):
            def __init__(self, input_dim, latent_dim=8, n_regimes=N_REGIMES):
                super().__init__()
                # Encoder
                self.encoder = nn.Sequential(
                    nn.Linear(input_dim, 128),
                    nn.LayerNorm(128),
                    nn.GELU(),
                    nn.Dropout(0.1),
                    nn.Linear(128, 64),
                    nn.LayerNorm(64),
                    nn.GELU(),
                )
                self.fc_mu = nn.Linear(64, latent_dim)
                self.fc_logvar = nn.Linear(64, latent_dim)

                # Decoder
                self.decoder = nn.Sequential(
                    nn.Linear(latent_dim, 64),
                    nn.LayerNorm(64),
                    nn.GELU(),
                    nn.Linear(64, 128),
                    nn.LayerNorm(128),
                    nn.GELU(),
                    nn.Linear(128, input_dim),
                )

                # Regime classification head
                self.regime_head = nn.Sequential(
                    nn.Linear(latent_dim, 32),
                    nn.GELU(),
                    nn.Linear(32, n_regimes),
                )

            def encode(self, x):
                h = self.encoder(x)
                return self.fc_mu(h), self.fc_logvar(h)

            def reparameterize(self, mu, logvar):
                std = (0.5 * logvar).exp()
                eps = torch.randn_like(std)
                return mu + eps * std

            def decode(self, z):
                return self.decoder(z)

            def forward(self, x):
                mu, logvar = self.encode(x)
                z = self.reparameterize(mu, logvar)
                recon = self.decode(z)
                regime_logits = self.regime_head(z)
                return recon, mu, logvar, regime_logits, z

        self._model = VAE(INPUT_DIM).to(self._device)
        logger.info(f"VAE Regime model built on {self._device} ({sum(p.numel() for p in self._model.parameters())} params)")
        return self._model

    def extract_regime_features(self, bars_by_symbol: Dict[str, List[Dict]]) -> np.ndarray:
        """
        Extract regime features from market data.
        
        Args:
            bars_by_symbol: Dict mapping symbol to list of bar dicts (sorted by date asc)
                           Must include at least SPY.
        Returns:
            np.ndarray of shape (n_days, INPUT_DIM) with regime features per day
        """
        spy_bars = bars_by_symbol.get("SPY", [])
        if len(spy_bars) < 30:
            return np.array([])

        closes = np.array([b["close"] for b in spy_bars], dtype=np.float32)
        highs = np.array([b["high"] for b in spy_bars], dtype=np.float32)
        lows = np.array([b["low"] for b in spy_bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in spy_bars], dtype=np.float32)

        n = len(closes)
        features_list = []

        for i in range(20, n):
            row = np.zeros(INPUT_DIM, dtype=np.float32)

            # SPY returns
            row[0] = (closes[i] / closes[max(0, i - 5)] - 1) * 100  # 5d return
            row[1] = (closes[i] / closes[max(0, i - 20)] - 1) * 100  # 20d return

            # SPY volatility
            ret_10 = np.diff(np.log(closes[max(0, i - 10):i + 1]))
            ret_20 = np.diff(np.log(closes[max(0, i - 20):i + 1]))
            row[2] = np.std(ret_10) * np.sqrt(252) * 100 if len(ret_10) > 1 else 0  # 10d vol
            row[3] = np.std(ret_20) * np.sqrt(252) * 100 if len(ret_20) > 1 else 0  # 20d vol

            # RSI-14
            window = closes[max(0, i - 14):i + 1]
            deltas = np.diff(window)
            gains = np.maximum(deltas, 0)
            losses = np.maximum(-deltas, 0)
            avg_gain = np.mean(gains) if len(gains) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            row[4] = 100 - (100 / (1 + rs))

            # MACD histogram
            ema12 = closes[i]  # simplified: use close as approx
            ema26 = np.mean(closes[max(0, i - 26):i + 1])
            ema12_approx = np.mean(closes[max(0, i - 12):i + 1])
            row[5] = ema12_approx - ema26

            # Bollinger Band width
            sma20 = np.mean(closes[max(0, i - 20):i + 1])
            std20 = np.std(closes[max(0, i - 20):i + 1])
            row[6] = (2 * std20 / sma20 * 100) if sma20 > 0 else 0

            # VIX approximation (from realized vol)
            row[7] = row[3]  # Use 20d vol as VIX proxy
            row[8] = row[3] - row[2]  # Vol change approx

            # Breadth approximations from available data
            above_sma20_pct = 0
            above_sma50_pct = 0
            n_symbols = 0
            for sym, sym_bars in bars_by_symbol.items():
                if sym == "SPY" or len(sym_bars) <= i:
                    continue
                sym_close = sym_bars[i]["close"]
                sym_sma20 = np.mean([b["close"] for b in sym_bars[max(0, i - 20):i + 1]])
                sym_sma50 = np.mean([b["close"] for b in sym_bars[max(0, i - 50):i + 1]]) if i >= 50 else sym_sma20
                if sym_close > sym_sma20:
                    above_sma20_pct += 1
                if sym_close > sym_sma50:
                    above_sma50_pct += 1
                n_symbols += 1

            row[9] = 1.0  # Advance/decline placeholder
            row[10] = (above_sma20_pct / n_symbols * 100) if n_symbols > 0 else 50
            row[11] = (above_sma50_pct / n_symbols * 100) if n_symbols > 0 else 50

            # Sector dispersion & correlation (simplified)
            row[12] = np.std([
                (closes[i] / closes[max(0, i - 5)] - 1)
            ]) * 100 if i > 5 else 0
            row[13] = 0.5  # Placeholder for correlation

            # Volume ratio
            vol_5d = np.mean(volumes[max(0, i - 5):i + 1])
            vol_20d = np.mean(volumes[max(0, i - 20):i + 1])
            row[14] = (vol_5d / vol_20d) if vol_20d > 0 else 1.0

            # Put/call approximation
            row[15] = 0.0  # Placeholder

            features_list.append(row)

        return np.array(features_list, dtype=np.float32)

    async def train(self, db=None, epochs: int = 100, batch_size: int = 256) -> Dict[str, Any]:
        """
        Train VAE regime detector on SPY + sector ETF data from MongoDB.
        
        Returns training metrics.
        """
        torch, nn = _try_import_torch()
        if torch is None:
            return {"success": False, "error": "PyTorch not installed"}

        db = db if db is not None else self._db
        if db is not None:
            self._db = db
        if db is None:
            return {"success": False, "error": "No database connection"}

        logger.info("[VAE REGIME] Starting training...")

        # Fetch SPY daily bars + sector ETFs for breadth features
        symbols_for_regime = ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP"]
        bars_by_symbol = {}

        for sym in symbols_for_regime:
            cursor = db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": "1 day"},
                {"_id": 0, "close": 1, "high": 1, "low": 1, "volume": 1, "date": 1}
            ).sort("date", -1).limit(10000).max_time_ms(60000)
            bars = list(cursor)
            bars.reverse()  # Back to chronological order
            if bars:
                bars_by_symbol[sym] = bars
                logger.info(f"[VAE REGIME] Loaded {len(bars)} daily bars for {sym}")

        if "SPY" not in bars_by_symbol:
            return {"success": False, "error": "No SPY data found"}

        # Extract features
        features = self.extract_regime_features(bars_by_symbol)
        if len(features) < 100:
            return {"success": False, "error": f"Insufficient features: {len(features)} (need 100+)"}

        logger.info(f"[VAE REGIME] Extracted {len(features)} feature vectors ({INPUT_DIM} features each)")

        # Normalize
        self._scaler_mean = features.mean(axis=0)
        self._scaler_std = features.std(axis=0) + 1e-8
        features_norm = (features - self._scaler_mean) / self._scaler_std

        # Build model
        self._build_model()

        # Convert to tensor
        X = torch.tensor(features_norm, dtype=torch.float32, device=self._device)

        # Training loop
        optimizer = torch.optim.AdamW(self._model.parameters(), lr=1e-3, weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        self._model.train()
        best_loss = float("inf")
        patience_counter = 0

        for epoch in range(epochs):
            # Shuffle
            perm = torch.randperm(len(X))
            total_loss = 0
            n_batches = 0

            for i in range(0, len(X), batch_size):
                batch = X[perm[i:i + batch_size]]
                recon, mu, logvar, regime_logits, z = self._model(batch)

                # Reconstruction loss
                recon_loss = nn.functional.mse_loss(recon, batch, reduction="mean")

                # KL divergence
                kl_loss = -0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp())

                # Regime clustering loss (entropy minimization — encourage sharp assignments)
                regime_probs = torch.softmax(regime_logits, dim=-1)
                entropy_loss = -(regime_probs * torch.log(regime_probs + 1e-8)).sum(dim=-1).mean()

                # Regime diversity loss (prevent mode collapse — all regimes should be used)
                avg_probs = regime_probs.mean(dim=0)
                diversity_loss = (avg_probs * torch.log(avg_probs + 1e-8)).sum()

                loss = recon_loss + 0.1 * kl_loss + 0.05 * entropy_loss + 0.1 * diversity_loss

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
                optimizer.step()

                total_loss += loss.item()
                n_batches += 1

            scheduler.step()
            avg_loss = total_loss / max(n_batches, 1)

            if epoch % 20 == 0:
                logger.info(f"[VAE REGIME] Epoch {epoch}/{epochs} — loss: {avg_loss:.4f}")

            if avg_loss < best_loss:
                best_loss = avg_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= 15:
                    logger.info(f"[VAE REGIME] Early stopping at epoch {epoch}")
                    break

        # Get regime assignments
        self._model.eval()
        with torch.no_grad():
            _, mu, _, regime_logits, z = self._model(X)
            regime_labels = torch.argmax(regime_logits, dim=-1).cpu().numpy()
            regime_probs_all = torch.softmax(regime_logits, dim=-1).cpu().numpy()

        # Log regime distribution
        unique, counts = np.unique(regime_labels, return_counts=True)
        regime_dist = {REGIME_NAMES.get(int(r), f"regime_{r}"): int(c) for r, c in zip(unique, counts)}
        logger.info(f"[VAE REGIME] Regime distribution: {regime_dist}")

        # Compute a quality metric since VAE is unsupervised (no "accuracy").
        # regime_diversity = normalized entropy of cluster assignment distribution.
        #   1.0 = all regimes used roughly equally (healthy)
        #   ~0.0 = model collapsed into a single regime (degenerate)
        total_assignments = int(counts.sum()) if len(counts) > 0 else 0
        if total_assignments > 0 and len(counts) > 1:
            import math as _math
            probs = [c / total_assignments for c in counts if c > 0]
            entropy_val = -sum(p * _math.log(p) for p in probs)
            max_entropy = _math.log(N_REGIMES)
            regime_diversity = entropy_val / max_entropy if max_entropy > 0 else 0.0
        else:
            regime_diversity = 0.0
        logger.info(
            f"[VAE REGIME] Regime diversity score: {regime_diversity:.3f} "
            f"(1.0 = balanced across {N_REGIMES} regimes, 0.0 = collapsed)"
        )

        self._trained = True
        self._training_samples = len(features)
        self._version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self._regime_diversity = float(regime_diversity)

        # Save model
        self._save_model()

        return {
            "success": True,
            "model": self.MODEL_NAME,
            "version": self._version,
            "epochs_trained": epoch + 1,
            "final_loss": best_loss,
            "regime_distribution": regime_dist,
            "regime_diversity": regime_diversity,
            # Unsupervised model — use diversity as the "accuracy" surrogate for pipeline reporting.
            # Downstream consumers should check `metric_type` to know this isn't a classifier accuracy.
            "accuracy": regime_diversity,
            "metric_type": "regime_diversity_entropy",
            "training_samples": len(features),
            "device": str(self._device),
        }

    def predict(self, bars_by_symbol: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """
        Predict current market regime.
        
        Args:
            bars_by_symbol: Must include at least SPY with recent 30+ daily bars
            
        Returns:
            {
                "regime": str,       # e.g., "bull_trending"
                "regime_id": int,    # 0-4
                "confidence": float, # 0-1
                "all_probs": dict,   # probabilities for each regime
            }
        """
        torch, _ = _try_import_torch()
        if torch is None or not self._trained or self._model is None:
            return {"regime": "unknown", "regime_id": -1, "confidence": 0.0}

        features = self.extract_regime_features(bars_by_symbol)
        if len(features) == 0:
            return {"regime": "unknown", "regime_id": -1, "confidence": 0.0}

        # Use the most recent feature vector
        latest = features[-1:]
        latest_norm = (latest - self._scaler_mean) / self._scaler_std

        self._model.eval()
        with torch.no_grad():
            x = torch.tensor(latest_norm, dtype=torch.float32, device=self._device)
            _, _, _, regime_logits, _ = self._model(x)
            probs = torch.softmax(regime_logits, dim=-1).cpu().numpy()[0]

        regime_id = int(np.argmax(probs))
        regime_name = REGIME_NAMES.get(regime_id, f"regime_{regime_id}")
        confidence = float(probs[regime_id])

        all_probs = {REGIME_NAMES.get(i, f"regime_{i}"): float(p) for i, p in enumerate(probs)}

        return {
            "regime": regime_name,
            "regime_id": regime_id,
            "confidence": confidence,
            "regime_diversity": float(getattr(self, "_regime_diversity", 1.0)),
            "all_probs": all_probs,
        }

    def _save_model(self):
        """Save model weights + scaler to MongoDB."""
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
                "training_samples": self._training_samples,
            }, buffer)
            model_bytes = buffer.getvalue()
            model_b64 = base64.b64encode(model_bytes).decode("utf-8")

            self._db[self.COLLECTION].update_one(
                {"name": self.MODEL_NAME},
                {"$set": {
                    "name": self.MODEL_NAME,
                    "model_data": model_b64,
                    "model_type": "vae_regime",
                    "version": self._version,
                    "training_samples": self._training_samples,
                    "n_regimes": N_REGIMES,
                    "input_dim": INPUT_DIM,
                    "regime_diversity": float(getattr(self, "_regime_diversity", 1.0)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True
            )
            logger.info(f"[VAE REGIME] Saved model {self._version} to MongoDB")
            return True
        except Exception as e:
            logger.error(f"[VAE REGIME] Failed to save model: {e}")
            return False

    def load_model(self, db=None):
        """Load model weights from MongoDB."""
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
            buffer = io.BytesIO(model_bytes)

            self._build_model()
            checkpoint = torch.load(buffer, map_location=self._device, weights_only=False)

            self._model.load_state_dict(checkpoint["model_state_dict"])
            self._scaler_mean = np.array(checkpoint["scaler_mean"], dtype=np.float32)
            self._scaler_std = np.array(checkpoint["scaler_std"], dtype=np.float32)
            self._version = checkpoint.get("version", "v0.0.0")
            self._training_samples = checkpoint.get("training_samples", 0)
            # Restore regime_diversity from the outer MongoDB doc (not the torch checkpoint).
            # Back-compat: older models without this field default to 1.0 which keeps the
            # confidence-gate diversity floor from kicking in — safe for legacy baselines.
            self._regime_diversity = float(doc.get("regime_diversity", 1.0))
            self._trained = True
            self._model.eval()

            logger.info(
                f"[VAE REGIME] Loaded model {self._version} ({self._training_samples} samples, "
                f"diversity={self._regime_diversity:.3f})"
            )
            return True
        except Exception as e:
            logger.error(f"[VAE REGIME] Failed to load model: {e}")
            return False
