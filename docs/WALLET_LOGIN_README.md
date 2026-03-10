# GRVT Wallet Login

Scripts that authenticate to GRVT using an EIP-712 wallet signature (`POST /auth/wallet/login`). Available in **Python** and **TypeScript**.

| Python                   | TypeScript                       |
|--------------------------|----------------------------------|
| `python/wallet_login.py` | `typescript/src/wallet_login.ts` |

## Overview

These scripts demonstrate EIP-712-based authentication for the main signing wallet.
Unlike API-key login (which requires a pre-minted key), wallet login lets any registered
main-wallet holder authenticate by signing a short-lived message directly. It returns:

- **Session cookie** (`gravity=...`) — for authenticated Trading API calls
- **Off-chain account ID** (`X-Grvt-Account-Id`) — required header for API requests
- **`funding_account_address`** — the user's on-chain main account address; pass this as `--main-account-id` in the authorize script

### How it works

1. Client builds a `WalletLogin` EIP-712 struct with their wallet address, a random nonce, and an expiration timestamp.
2. Client signs the struct with the wallet private key (`eth_signTypedData_v4`).
3. Client POSTs `{ address, signature: { signer, v, r, s, nonce, expiration, chain_id } }` to `/auth/wallet/login`.
4. Server validates expiration, verifies the EIP-712 signature, atomically marks the nonce as used (replay prevention via Redis), and issues a session cookie.
5. Server returns `{"funding_account_address": "0x..."}` in the response body — the user's main account (chain account address).
6. The script extracts the `gravity` cookie, `X-Grvt-Account-Id` header, and `funding_account_address`.

### Full integration flow

Wallet login is the **first step** in the builder integration. Use the `funding_account_address` from the login response as `main_account_id` in subsequent steps:

```
1. wallet_login  →  funding_account_address  (= main_account_id)
2. authorize     →  api_key                  (builder authorised for user)
3. trade         →  orders submitted on behalf of user
```

| Step                        | Script                                                   | Key output                                            |
|-----------------------------|----------------------------------------------------------|-------------------------------------------------------|
| 1. Login with user's wallet | `python/wallet_login.py` / `typescript/src/wallet_login.ts`                    | `funding_account_address` → use as `main_account_id`  |
| 2. Authorize builder        | `python/authorize.py --authorize` / `typescript/src/authorize.ts --authorize`  | `api_key`                                             |
| 3. Create orders            | `python/grvt_create_order_api.py` / `typescript/src/grvt_create_order_api.ts` | order confirmation                                    |

### EIP-712 structure

| Field        | Value                                                       |
|--------------|-------------------------------------------------------------|
| Domain name  | `GRVT Exchange`                                             |
| Version      | `0`                                                         |
| Chain ID     | Environment-specific (see Environments below)               |
| Primary type | `WalletLogin`                                               |
| Type string  | `WalletLogin(address signer,uint32 nonce,int64 expiration)` |

**Message fields:**

| Field        | Type      | Description                                        |
|--------------|-----------|----------------------------------------------------|
| `signer`     | `address` | The wallet address signing the message             |
| `nonce`      | `uint32`  | Random client-chosen value (replay prevention)     |
| `expiration` | `int64`   | Unix timestamp in **nanoseconds**, max now + 5 min |
### Server-enforced constraints

| Rule                     | Detail                                                                                  |
|--------------------------|-----------------------------------------------------------------------------------------|
| Expiration > now         | Expired signatures are rejected with `401 Unauthorized`                                 |
| Expiration ≤ now + 5 min | Longer windows are rejected with `400 Bad Request`                                      |
| Unique nonce             | Replayed `(address, nonce)` pairs are rejected with `401` within the signature lifetime |
| `0x` prefix required     | Address without `0x` prefix returns `400 Bad Request`                                   |
| v ∈ {27, 28}             | Any other value returns `400 Bad Request`                                               |

## Prerequisites

**Python:**
- Python 3.7+
```bash
pip install requests eth-account
```

**TypeScript:**
- Node.js 18+
```bash
cd typescript && npm install
```

## Environments

| Environment | Chain ID | Edge API                         |
|-------------|----------|----------------------------------|
| `dev`       | 327      | edge.dev.gravitymarkets.io       |
| `staging`   | 327      | edge.staging.gravitymarkets.io   |
| `testnet`   | 326      | edge.testnet.grvt.io (default)   |
| `prod`      | 325      | edge.grvt.io                     |

## Usage

### Basic login (derives address from private key)

**Python** (from `python/` directory):
```bash
cd python
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY
```

**TypeScript** (from `typescript/` directory):
```bash
cd typescript
npx tsx src/wallet_login.ts --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY
```

### Login without verifying session

**Python:**
```bash
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
  --no-verify
```

**TypeScript:**
```bash
npx tsx src/wallet_login.ts --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
  --no-verify
```

### Using environment variables

```bash
export WALLET_PRIVKEY="0x..."

# Python (from python/ directory)
python wallet_login.py --env testnet --wallet-privkey "$WALLET_PRIVKEY"

# TypeScript (from typescript/ directory)
npx tsx src/wallet_login.ts --env testnet --wallet-privkey "$WALLET_PRIVKEY"
```

## Command Line Arguments

| Argument            | Description                                                 | Required | Default              |
|---------------------|-------------------------------------------------------------|----------|----------------------|
| `--env`             | Target environment (dev/staging/testnet/prod)               | No       | `testnet`            |
| `--wallet-privkey`  | Main wallet private key for EIP-712 signing                 | **Yes**  | None                 |
| `--wallet-address`  | Wallet address (derived from `--wallet-privkey` if omitted) | No       | Derived from privkey |
| `--expiration-secs` | Signature lifetime in seconds (max 300 — server enforced)   | No       | `240` (4 minutes)    |
| `--no-verify`       | Skip the `get_sub_accounts` verification step after login   | No       | False                |

