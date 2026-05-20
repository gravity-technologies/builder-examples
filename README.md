# GRVT Builder Examples

Example scripts demonstrating integration with GRVT's Builder Codes system and Trading API, available in **Python** and **TypeScript**.

## Overview

This repository contains example scripts for:
- **Builder Authorization** - Generate API keys through EIP-712 signature authorization
- **Wallet Login** - Authenticate using an EIP-712 wallet signature (no API key required)
- **Order Creation** - Create and submit authenticated orders to the GRVT Trading API

These examples demonstrate the complete flow from user authorization to order execution, following GRVT's official API documentation.

## Repository Structure

```
builder-examples/
├── python/                          # Python implementation
│   ├── grvt_common.py              # Shared utilities
│   ├── wallet_login.py             # EIP-712 wallet login
│   ├── authorize.py                # Builder authorization & API key generation
│   ├── grvt_create_order_api.py    # Order creation with API key auth
│   └── create_order_data.json      # Sample order data
├── typescript/                      # TypeScript implementation
│   ├── src/
│   │   ├── grvt_common.ts          # Shared utilities
│   │   ├── wallet_login.ts         # EIP-712 wallet login
│   │   ├── authorize.ts            # Builder authorization & API key generation
│   │   └── grvt_create_order_api.ts # Order creation with API key auth
│   ├── create_order_data.json      # Sample order data
│   ├── package.json
│   └── tsconfig.json
├── docs/
│   ├── AUTHORIZE_README.md          # Detailed authorize documentation
│   ├── WALLET_LOGIN_README.md       # Detailed wallet login documentation
│   └── CREATE_ORDER_README.md       # Detailed order creation documentation
└── README.md                        # This file
```

## Quick Start

### Python

#### Prerequisites

- Python 3.7+
- Install required packages:

```bash
pip install requests eth-account
```

#### 1. Wallet Login

```bash
cd python
python wallet_login.py \
  --env testnet \
  --wallet-privkey 0xYOUR_USER_WALLET_PRIVATE_KEY \
  --no-verify
```

#### 2. Generate an API Key

```bash
python authorize.py \
  --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USER_WALLET_PRIVATE_KEY \
  --main-account-id 0xFUNDING_ACCOUNT_ADDRESS \
  --builder-account-id 0xBUILDER_ACCOUNT_ADDRESS
```

#### 3. Create an Order

```bash
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json
```

---

### TypeScript

#### Prerequisites

- Node.js 18+
- Install dependencies:

```bash
cd typescript
npm install
```

#### 1. Wallet Login

```bash
npx tsx src/wallet_login.ts \
  --env testnet \
  --wallet-privkey 0xYOUR_USER_WALLET_PRIVATE_KEY \
  --no-verify
```

#### 2. Generate an API Key

```bash
npx tsx src/authorize.ts \
  --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USER_WALLET_PRIVATE_KEY \
  --main-account-id 0xFUNDING_ACCOUNT_ADDRESS \
  --builder-account-id 0xBUILDER_ACCOUNT_ADDRESS
```

#### 3. Create an Order

```bash
npx tsx src/grvt_create_order_api.ts \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json
```

## Scripts

### 1. Wallet Login

**Purpose:** Authenticate with the user's main wallet using EIP-712. Returns a session cookie, off-chain account ID, and `funding_account_address` (used as `--main-account-id` in the authorize step).

| Python | TypeScript |
|--------|------------|
| `python/wallet_login.py` | `typescript/src/wallet_login.ts` |

**Key Features:**
- EIP-712 `WalletLogin` signature (`WalletLogin(address signer, uint32 nonce, int64 expiration)`)
- Returns `funding_account_address` — use as `main_account_id` in the authorize step
- Replay prevention via server-side nonce consumption
- Short-lived signatures (max 5 minutes, server-enforced)

**Full Documentation:** [docs/WALLET_LOGIN_README.md](docs/WALLET_LOGIN_README.md)

---

### 2. Builder Authorization

**Purpose:** Authorize a builder to act on behalf of a user's account.

| Python | TypeScript |
|--------|------------|
| `python/authorize.py` | `typescript/src/authorize.ts` |

**Key Features:**
- Two authorization paths: with API key (`--authorize`) or without (`--authorize-only`)
- Auto-generates builder API signer keypair if not provided
- Multi-environment support (staging, testnet, prod)

**Full Documentation:** [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md)

---

### 3. Order Creation

**Purpose:** Create and submit signed orders to the GRVT Trading API using API key authentication.

| Python | TypeScript |
|--------|------------|
| `python/grvt_create_order_api.py` | `typescript/src/grvt_create_order_api.ts` |

**Key Features:**
- API key authentication flow
- EIP-712 order signing
- Multi-leg order support
- Automatic expiration and nonce updates
- Instrument metadata fetching

