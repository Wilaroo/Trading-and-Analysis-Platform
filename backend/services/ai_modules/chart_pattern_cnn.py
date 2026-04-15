"""
Chart Pattern CNN — ResNet-18 based visual pattern recognition for trading.

Two prediction heads:
  1. Pattern Classification → BREAKOUT, SCALP, ORB, REVERSAL, etc.
  2. Win Probability → 0.0 - 1.0 (likelihood the setup results in a winning trade)

Uses transfer learning from ImageNet pretrained weights.
Auto-detects GPU (CUDA) and falls back to CPU gracefully.
"""
import os
import logging
import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Device setup ────────────────────────────────────────────────
_DEVICE = None
_GPU_INFO = None

def get_device():
    """Get PyTorch device. Caches after first call."""
    global _DEVICE, _GPU_INFO
    if _DEVICE is not None:
        return _DEVICE

    import torch
    if torch.cuda.is_available():
        _DEVICE = torch.device("cuda")
        gpu_name = torch.cuda.get_device_name(0)
        vram_mb = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
        _GPU_INFO = {"gpu": gpu_name, "vram_mb": vram_mb, "cuda": True}
        logger.info(f"CNN using GPU: {gpu_name} ({vram_mb} MB VRAM)")
    else:
        _DEVICE = torch.device("cpu")
        _GPU_INFO = {"gpu": "None", "vram_mb": 0, "cuda": False}
        logger.info("CNN using CPU (no CUDA detected)")
    return _DEVICE


def get_gpu_info() -> Dict:
    """Return GPU information."""
    get_device()  # ensure initialized
    return _GPU_INFO or {"gpu": "Unknown", "vram_mb": 0, "cuda": False}


# ── Setup types for classification ──────────────────────────────
SETUP_CLASSES = [
    "SCALP", "ORB", "GAP_AND_GO", "VWAP", "BREAKOUT", "RANGE",
    "MEAN_REVERSION", "REVERSAL", "TREND_CONTINUATION", "MOMENTUM",
    "SHORT_SCALP", "SHORT_ORB", "SHORT_BREAKDOWN", "SHORT_FADE",
    "SHORT_REVERSAL", "SHORT_MOMENTUM", "UNKNOWN"
]

CLASS_TO_IDX = {c: i for i, c in enumerate(SETUP_CLASSES)}
IDX_TO_CLASS = {i: c for i, c in enumerate(SETUP_CLASSES)}

# ── CNN window sizes per setup (candles before entry) ───────────
CNN_WINDOW_SIZES = {
    "SCALP":              35,
    "SHORT_SCALP":        35,
    "ORB":                40,
    "SHORT_ORB":          40,
    "GAP_AND_GO":         35,
    "VWAP":               40,
    "BREAKOUT":           80,
    "SHORT_BREAKDOWN":    80,
    "RANGE":              60,
    "MEAN_REVERSION":     50,
    "REVERSAL":           60,
    "SHORT_REVERSAL":     60,
    "SHORT_FADE":         40,
    "TREND_CONTINUATION": 80,
    "MOMENTUM":           70,
    "SHORT_MOMENTUM":     70,
}

DEFAULT_WINDOW_SIZE = 50
CNN_IMAGE_SIZE = 224  # ResNet input size


# ── Model Definition ────────────────────────────────────────────
def build_cnn_model(num_classes: int = None):
    """
    Build a ResNet-18 with two prediction heads:
      - Pattern classifier (num_classes outputs)
      - Win probability (1 output, sigmoid)

    Uses ImageNet pretrained weights for transfer learning.
    """
    import torch
    import torch.nn as nn

    try:
        import torchvision
    except ImportError:
        raise ImportError(
            "torchvision not installed. Run InstallML_GPU.bat or: "
            "pip install torchvision"
        )

    if num_classes is None:
        num_classes = len(SETUP_CLASSES)

    try:
        from torchvision.models import resnet18, ResNet18_Weights
        backbone = resnet18(weights=ResNet18_Weights.DEFAULT)
    except ImportError:
        from torchvision.models import resnet18
        backbone = resnet18(pretrained=True)

    # Freeze early layers (conv1 + layer1) — they already know edges/shapes
    for name, param in backbone.named_parameters():
        if name.startswith(("conv1", "bn1", "layer1")):
            param.requires_grad = False

    # Remove original fc layer
    feature_dim = backbone.fc.in_features  # 512 for ResNet-18
    backbone.fc = nn.Identity()

    class ChartPatternCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = backbone
            self.dropout = nn.Dropout(0.3)

            # Head 1: Pattern classification
            self.pattern_head = nn.Sequential(
                nn.Linear(feature_dim, 256),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(256, num_classes)
            )

            # Head 2: Win probability
            self.win_head = nn.Sequential(
                nn.Linear(feature_dim, 128),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(128, 1),
                nn.Sigmoid()
            )

        def forward(self, x):
            features = self.backbone(x)
            features = self.dropout(features)
            pattern_logits = self.pattern_head(features)
            win_prob = self.win_head(features).squeeze(-1)
            return pattern_logits, win_prob

        def extract_features(self, x):
            """Extract the 512-dim feature vector (for ensemble integration)."""
            return self.backbone(x)

    model = ChartPatternCNN()
    return model