## How It Works

### Step 1: Build the EIP-712 payload

The script constructs a `WalletLogin` typed-data structure:

```
{
    "domain": {
        "name": "GRVT Exchange",
        "version": "0",
        "chainId": 326          # testnet; varies by environment
    },
    "primaryType": "WalletLogin",
    "types": {
        "EIP712Domain": [
            {"name": "name",    "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"}
        ],
        "WalletLogin": [
            {"name": "signer",     "type": "address"},
            {"name": "nonce",      "type": "uint32"},
            {"name": "expiration", "type": "int64"}
        ]
    },
    "message": {
        "signer":     "0xYOUR_WALLET_ADDRESS",
        "nonce":      2847362918,            # random uint32
        "expiration": 1700000240000000000    # now + 4 min, in nanoseconds
    }
}
```

### Step 2: Sign

The struct is signed with `eth_signTypedData_v4` (EIP-712), producing `v` (27 or 28), `r` (hex), and `s` (hex).

### Step 3: POST to /auth/wallet/login

```json
{
  "address": "0xYOUR_WALLET_ADDRESS",
  "signature": {
    "signer": "0xYOUR_WALLET_ADDRESS",
    "v": 28,
    "r": "0x...",
    "s": "0x...",
    "nonce": 2847362918,
    "expiration": "1700000240000000000",
    "chain_id": "326"
  }
}
```

`chain_id` is optional — the server uses its configured GRVT chain ID when omitted or set to `"0"`.

### Step 4: Extract session and funding account address

On `200 OK` the server sets a `gravity` session cookie and `X-Grvt-Account-Id` header,
and returns the following JSON body:

```json
{
  "funding_account_address": "0xYOUR_MAIN_ACCOUNT_ADDRESS"
}
```

`funding_account_address` is the user's **main account** (chain account address) — pass it
as `--main-account-id` when calling the authorize script. The session cookie and header are used
for all subsequent authenticated API calls:

```
Cookie: gravity=...
X-Grvt-Account-Id: 0x...
```

### Step 5 (optional): Verify session

The script calls `POST /full/v1/get_sub_accounts` using the session cookie to confirm the session is valid.

## Output

```
Signing as: 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
Nonce:      2847362918
Expiration: 1700000240000000000 ns (~240s from now)

== Wallet Login ==
URL: POST https://edge.testnet.grvt.io/auth/wallet/login
Status: 200
X-Grvt-Account-Id: 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
Set-Cookie: gravity=...; Path=/; HttpOnly; Secure
JSON:
{
  "funding_account_address": "0xabc123..."
}

Session gravity cookie:   gravity=...
X-Grvt-Account-Id:        0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266
Funding account address:  0xabc123...
  (use as --main-account-id in the authorize script)

== Get Sub Accounts ==
URL: POST https://trades.testnet.grvt.io/full/v1/get_sub_accounts
Status: 200
...

Sub accounts: {...}

✅ Wallet login and session verification complete.
```

## Security Considerations

⚠️ **Security Best Practices:**

- **Never commit private keys to version control.** Use environment variables.
- The signature is valid for at most **5 minutes** (server cap). The session itself (30 days) is separate.
- **Replay protection:** Each `(address, nonce)` pair can only be used once within its lifetime. Always use a fresh random nonce.
- The private key is only used locally to sign the EIP-712 message — it is never sent over the network.

## Script Functions

| Function              | Python                   | TypeScript             |
|-----------------------|--------------------------|------------------------|
| Build EIP-712 payload | `build_eip712_payload()` | `buildEip712Payload()` |
| Sign typed data       | `sign_eip712()`          | `signEip712()`         |
| Wallet login          | `wallet_login()`         | `walletLogin()`        |
| Verify session        | `get_sub_accounts()`     | `getSubAccounts()`     |
| Normalize addresses   | `ensure_0x()`            | `ensure0x()`           |
| Parse cookie          | `parse_gravity_cookie()` | `parseGravityCookie()` |
| Debug HTTP            | `print_http()`           | `printHttp()`          |

## Troubleshooting

### `signature expired` (401)

The signature's expiration timestamp is in the past. This can happen if there is significant clock skew. Reduce `--expiration-secs` or sync your system clock.

### `signature expiration exceeds maximum allowed window` (400)

`--expiration-secs` exceeds 300 (5 minutes). The server cap is strict — reduce the value.

### `invalid signature` (401)

- Verify `--wallet-privkey` corresponds to `--wallet-address` (or omit `--wallet-address` to let the script derive it).
- Ensure the correct `--env` is selected (chain ID is part of the EIP-712 domain).

### `wallet address not registered` (401)

The wallet address is not registered on GRVT. Ensure the address is the main signing wallet of an existing GRVT account.

### `signature already used` (401)

The `(address, nonce)` pair was already consumed. Re-run the script — a new random nonce is generated on each run.

### Missing `encode_typed_data`

```
RuntimeError: eth-account is missing encode_typed_data/encode_structured_data
```

Update eth-account:

```bash
pip install --upgrade eth-account
```

## Exit Codes

| Code     | Meaning                                            |
|----------|----------------------------------------------------|
| `0`      | Success                                            |
| `2`      | Invalid arguments (e.g. `--expiration-secs > 300`) |
| Non-zero | HTTP error or runtime error                        |

## API Documentation References

- [Authentication](https://api-docs.grvt.io/auth/) — Login methods and session management
- [Trading API](https://api-docs.grvt.io/trading_api/) — Authenticated endpoint documentation
