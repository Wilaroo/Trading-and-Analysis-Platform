# Deploy to DGX Spark & Run First XGBoost Training
## Step-by-Step Guide

---

## STEP 1: Push Code from Emergent to GitHub

In the Emergent chat interface:
1. Click the **"Save to GitHub"** button in the chat input area
2. This pushes your latest code (Phases 1-4.5) to your GitHub repo

---

## STEP 2: Pull Code on DGX Spark

SSH into your Spark:
```bash
ssh spark-1a60@192.168.50.2
```

Navigate to your project and pull:
```bash
cd ~/Trading-and-Analysis-Platform
git pull origin main
```

---

## STEP 3: Activate Virtual Environment & Install Dependencies

```bash
source ~/venv/bin/activate
```

Install updated Python packages (XGBoost is the key new one):
```bash
cd ~/Trading-and-Analysis-Platform/backend
pip install -r requirements.txt
```

Verify XGBoost installed with GPU support:
```bash
python -c "import xgboost as xgb; print(f'XGBoost {xgb.__version__}'); dtrain = xgb.DMatrix([[1,2,3]], label=[1]); m = xgb.train({'tree_method':'hist','device':'cuda','objective':'binary:logistic'}, dtrain, 1); print('GPU OK')"
```

You should see: `XGBoost 3.2.0` and `GPU OK`

---

## STEP 4: Verify .env Files

Your backend `.env` should already be set from the April 7 session. Verify it:
```bash
cat ~/Trading-and-Analysis-Platform/backend/.env
```

Confirm these key values match:
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand
IB_HOST=192.168.50.1
IB_PORT=4002
```

Frontend `.env`:
```bash
cat ~/Trading-and-Analysis-Platform/frontend/.env
```

Should contain:
```
REACT_APP_BACKEND_URL=http://192.168.50.2:8001
```

> If your .env files got overwritten by the git pull, restore them from the template at `documents/DGX_SPARK_ENV_TEMPLATE.md`

---

## STEP 5: Verify MongoDB is Running

```bash
docker ps | grep mongo
```

Should show the MongoDB container running on port 27017. If not:
```bash
docker start <your-mongo-container-name>
```

Quick data check (confirm your 178M+ bars are intact):
```bash
python -c "
from pymongo import MongoClient
db = MongoClient('mongodb://localhost:27017')['tradecommand']
count = db['ib_historical_data'].estimated_document_count()
print(f'ib_historical_data: {count:,} bars')
print(f'Symbols with data: {len(db[\"ib_historical_data\"].distinct(\"symbol\", {}))}' if count < 1000000 else 'Skipping distinct (too many rows)')
"
```

Alternative count check that won't timeout:
```bash
python -c "
from pymongo import MongoClient
db = MongoClient('mongodb://localhost:27017')['tradecommand']
result = list(db['ib_historical_data'].aggregate([{'\$group': {'_id': None, 'count': {'\$sum': 1}}}], allowDiskUse=True))
print(f'Total bars: {result[0][\"count\"]:,}' if result else 'No data found')
"
```

---

## STEP 6: Start the Backend

Option A — nohup (quick, manual):
```bash
cd ~/Trading-and-Analysis-Platform/backend
source ~/venv/bin/activate
nohup python server.py > ~/backend.log 2>&1 &
echo "Backend PID: $!"
```

Option B — systemd (persistent, auto-restarts):
```bash
# If you haven't set up systemd yet, run the commands from:
# documents/SPARK_SYSTEMD_SETUP.md
sudo systemctl start tradecommand-backend
```

Verify backend is running:
```bash
curl -s http://192.168.50.2:8001/api/health | python -m json.tool
```

---

## STEP 7: Start the Worker Process

The worker is what actually runs the training jobs. It MUST be running separately from the backend:

```bash
cd ~/Trading-and-Analysis-Platform/backend
source ~/venv/bin/activate
nohup python worker.py > ~/worker.log 2>&1 &
echo "Worker PID: $!"
```

Verify worker started:
```bash
tail -5 ~/worker.log
```

Should show something like: `[WORKER] INFO: Worker started, polling for jobs...`

---

## STEP 8: Start Frontend (Optional — for UI access)

```bash
cd ~/Trading-and-Analysis-Platform/frontend
nohup yarn start > ~/frontend.log 2>&1 &
```

Access at: `http://192.168.50.2:3000`

