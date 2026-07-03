# Autonomous Trading Bridge AI

Welcome to your masterpiece. This repository connects the raw intelligence of **Open Jarvis** and **RuFlow** to the live crypto markets, driven by a mathematically proven **Hidden Markov Model** volatility regime engine.

## 🚀 Architecture Overview
- **Core Engine:** Analyzes Realized Volatility and Garman-Klass volatility to categorize the market into pure regimes (Calm, Choppy, Turbulent).
- **Strategy Layer:** Maximize exposure when waters are calm. Scale back or retreat when turbulence spikes.
- **Risk Manager:** An absolute defense-in-depth circuit breaker. Watches actual P&L, cutting positions by 50% on minor drawdowns, and issuing hard halts on major drawdowns.
- **Broker (CCXT):** Executes allocations directly on Binance, Bybit, KuCoin, etc.
- **Dashboard:** A beautiful FastApi + Tailwind glassmorphism UI to watch your bot work.

---

## 🔑 How to Connect Your Real Money (Bybit Example)

**DO NOT DEPOSIT MONEY INTO THIS CODE.** The code uses an API key to securely trade the funds already sitting in your Bybit account.

### Step 1: Prepare Your Bybit Account
1. Ensure your Bybit account has completed **Identity Verification (KYC)**. Bybit requires at least Basic Verification to trade and use API keys effectively. Unverified accounts may face restrictions or api failures.
2. Deposit USDT into your **Unified Trading Account** or Spot/Derivatives wallet.

### Step 2: Generate the API Key
1. Go to Bybit API Management -> Create New Key.
2. Select **"System-Generated API Keys"**.
3. Set API Key Usage to **"API Transaction"**.
4. Name it something like `API BRIDGE`.
5. Set Permissions to **"Read-Write"**.
6. **CRITICAL:** Check the boxes for `Orders`, `Positions`, and `Trade`.
7. **CRITICAL:** Ensure `Withdrawal` and `Transfer` are **UNCHECKED**. The bot must never have permission to move your money out of Bybit.
8. Submit and copy your **API Key** and **API Secret**.

### Step 3: Configure the Bot
1. In the root of `/trading-bridge`, create a file exactly named `.env`
2. Paste your keys inside like this:
```env
BYBIT_API_KEY="paste_your_key_here"
BYBIT_API_SECRET="paste_your_secret_here"
```

### Step 4: Go Live
1. Open `main.py` and locate the `CryptoBrokerClient` initialization.
2. Change `paper_trading=True` to `paper_trading=False`.
3. When you run the script, the terminal will scream at you. You MUST type exactly `YES I UNDERSTAND THE RISKS` to authorize the bot to touch your real funds.

---

## 🖥️ Running the Dashboard
To watch the bot in action, run the web server:
```bash
python -m monitoring.server
```
Then open your browser to `http://localhost:8000`.
