# GRVT Builder Codes / Trading API Smoke Test

Scripts for testing the GRVT Builder integration flow, including authorization, authentication, and API access. Available in **Python** and **TypeScript**.

| Python                | TypeScript                    |
|-----------------------|-------------------------------|
| `python/authorize.py` | `typescript/src/authorize.ts` |

## Overview

These scripts demonstrate the complete flow for integrating with GRVT's Builder Codes system:

1. **Authorization (with API key)**: Generate an API key by having a user authorize a builder via `AddAccountSignerWithBuilder` (EIP-712 signature) — use `--authorize`
2. **Authorization (without API key)**: Authorize a builder's fee rates on-chain via `AuthorizeBuilder` (EIP-712 signature) without creating an API key — use `--authorize-only`
3. **Login**: Authenticate using the API key to obtain a session cookie
4. **API Access**: Call authenticated Trading API endpoints (e.g., `get_sub_accounts`)

### When to use each authorization path

| Path            | Flag               | Creates API key | EIP-712 type                  | Use when                                      |
|-----------------|--------------------|-----------------|-------------------------------|-----------------------------------------------|
| With API key    | `--authorize`      | Yes             | `AddAccountSignerWithBuilder` | Builder needs to trade on behalf of the user  |
| Without API key | `--authorize-only` | No              | `AuthorizeBuilder`            | Only registering the builder's fee rates      |

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

## Configuration

The script supports multiple environments:

- `staging` - Staging environment (edge.staging.gravitymarkets.io)
- `testnet` - Testnet environment (edge.testnet.grvt.io) **[default]**
- `prod` - Production environment (edge.grvt.io)

## Usage

### Option A: Use an Existing API Key

If you already have an API key, you can skip the authorization step:

**Python** (from `python/` directory):
```bash
cd python
python authorize.py --env testnet --api-key YOUR_API_KEY
```

**TypeScript** (from `typescript/` directory):
```bash
cd typescript
npx tsx src/authorize.ts --env testnet --api-key YOUR_API_KEY
```

### Option B: Full Authorization Flow (with API key)

Generate a new API key and test the complete flow:

**Python:**
```bash
python authorize.py --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
  --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
```

**TypeScript:**
```bash
npx tsx src/authorize.ts --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
  --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
```

**Note:** If you don't provide `--builder-api-signer-privkey`, a new keypair will be automatically generated and displayed.

### Option C: Authorize Builder Without API Key

Authorize a builder's fee rates on-chain without creating an API key. No signer keypair is needed:

**Python:**
```bash
python authorize.py --env testnet \
  --authorize-only \
  --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
  --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
```

**TypeScript:**
```bash
npx tsx src/authorize.ts --env testnet \
  --authorize-only \
  --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
  --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
```

This sends an `AuthorizeBuilder` chain transaction and exits without proceeding to the login step.

## Command Line Arguments

| Argument                       | Description                                                               | Required                       | Default              |
|--------------------------------|---------------------------------------------------------------------------|--------------------------------|----------------------|
| `--env`                        | Target environment (staging/testnet/prod)                                 | No                             | `testnet`            |
| `--api-key`                    | Existing API key to use (skips authorization)                             | Conditional*                   | None                 |
| `--authorize`                  | Authorize builder and create an API key (with signer + permissions)       | Conditional*                   | False                |
| `--authorize-only`             | Authorize builder on-chain without creating an API key                    | Conditional*                   | False                |
| `--user-privkey`               | User's main account private key (for EIP-712 signature)                   | If authorizing                 | None                 |
| `--main-account-id`            | User's funding account address (0x...)                                    | If authorizing                 | None                 |
| `--builder-account-id`         | Builder's funding account address (0x...)                                 | If authorizing                 | None                 |
| `--builder-api-signer-privkey` | Fresh signer private key for the API key (auto-generated if not provided) | No (`--authorize` only)        | Auto-generated       |
| `--permissions`                | Permission level for the API key                                          | No (`--authorize` only)        | `Trade`              |
| `--builder-api-key-label`      | Label for the generated API key                                           | No (`--authorize` only)        | `builder-smoke-test` |
| `--max-futures-fee-rate`       | Maximum futures fee rate (decimal string)                                 | No                             | `0.001`              |
| `--max-spot-fee-rate`          | Maximum spot fee rate (decimal string)                                    | No                             | `0.0001`             |

\* Either provide `--api-key`, OR use `--authorize` (creates API key), OR use `--authorize-only` (no API key).

**Note on Auto-Generated Keys:** When using `--authorize` without providing `--builder-api-signer-privkey`, the script will automatically generate a new keypair and display the private key. Make sure to save this private key securely, as you'll need it to use the API key later.

**Note:** The EIP-712 domain chain ID is automatically configured based on the selected environment:
- `staging`: chain ID 327
- `testnet`: chain ID 326
- `prod`: chain ID 325

## How It Works

### 1a. Authorization Step with API key (`--authorize`)

When you run with `--authorize`, the script:

1. **Generates a builder API signer keypair** (if `--builder-api-signer-privkey` is not provided):
   - Creates a new Ethereum keypair using `Account.create()`
   - Displays the private key and address with clear warnings to save it securely
2. Generates a random nonce (32-bit unsigned integer)
3. Calculates an expiration timestamp (7 days from now, in nanoseconds)
4. Builds an EIP-712 typed data structure with:
   - User's main account ID (funding account address)
   - Builder's main account ID (funding account address)
   - Builder API key signer address (derived from the private key)
   - Permissions (default: "Trade")
   - Maximum fee rates (converted to uint32)
   - Nonce and expiration
5. Signs the typed data with the user's private key
6. Sends a POST request to `/auth/builder/authorize` with:
   - The signature components (v, r, s)
   - Account IDs and fee rates
   - Builder API key label, signer address, and permissions
7. Returns the generated API key

**EIP-712 Domain:**
```json
{
  "name": "GRVT Exchange",
  "version": "0",
  "chainId": 326
}
```
*Note: chainId varies by environment (staging: 327, testnet: 326, prod: 325)*

**Primary Type:** `AddAccountSignerWithBuilder`

### 1b. Authorization Step without API key (`--authorize-only`)

When you run with `--authorize-only`, the script:

1. Generates a random nonce (32-bit unsigned integer)
2. Calculates an expiration timestamp (7 days from now, in nanoseconds)
3. Builds an EIP-712 typed data structure with:
   - User's main account ID (funding account address)
   - Builder's main account ID (funding account address)
   - Maximum fee rates (converted to uint32)
   - Nonce and expiration
   - **No signer address or permissions** (those fields are omitted)
4. Signs the typed data with the user's private key
5. Sends a POST request to `/auth/builder/authorize` with:
   - The signature components (v, r, s)
   - Account IDs and fee rates
   - **No** `builder_api_key_label`, `builder_api_key_signer`, or `builder_api_key_permissions`
6. Exits after success — no API key is returned and the login step is skipped

**Primary Type:** `AuthorizeBuilder`

### 2. Login Step

After obtaining an API key (either from authorization or provided directly):

1. Sends a POST request to `/auth/api_key/login` with:
   - Content-Type: application/json
   - Cookie: rm=true;
   - Body: {"api_key": "..."}
2. Extracts from the response:
   - `gravity` cookie from the `Set-Cookie` header
   - `X-Grvt-Account-Id` from response headers

### 3. API Call Step

With the authenticated session:

1. Sends a POST request to `/full/v1/get_sub_accounts` with:
   - Cookie: gravity=...
   - X-Grvt-Account-Id: 0x...
2. Returns the user's sub-accounts information

## Important Notes

### Authorization Requirements

- The authorization step **MUST** be signed by the user's main account private key using EIP-712
- The signature authorizes a builder to act on behalf of the user's account
- The generated API key is valid for up to 30 days (this script uses 7 days by default)

### Security Considerations

⚠️ **Security Best Practices:**

- **Never commit private keys to version control**
- Store API keys securely (use environment variables or a secrets manager)
- Use environment variables or secure key management systems for sensitive data
- The `builder-api-signer-privkey` should be a fresh keypair generated specifically for this purpose (the script can auto-generate one for you)
- **Save the auto-generated private key immediately** - it's displayed only once and cannot be retrieved later
- Private keys are converted to lowercase hex format automatically

### Permissions

- The script uses `Trade` permissions by default (as recommended by GRVT documentation)
- This permission level allows the builder to execute trades on behalf of the user
- You can override with `--permissions` if needed

### Fee Rate Scaling

The script converts decimal fee rate strings to uint32 for the EIP-712 signature:
- Formula: `uint32 = int(fee_rate * 10000)`
- Example: "0.001" → 10 (uint32)
- Example: "0.0001" → 1 (uint32)

If GRVT uses a different scaling factor, you may need to adjust the conversion in the `authorize_builder` function.

## Output

The script provides detailed HTTP request/response information for debugging:

```
🔑 Generated new builder API signer keypair:
   Private Key: 0x1234567890abcdef...
   Address: 0xABCD1234...
   ⚠️  Save this private key securely - you'll need it to use the API key!

== Authorize Builder ==
URL: POST https://edge.testnet.grvt.io/auth/builder/authorize
Status: 200
Content-Type: application/json
JSON:
{
  "api_key": "grvt_api_...",
  ...
}

Minted api_key: grvt_api_...

== API Key Login ==
URL: POST https://edge.testnet.grvt.io/auth/api_key/login
Status: 200
...

Session gravity cookie: gravity=...
X-Grvt-Account-Id: 0x...

== Get Sub Accounts ==
URL: POST https://trades.testnet.grvt.io/full/v1/get_sub_accounts
Status: 200
...

Sub accounts: {...}

✅ Smoke test complete.
```

**Note:** Once the API Key is minted, you better save it securely. There's no way to retrieve the same API key again, and you would need to re-run the authorization flow to get a new one if lost.