---

## STEP 9: Trigger Full Universe XGBoost Training

### Option A: Via UI
1. Open `http://192.168.50.2:3000` in browser
2. Go to the AI Training panel (NIA section)
3. Click **"Full Universe"** button
4. Confirm the dialog
5. The job gets queued and the worker picks it up

### Option B: Via API (recommended for first run — you can see exact responses)
```bash
# Train all timeframes across full symbol universe
curl -X POST http://192.168.50.2:8001/api/ai/timeseries/train-full-universe-all \
  -H "Content-Type: application/json" \
  -d '{"symbol_batch_size": 500, "max_bars_per_symbol": 5000}'
```

This returns a `job_id`. Monitor progress:
```bash
# Replace JOB_ID with the actual job_id returned above
curl -s http://192.168.50.2:8001/api/jobs/JOB_ID | python -m json.tool
```

Or monitor via worker logs:
```bash
tail -f ~/worker.log
```

---

## STEP 10: Monitor Training Progress

### Watch the worker log (most detailed):
```bash
tail -f ~/worker.log
```

### Check GPU utilization:
```bash
# On the Spark
nvidia-smi
# Or continuous monitoring:
watch -n 2 nvidia-smi
```

You should see GPU memory usage and utilization climb when XGBoost is training.

### Check training status via API:
```bash
curl -s http://192.168.50.2:8001/api/ai/timeseries/training-status | python -m json.tool
```

### Check feature cache filling:
```bash
python -c "
from pymongo import MongoClient
db = MongoClient('mongodb://localhost:27017')['tradecommand']
cached = db['feature_cache'].estimated_document_count()
models = db['timeseries_models'].estimated_document_count()
print(f'Feature cache entries: {cached}')
print(f'Trained models: {models}')
"
```

---

## Expected Timeline

| Phase | Est. Time | What Happens |
|-------|-----------|-------------|
| Feature extraction + caching | 2-4 hours | Reads 178M bars, computes features per symbol/timeframe, caches in MongoDB |
| XGBoost GPU training | 4-6 hours | Trains models on cached features using Blackwell GPU |
| **Total first run** | **~8-12 hours** | Subsequent runs much faster (features cached) |

---

## Troubleshooting

### "ML libraries not installed" error
```bash
source ~/venv/bin/activate
pip install xgboost==3.2.0
```

### Worker not picking up jobs
```bash
# Check if worker is running
ps aux | grep worker.py

# Check worker logs for errors
tail -50 ~/worker.log
```

### GPU not detected by XGBoost
```bash
python -c "
import xgboost as xgb
import numpy as np
X = np.random.randn(1000, 10).astype(np.float32)
y = np.random.randint(0, 2, 1000)
dtrain = xgb.DMatrix(X, label=y)
params = {'tree_method': 'hist', 'device': 'cuda', 'objective': 'binary:logistic'}
try:
    model = xgb.train(params, dtrain, num_boost_round=5)
    print('GPU training: OK')
except Exception as e:
    print(f'GPU training FAILED: {e}')
    print('Falling back to CPU (will be slower)')
"
```

### Backend won't start
```bash
cd ~/Trading-and-Analysis-Platform/backend
source ~/venv/bin/activate
python -c "import server" 2>&1 | head -20
```

### MongoDB connection issues
```bash
docker ps | grep mongo
docker logs <mongo-container> --tail 20
```

---

## After Training Completes

Once the full training run finishes, come back here and let me know:
1. How long it took
2. Any errors in `worker.log`
3. How many models were created (check via the feature cache command above)

Then we'll move to **Phase 5: Deep Learning Models** (TFT, CNN-LSTM, FinBERT, VAE, RL Position Sizer).
