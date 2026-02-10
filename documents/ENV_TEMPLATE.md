# Backend Environment Configuration
# Copy this to backend/.env on your local machine

# Database
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand

# AI - Emergent (for deep analysis)
EMERGENT_LLM_KEY=sk-emergent-eB546De49960147361

# AI - Ollama (for free local AI)
# Cloud mode: Use ngrok URL
OLLAMA_URL=https://pseudoaccidentally-linty-addie.ngrok-free.dev
# Local mode: Use direct localhost
# OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3:8b

# Market Data - Finnhub
FINNHUB_API_KEY=d5p596hr01qs8sp44dn0d5p596hr01qs8sp44dng

# Market Data - Twelve Data (demo key)
TWELVEDATA_API_KEY=demo

# Trading - Alpaca (Paper)
ALPACA_API_KEY=PK6YVB2AYAPO35BFSB7GL77VQB
ALPACA_SECRET_KEY=9Z36ZEEpury2CpteeSPbVhmdLpoo3gqcwEJmxEG61BCr
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Trading - Interactive Brokers
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1
IB_ACCOUNT_ID=esw100000
IB_FLEX_TOKEN=246862982700643739395
IB_FLEX_QUERY_ID=944620

# Optional - Perplexity (not currently used)
PERPLEXITY_API_KEY=
PERPLEXITY_MODEL=sonar
