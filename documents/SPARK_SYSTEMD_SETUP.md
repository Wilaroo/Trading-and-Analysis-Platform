# DGX Spark Systemd Services Setup
# Run these commands ONCE on the Spark to enable auto-start on boot

## Step 1: Create service files (run as root via sudo)

### Backend Service
```bash
sudo tee /etc/systemd/system/tradecommand-backend.service << 'EOF'
[Unit]
Description=TradeCommand Backend API
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=spark-1a60
WorkingDirectory=/home/spark-1a60/Trading-and-Analysis-Platform/backend
Environment=PATH=/home/spark-1a60/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/spark-1a60/venv/bin/python server.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

### Frontend Service
```bash
sudo tee /etc/systemd/system/tradecommand-frontend.service << 'EOF'
[Unit]
Description=TradeCommand Frontend React
After=network.target tradecommand-backend.service

[Service]
Type=simple
User=spark-1a60
WorkingDirectory=/home/spark-1a60/Trading-and-Analysis-Platform/frontend
ExecStart=/usr/bin/yarn start
Restart=on-failure
RestartSec=10
Environment=PORT=3000
Environment=BROWSER=none

[Install]
WantedBy=multi-user.target
EOF
```

### Worker Service
```bash
sudo tee /etc/systemd/system/tradecommand-worker.service << 'EOF'
[Unit]
Description=TradeCommand Background Worker
After=network.target tradecommand-backend.service
Requires=tradecommand-backend.service

[Service]
Type=simple
User=spark-1a60
WorkingDirectory=/home/spark-1a60/Trading-and-Analysis-Platform/backend
Environment=PATH=/home/spark-1a60/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/spark-1a60/venv/bin/python worker.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

## Step 2: Enable and start all services
```bash
sudo systemctl daemon-reload
sudo systemctl enable tradecommand-backend tradecommand-frontend tradecommand-worker
sudo systemctl start tradecommand-backend tradecommand-frontend tradecommand-worker
```

## Step 3: Check status
```bash
sudo systemctl status tradecommand-backend tradecommand-frontend tradecommand-worker
```

## Useful commands
```bash
# View logs
sudo journalctl -u tradecommand-backend -f
sudo journalctl -u tradecommand-frontend -f
sudo journalctl -u tradecommand-worker -f

# Restart a service
sudo systemctl restart tradecommand-backend

# Stop all
sudo systemctl stop tradecommand-backend tradecommand-frontend tradecommand-worker
```
