"""
CNN Training Pipeline — End-to-end chart pattern CNN training.

Pipeline stages:
  1. Generate labeled chart images from IB historical bars
  2. Build PyTorch datasets with train/val/test splits
  3. Train ResNet-18 model with dual heads (pattern + win prediction)
  4. Validate and compute metrics
  5. Save to MongoDB if accuracy meets threshold

Integrates with the existing worker.py job queue system.
"""
import os
import io
import logging
import time
from typing import Dict, List, Optional, Callable, Awaitable
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

# Minimum accuracy to promote a new model over the existing one
MIN_ACCURACY_THRESHOLD = 0.52  # Better than random (50%)
MIN_TRAINING_SAMPLES = 200


async def run_cnn_training(
    db,
    setup_type: str = "ALL",
    bar_size: str = None,
    max_symbols: int = None,
    progress_callback: Optional[Callable] = None,
) -> Dict:
    """
    Full CNN training pipeline for a setup type.

    Args:
        db: MongoDB database
        setup_type: Setup type or "ALL" for all types
        bar_size: Specific bar size, or None to train all profiles
        max_symbols: Limit symbols for faster training
        progress_callback: async fn(percent, message) for progress updates

    Returns:
        Training result dict with metrics per model
    """
    import torch
    from services.ai_modules.chart_pattern_cnn import (
        build_cnn_model, save_model_to_db, get_device, get_gpu_info,
        CNN_WINDOW_SIZES, DEFAULT_WINDOW_SIZE, SETUP_CLASSES, CLASS_TO_IDX
    )
    from services.ai_modules.chart_image_generator import (
        generate_training_images_from_bars, image_bytes_to_tensor
    )
    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES

    start_time = time.time()
    device = get_device()
    results = {}

    async def _progress(pct, msg):
        if progress_callback:
            await progress_callback(pct, msg)
        logger.info(f"[CNN {pct}%] {msg}")

    await _progress(1, f"Starting CNN training pipeline (device={device})")
    await _progress(2, f"GPU: {get_gpu_info()}")

    # Determine what to train
    if setup_type == "ALL":
        setups_to_train = list(SETUP_TRAINING_PROFILES.keys())
    else:
        setups_to_train = [setup_type]

    total_profiles = 0
    profile_list = []
    for st in setups_to_train:
        profiles = SETUP_TRAINING_PROFILES.get(st, [])
        for p in profiles:
            if bar_size and p["bar_size"] != bar_size:
                continue
            profile_list.append((st, p["bar_size"]))
            total_profiles += 1

    if total_profiles == 0:
        return {"success": False, "error": f"No profiles found for {setup_type}/{bar_size}"}

    await _progress(3, f"Training {total_profiles} CNN models across {len(setups_to_train)} setup types")

    trained_count = 0
    skipped_count = 0

    for idx, (st, bs) in enumerate(profile_list):
        profile_pct_start = 5 + int((idx / total_profiles) * 90)
        profile_pct_end = 5 + int(((idx + 1) / total_profiles) * 90)
        model_name = f"cnn_{st.lower()}_{bs.replace(' ', '')}"

        await _progress(profile_pct_start, f"[{idx + 1}/{total_profiles}] {st}/{bs}: Generating chart images...")

        # Stage 1: Generate training images
        window_size = CNN_WINDOW_SIZES.get(st, DEFAULT_WINDOW_SIZE)
        try:
            samples = generate_training_images_from_bars(
                db, st, bs,
                window_size=window_size,
                max_symbols=max_symbols or 50,
                max_bars_per_symbol=2000,
                max_samples=3000,
            )
        except Exception as e:
            logger.error(f"Image generation failed for {st}/{bs}: {e}")
            results[model_name] = {"success": False, "error": f"Image generation: {str(e)}"}
            skipped_count += 1
            continue

        if len(samples) < MIN_TRAINING_SAMPLES:
            logger.warning(f"Insufficient samples for {st}/{bs}: {len(samples)} < {MIN_TRAINING_SAMPLES}")
            results[model_name] = {
                "success": False,
                "error": f"Only {len(samples)} samples (need {MIN_TRAINING_SAMPLES})",
                "samples": len(samples),
            }
            skipped_count += 1
            continue

        await _progress(
            profile_pct_start + (profile_pct_end - profile_pct_start) // 3,
            f"[{idx + 1}/{total_profiles}] {st}/{bs}: {len(samples)} images, training CNN..."
        )

        # Stage 2: Prepare PyTorch dataset
        try:
            result = _train_single_model(
                samples, st, bs, device, db
            )
            results[model_name] = result

            if result.get("success"):
                trained_count += 1
                acc = result.get("metrics", {}).get("accuracy", 0)
                await _progress(
                    profile_pct_end,
                    f"[{idx + 1}/{total_profiles}] {st}/{bs}: TRAINED (acc={acc:.1%}, win_auc={result.get('metrics', {}).get('win_auc', 0):.3f})"
                )
            else:
                skipped_count += 1
                await _progress(profile_pct_end, f"[{idx + 1}/{total_profiles}] {st}/{bs}: {result.get('error', 'Failed')}")

        except Exception as e:
            logger.error(f"Training failed for {st}/{bs}: {e}", exc_info=True)
            results[model_name] = {"success": False, "error": str(e)}
            skipped_count += 1

    elapsed = time.time() - start_time
    await _progress(100, f"CNN pipeline complete: {trained_count} trained, {skipped_count} skipped in {elapsed:.0f}s")

    return {
        "success": trained_count > 0,
        "trained": trained_count,
        "skipped": skipped_count,
        "total_profiles": total_profiles,
        "elapsed_seconds": round(elapsed, 1),
        "gpu_info": get_gpu_info(),
        "models": results,
    }