**Full Documentation:** [docs/CREATE_ORDER_README.md](docs/CREATE_ORDER_README.md)

## Environments

All scripts support multiple GRVT environments:

| Environment | Chain ID | Edge API                       | Trading API                      | Market Data API                       |
|-------------|----------|--------------------------------|----------------------------------|---------------------------------------|
| **staging** | 327      | edge.staging.gravitymarkets.io | trades.staging.gravitymarkets.io | market-data.staging.gravitymarkets.io |
| **testnet** | 326      | edge.testnet.grvt.io           | trades.testnet.grvt.io           | market-data.testnet.grvt.io           |
| **prod**    | 325      | edge.grvt.io                   | trades.grvt.io                   | market-data.grvt.io                   |

Use `--env` flag to select the environment (default: `testnet`).

## Complete Integration Flow

```
1. wallet_login  →  funding_account_address  (= main_account_id)
2. authorize     →  api_key                  (builder authorised for user)
3. trade         →  orders submitted on behalf of user
```

### Step 1: Login with user's wallet

**Python:**
```bash
cd python
python wallet_login.py --env testnet \
  --wallet-privkey "$USER_WALLET_PRIVKEY" --no-verify
```

**TypeScript:**
```bash
cd typescript
npx tsx src/wallet_login.ts --env testnet \
  --wallet-privkey "$USER_WALLET_PRIVKEY" --no-verify
```

### Step 2: Authorize builder

**Python:**
```bash
python authorize.py --env testnet --authorize \
  --user-privkey "$USER_WALLET_PRIVKEY" \
  --main-account-id "$MAIN_ACCOUNT" \
  --builder-account-id "$BUILDER_ACCOUNT"
```

**TypeScript:**
```bash
npx tsx src/authorize.ts --env testnet --authorize \
  --user-privkey "$USER_WALLET_PRIVKEY" \
  --main-account-id "$MAIN_ACCOUNT" \
  --builder-account-id "$BUILDER_ACCOUNT"
```

### Step 3: Create orders

**Python:**
```bash
python grvt_create_order_api.py --env testnet \
  --api-key "$GRVT_API_KEY" \
  --private-key "$ORDER_SIGNING_KEY" \
  --order-file create_order_data.json \
  --update-expiration --expiration-hours 24
```

**TypeScript:**
```bash
npx tsx src/grvt_create_order_api.ts --env testnet \
  --api-key "$GRVT_API_KEY" \
  --private-key "$ORDER_SIGNING_KEY" \
  --order-file create_order_data.json \
  --update-expiration --expiration-hours 24
```

## Technology Stack

| | Python | TypeScript |
|---|--------|------------|
| **HTTP Client** | `requests` | `fetch` (built-in) |
| **Ethereum/EIP-712** | `eth-account` | `ethers` v6 |
| **CLI Parsing** | `argparse` (built-in) | `commander` |
| **Runtime** | Python 3.7+ | Node.js 18+ / `tsx` |

## Security Best Practices

1. **Never commit private keys or API keys to version control**
2. **Use environment variables** for sensitive data
3. **Test on testnet first** before using production
4. **Rotate API keys regularly** (keys can expire up to 30 days)
5. **Use secure key management** systems in production
6. **Validate order parameters** before submission
7. **Monitor your orders** and positions after submission

## API Documentation References

- **Builder Codes Integration:** https://api-docs.grvt.io/builder_codes/
- **Authentication:** https://api-docs.grvt.io/auth/
- **Trading API:** https://api-docs.grvt.io/trading_api/
- **Market Data API:** https://api-docs.grvt.io/market_data/

## Troubleshooting

### Common Issues

#### "Missing required args for --authorize"
- Ensure all required arguments are provided when using `--authorize`
- See [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md)

#### "Could not find gravity cookie"
- API key may be invalid or expired
- Check you're using the correct environment

#### "Instrument not found"
- Verify instrument name is correct and case-sensitive
- Check instrument is active in your environment

#### "Signature verification failed"
- Ensure private key matches the signer address
- Check expiration timestamp is in the future
- Verify nonce is unique

### Getting Help

1. Check the detailed documentation for each script in the `docs/` folder
2. Review GRVT's official API documentation
3. Verify your environment configuration and credentials
4. Test with smaller values on testnet first

## Project Dependencies

### Python
```bash
pip install requests eth-account
```

### TypeScript
```bash
cd typescript && npm install
```

## License

These examples are provided as-is for testing and integration purposes with GRVT's Builder Codes system.

## Additional Resources

- **GRVT Website:** https://grvt.io/
- **API Documentation:** https://api-docs.grvt.io/
- **Discord Community:** [Join GRVT Discord](https://discord.gg/grvt)