# ── Model Persistence (MongoDB) ─────────────────────────────────
def save_model_to_db(db, model, setup_type: str, bar_size: str, metrics: Dict):
    """Save trained CNN model weights and metadata to MongoDB."""
    import torch
    import io

    model_name = f"cnn_{setup_type.lower()}_{bar_size.replace(' ', '')}"

    # Serialize model state dict to bytes
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    model_bytes = buffer.getvalue()

    doc = {
        "model_name": model_name,
        "setup_type": setup_type,
        "bar_size": bar_size,
        "model_type": "cnn_resnet18",
        "model_weights": model_bytes,
        "metrics": metrics,
        "num_classes": len(SETUP_CLASSES),
        "image_size": CNN_IMAGE_SIZE,
        "window_size": CNN_WINDOW_SIZES.get(setup_type, DEFAULT_WINDOW_SIZE),
        "gpu_info": get_gpu_info(),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    col = db["cnn_models"]
    col.update_one(
        {"model_name": model_name},
        {"$set": doc},
        upsert=True
    )
    logger.info(f"Saved CNN model: {model_name} (acc={metrics.get('accuracy', 0):.3f})")
    return model_name


def load_model_from_db(db, setup_type: str, bar_size: str):
    """Load a trained CNN model from MongoDB. Returns (model, metadata) or (None, None)."""
    import torch
    import io

    model_name = f"cnn_{setup_type.lower()}_{bar_size.replace(' ', '')}"
    col = db["cnn_models"]
    doc = col.find_one({"model_name": model_name})

    if not doc:
        return None, None

    model = build_cnn_model(num_classes=doc.get("num_classes", len(SETUP_CLASSES)))
    buffer = io.BytesIO(doc["model_weights"])
    state_dict = torch.load(buffer, map_location=get_device(), weights_only=True)
    model.load_state_dict(state_dict)
    model.to(get_device())
    model.eval()

    metadata = {
        "model_name": doc["model_name"],
        "setup_type": doc["setup_type"],
        "bar_size": doc["bar_size"],
        "metrics": doc.get("metrics", {}),
        "trained_at": doc.get("trained_at"),
        "window_size": doc.get("window_size", DEFAULT_WINDOW_SIZE),
    }
    return model, metadata


def list_cnn_models(db) -> List[Dict]:
    """List all saved CNN models with their metrics."""
    col = db["cnn_models"]
    models = []
    for doc in col.find({}, {"model_weights": 0, "_id": 0}):
        models.append(doc)
    return models


# ── Inference ───────────────────────────────────────────────────
def predict_from_image(model, image_tensor) -> Dict:
    """
    Run inference on a single chart image.

    Args:
        model: Loaded ChartPatternCNN
        image_tensor: Preprocessed image tensor (1, 3, 224, 224)

    Returns:
        {pattern, pattern_confidence, win_probability, all_patterns}
    """
    import torch

    device = get_device()
    model.eval()

    with torch.no_grad():
        image_tensor = image_tensor.to(device)
        if image_tensor.dim() == 3:
            image_tensor = image_tensor.unsqueeze(0)

        pattern_logits, win_prob = model(image_tensor)

        # Pattern classification
        probs = torch.softmax(pattern_logits, dim=1).cpu().numpy()[0]
        top_idx = probs.argmax()
        pattern = IDX_TO_CLASS.get(top_idx, "UNKNOWN")
        confidence = float(probs[top_idx])

        # Win probability
        win_probability = float(win_prob.cpu().numpy()[0])

        # Top-3 patterns
        top3_indices = probs.argsort()[-3:][::-1]
        all_patterns = [
            {"pattern": IDX_TO_CLASS.get(i, "UNKNOWN"), "confidence": float(probs[i])}
            for i in top3_indices
        ]

    return {
        "pattern": pattern,
        "pattern_confidence": round(confidence, 4),
        "win_probability": round(win_probability, 4),
        "top_patterns": all_patterns,
    }


def get_image_transform():
    """Get the standard image preprocessing transform for CNN input."""
    try:
        from torchvision import transforms
    except ImportError:
        logger.warning("torchvision not installed — CNN transforms unavailable")
        return None

    return transforms.Compose([
        transforms.Resize((CNN_IMAGE_SIZE, CNN_IMAGE_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],  # ImageNet norms
            std=[0.229, 0.224, 0.225]
        ),
    ])