def _train_single_model(
    samples: List[Dict],
    setup_type: str,
    bar_size: str,
    device,
    db,
) -> Dict:
    """Train a single CNN model from pre-generated samples."""
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader, random_split
    from services.ai_modules.chart_pattern_cnn import (
        build_cnn_model, save_model_to_db, load_model_from_db,
        CLASS_TO_IDX, MIN_ACCURACY_THRESHOLD,
        CNN_IMAGE_SIZE
    )
    from services.ai_modules.chart_image_generator import image_bytes_to_tensor

    # Build tensors from image bytes
    images = []
    pattern_labels = []
    win_labels = []

    for s in samples:
        try:
            tensor = image_bytes_to_tensor(s["image_bytes"])
            images.append(tensor)
            pattern_labels.append(CLASS_TO_IDX.get(s["setup_type"], CLASS_TO_IDX["UNKNOWN"]))
            win_labels.append(1.0 if s["outcome"] == "WIN" else 0.0)
        except Exception:
            continue

    if len(images) < MIN_TRAINING_SAMPLES:
        return {"success": False, "error": f"Only {len(images)} valid images after processing"}

    # Stack into tensors
    X = torch.stack(images)
    y_pattern = torch.tensor(pattern_labels, dtype=torch.long)
    y_win = torch.tensor(win_labels, dtype=torch.float32)

    # Dataset
    class ChartDataset(Dataset):
        def __init__(self, X, y_pattern, y_win):
            self.X = X
            self.y_pattern = y_pattern
            self.y_win = y_win
        def __len__(self):
            return len(self.X)
        def __getitem__(self, idx):
            return self.X[idx], self.y_pattern[idx], self.y_win[idx]

    dataset = ChartDataset(X, y_pattern, y_win)

    # Train/val/test split: 70/15/15
    n = len(dataset)
    n_train = int(0.7 * n)
    n_val = int(0.15 * n)
    n_test = n - n_train - n_val
    train_ds, val_ds, test_ds = random_split(dataset, [n_train, n_val, n_test])

    # Batch size based on available memory
    batch_size = 32 if device.type == "cuda" else 16
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    # Build model
    model = build_cnn_model()
    model.to(device)

    # Loss functions
    pattern_criterion = nn.CrossEntropyLoss()
    win_criterion = nn.BCELoss()

    # Optimizer — lower LR for frozen layers, higher for heads
    optimizer = optim.AdamW([
        {"params": model.backbone.parameters(), "lr": 1e-4},
        {"params": model.pattern_head.parameters(), "lr": 5e-4},
        {"params": model.win_head.parameters(), "lr": 5e-4},
    ], weight_decay=1e-4)

    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=0.5)

    # Training loop
    num_epochs = 25
    best_val_loss = float("inf")
    best_state = None
    patience_counter = 0
    max_patience = 7

    logger.info(f"Training CNN {setup_type}/{bar_size}: {n_train} train, {n_val} val, {n_test} test (device={device})")

    for epoch in range(num_epochs):
        # Train
        model.train()
        train_loss = 0
        for X_batch, y_pat, y_win in train_loader:
            X_batch = X_batch.to(device)
            y_pat = y_pat.to(device)
            y_win = y_win.to(device)

            optimizer.zero_grad()
            pat_logits, win_pred = model(X_batch)

            loss_pat = pattern_criterion(pat_logits, y_pat)
            loss_win = win_criterion(win_pred, y_win)
            loss = loss_pat + 0.5 * loss_win  # Weight pattern loss higher

            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validate
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for X_batch, y_pat, y_win in val_loader:
                X_batch = X_batch.to(device)
                y_pat = y_pat.to(device)
                y_win = y_win.to(device)
                pat_logits, win_pred = model(X_batch)
                loss = pattern_criterion(pat_logits, y_pat) + 0.5 * win_criterion(win_pred, y_win)
                val_loss += loss.item()

        avg_train = train_loss / max(len(train_loader), 1)
        avg_val = val_loss / max(len(val_loader), 1)
        scheduler.step(avg_val)

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if epoch % 5 == 0 or patience_counter >= max_patience:
            logger.info(f"  Epoch {epoch + 1}/{num_epochs}: train_loss={avg_train:.4f} val_loss={avg_val:.4f} (patience={patience_counter})")

        if patience_counter >= max_patience:
            logger.info(f"  Early stopping at epoch {epoch + 1}")
            break

    # Load best model
    if best_state:
        model.load_state_dict(best_state)
        model.to(device)

    # Test evaluation
    model.eval()
    correct_pattern = 0
    total = 0
    all_win_preds = []
    all_win_true = []

    with torch.no_grad():
        for X_batch, y_pat, y_win in test_loader:
            X_batch = X_batch.to(device)
            y_pat = y_pat.to(device)
            y_win = y_win.to(device)

            pat_logits, win_pred = model(X_batch)
            pred_classes = pat_logits.argmax(dim=1)
            correct_pattern += (pred_classes == y_pat).sum().item()
            total += len(y_pat)

            all_win_preds.extend(win_pred.cpu().numpy().tolist())
            all_win_true.extend(y_win.cpu().numpy().tolist())

    accuracy = correct_pattern / max(total, 1)

    # Win prediction AUC
    win_auc = 0.5
    try:
        from sklearn.metrics import roc_auc_score
        if len(set(all_win_true)) > 1:
            win_auc = roc_auc_score(all_win_true, all_win_preds)
    except Exception:
        pass

    metrics = {
        "accuracy": round(accuracy, 4),
        "win_auc": round(win_auc, 4),
        "test_samples": total,
        "train_samples": n_train,
        "val_samples": n_val,
        "total_samples": n,
        "best_val_loss": round(best_val_loss, 4),
        "win_rate_in_data": round(sum(all_win_true) / max(len(all_win_true), 1), 4),
    }

    logger.info(f"CNN {setup_type}/{bar_size}: accuracy={accuracy:.3f}, win_auc={win_auc:.3f}")

    # Save if meets threshold
    if accuracy >= MIN_ACCURACY_THRESHOLD:
        # Check if new model beats existing
        existing_model, existing_meta = load_model_from_db(db, setup_type, bar_size)
        existing_acc = existing_meta.get("metrics", {}).get("accuracy", 0) if existing_meta else 0

        if accuracy >= existing_acc:
            model_name = save_model_to_db(db, model, setup_type, bar_size, metrics)
            metrics["saved"] = True
            metrics["model_name"] = model_name
            if existing_acc > 0:
                logger.info(f"  Model promoted: {accuracy:.3f} > {existing_acc:.3f} (old)")
        else:
            metrics["saved"] = False
            metrics["reason"] = f"New acc {accuracy:.3f} < existing {existing_acc:.3f}"
            logger.info(f"  Model NOT promoted: {accuracy:.3f} < {existing_acc:.3f}")
    else:
        metrics["saved"] = False
        metrics["reason"] = f"Accuracy {accuracy:.3f} below threshold {MIN_ACCURACY_THRESHOLD}"
        logger.info(f"  Model NOT saved: accuracy {accuracy:.3f} < {MIN_ACCURACY_THRESHOLD}")

    return {
        "success": True,
        "setup_type": setup_type,
        "bar_size": bar_size,
        "metrics": metrics,
    }