## API Documentation References

- [Builder Codes Integration](https://api-docs.grvt.io/builder_codes/) - Authorization endpoint and EIP-712 payload structure
- [Authentication](https://api-docs.grvt.io/auth/) - API key login and session management
- [Trading API](https://api-docs.grvt.io/trading_api/) - Authenticated endpoint documentation

## Troubleshooting

### Missing `encode_typed_data` or `encode_structured_data`

**Error:** `RuntimeError: eth-account is missing encode_typed_data/encode_structured_data`

**Solution:** Update eth-account to a newer version:
```bash
pip install --upgrade eth-account
```

### Authorization Fails (4xx/5xx status)

**Possible causes:**
- Verify that `--user-privkey` corresponds to `--main-account-id`
- Check that all addresses are properly formatted (0x prefix, checksummed if required)
- Ensure fee rates are within acceptable ranges
- Verify the nonce is properly randomized
- Check that the EIP-712 domain chainId matches the environment

### Login Cookie Not Found

**Error:** `RuntimeError: Could not find gravity cookie in Set-Cookie response header`

**Possible causes:**
- The API key may be invalid or expired
- The API key may not have been generated correctly
- Network connectivity issues to the specified environment

### Missing Required Arguments

**Error:** `Missing required args for --authorize: ...` or `Missing required args for --authorize-only: ...`

**Solution:** When using `--authorize` or `--authorize-only`, you must provide:
- `--user-privkey`
- `--main-account-id`
- `--builder-account-id`

Note: `--builder-api-signer-privkey` is optional for `--authorize` (auto-generated if not provided) and is not used at all for `--authorize-only`.

## Exit Codes

- `0` - Success
- `2` - Missing required arguments or configuration error
- Non-zero - HTTP error or other runtime error

## Example Workflows

### Testing with Environment Variables

```bash
export USER_PRIVKEY="0x..."
export MAIN_ACCOUNT="0x..."
export BUILDER_ACCOUNT="0x..."

# Python (from python/ directory)
cd python

# Option 1: Let the script auto-generate a signer keypair
python authorize.py --env testnet \
  --authorize \
  --user-privkey "$USER_PRIVKEY" \
  --main-account-id "$MAIN_ACCOUNT" \
  --builder-account-id "$BUILDER_ACCOUNT"

# Option 2: Provide your own signer private key
export BUILDER_SIGNER_PRIVKEY="0x..."

python authorize.py --env testnet \
  --authorize \
  --user-privkey "$USER_PRIVKEY" \
  --main-account-id "$MAIN_ACCOUNT" \
  --builder-account-id "$BUILDER_ACCOUNT" \
  --builder-api-signer-privkey "$BUILDER_SIGNER_PRIVKEY"
```

### Reusing an Existing API Key

Once you have an API key, you can skip the authorization step:

```bash
export GRVT_API_KEY="grvt_api_..."

# Python (from python/ directory)
python authorize.py --env testnet --api-key "$GRVT_API_KEY"

# TypeScript (from typescript/ directory)
npx tsx src/authorize.ts --env testnet --api-key "$GRVT_API_KEY"
```

### Testing Different Environments

```bash
# Python (from python/ directory)
python authorize.py --env staging --api-key YOUR_API_KEY
python authorize.py --env prod --api-key YOUR_API_KEY

# TypeScript (from typescript/ directory)
npx tsx src/authorize.ts --env staging --api-key YOUR_API_KEY
npx tsx src/authorize.ts --env prod --api-key YOUR_API_KEY
```

## Script Functions

| Function                                | Python                                    | TypeScript                          |
|-----------------------------------------|-------------------------------------------|-------------------------------------|
| Build EIP-712 payload (with API key)    | `build_eip712_payload()`                  | `buildEip712Payload()`              |
| Build EIP-712 payload (authorize only)  | `build_eip712_payload_authorize_only()`   | `buildEip712PayloadAuthorizeOnly()` |
| Sign typed data                         | `sign_eip712()`                           | `signEip712()`                      |
| Authorize builder (with API key)        | `authorize_builder()`                     | `authorizeBuilder()`                |
| Authorize builder (no API key)          | `authorize_builder_only()`                | `authorizeBuilderOnly()`            |
| Login with API key                      | `login_with_api_key()`                    | `loginWithApiKey()`                 |
| Fetch sub-accounts                      | `get_sub_accounts()`                      | `getSubAccounts()`                  |
| Normalize addresses                     | `ensure_0x()`                             | `ensure0x()`                        |
| Parse cookie                            | `parse_gravity_cookie()`                  | `parseGravityCookie()`              |
| Debug HTTP                              | `print_http()`                            | `printHttp()`                       |

## Contributing

When modifying this script:

1. Ensure all address/key handling uses `_ensure_0x()` for consistency
2. Add proper error handling with descriptive messages
3. Update this README if you add new arguments or change behavior
4. Test against multiple environments (staging, testnet)

## License

This script is provided as-is for testing and integration purposes with GRVT's Builder Codes system.
