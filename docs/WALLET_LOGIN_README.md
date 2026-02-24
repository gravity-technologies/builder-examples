# GRVT Wallet Login

A Python script that authenticates to GRVT using an EIP-712 wallet signature (`POST /auth/wallet/login`).

## Overview

`wallet_login.py` demonstrates EIP-712-based authentication for the main signing wallet.
Unlike API-key login (which requires a pre-minted key), wallet login lets any registered
main-wallet holder obtain a session cookie by signing a short-lived message directly.

### How it works

1. Client builds a `WalletLogin` EIP-712 struct with their wallet address, a random nonce, and an expiration timestamp.
2. Client signs the struct with the wallet private key (`eth_signTypedData_v4`).
3. Client POSTs `{ address, signature: { v, r, s, nonce, expiration, chainID } }` to `/auth/wallet/login`.
4. Server validates expiration, verifies the EIP-712 signature, atomically marks the nonce as used (replay prevention via Redis), and issues a session cookie.
5. The script extracts the `gravity` cookie and `X-Grvt-Account-Id` header for use in subsequent API calls.

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

- Python 3.7+
- Required packages:

```bash
pip install requests eth-account
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

```bash
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY
```

### Login without verifying session

```bash
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
  --no-verify
```

### Provide wallet address explicitly

```bash
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
  --wallet-address 0xYOUR_WALLET_ADDRESS
```

### Custom expiration (must be ≤ 300 seconds / 5 minutes)

```bash
python wallet_login.py --env testnet \
  --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
  --expiration-secs 60
```

### Using environment variables

```bash
export WALLET_PRIVKEY="0x..."

python wallet_login.py --env testnet \
  --wallet-privkey "$WALLET_PRIVKEY"
```

## Command Line Arguments

| Argument              | Description                                                            | Required | Default             |
|-----------------------|------------------------------------------------------------------------|----------|---------------------|
| `--env`               | Target environment (dev/staging/testnet/prod)                          | No       | `testnet`           |
| `--wallet-privkey`    | Main wallet private key for EIP-712 signing                            | **Yes**  | None                |
| `--wallet-address`    | Wallet address (derived from `--wallet-privkey` if omitted)            | No       | Derived from privkey|
| `--expiration-secs`   | Signature lifetime in seconds (max 300 — server enforced)              | No       | `240` (4 minutes)   |
| `--no-verify`         | Skip the `get_sub_accounts` verification step after login              | No       | False               |

## How It Works

### Step 1: Build the EIP-712 payload

The script constructs a `WalletLogin` typed-data structure:

```python
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
    "v": 28,
    "r": "0x...",
    "s": "0x...",
    "nonce": 2847362918,
    "expiration": 1700000240000000000,
    "chainID": 326
  }
}
```

`chainID` is optional — the server uses its configured GRVT chain ID when omitted or set to `0`.

### Step 4: Extract session

On `200 OK` the server sets a `gravity` session cookie and `X-Grvt-Account-Id` header.
These are used for all subsequent authenticated API calls:

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

Session gravity cookie: gravity=...
X-Grvt-Account-Id:      0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266

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

- `build_eip712_payload()` — Constructs the `WalletLogin` EIP-712 typed data structure
- `sign_eip712()` — Signs typed data with a private key (returns v, r, s)
- `wallet_login()` — Calls `POST /auth/wallet/login` and returns `(gravity_cookie, x_grvt_account_id)`
- `get_sub_accounts()` — Calls `POST /full/v1/get_sub_accounts` to verify the session
- `_ensure_0x()` — Normalizes Ethereum addresses (adds 0x prefix, lowercases)
- `_hex32()` — Converts integers to 32-byte hex strings
- `_parse_gravity_cookie()` — Extracts gravity cookie from Set-Cookie header
- `_print_http()` — Pretty-prints HTTP request/response details

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
