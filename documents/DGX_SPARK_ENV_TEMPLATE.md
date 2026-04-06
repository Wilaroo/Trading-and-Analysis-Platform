# DGX Spark Environment Configuration
# Network: Spark=192.168.50.2, Windows PC=192.168.50.1 (10GbE direct link)

## Backend .env (~/Trading-and-Analysis-Platform/backend/.env)
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand
EMERGENT_LLM_KEY=sk-emergent-eB546De49960147361
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3:8b
FINNHUB_API_KEY=d5p596hr01qs8sp44dn0d5p596hr01qs8sp44dng
TWELVEDATA_API_KEY=demo
ALPACA_API_KEY=PK6YVB2AYAPO35BFSB7GL77VQB
ALPACA_SECRET_KEY=9Z36ZEEpury2CpteeSPbVhmdLpoo3gqcwEJmxEG61BCr
ALPACA_BASE_URL=https://paper-api.alpaca.markets
IB_HOST=192.168.50.1
IB_PORT=4002
IB_CLIENT_ID=1
IB_ACCOUNT_ID=esw100000
IB_FLEX_TOKEN=246862982700643739395
IB_FLEX_QUERY_ID=944620
REACT_APP_BACKEND_URL=http://192.168.50.2:8001
APP_URL=http://192.168.50.2:8001
PERPLEXITY_API_KEY=
PERPLEXITY_MODEL=sonar
```

## Frontend .env (~/Trading-and-Analysis-Platform/frontend/.env)
```
REACT_APP_BACKEND_URL=http://192.168.50.2:8001
```

## IB Data Pusher (Windows PC)
```
python ib_data_pusher.py --cloud-url http://192.168.50.2:8001 --ib-host 127.0.0.1 --ib-port 4002
```
