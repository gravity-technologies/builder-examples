# GRVT Builder Codes / Trading API Smoke Test

A Python script for testing the GRVT Builder integration flow, including authorization, authentication, and API access.

## Overview

This script (`authorize.py`) demonstrates the complete flow for integrating with GRVT's Builder Codes system:

1. **Authorization**: Generate an API key by having a user authorize a builder (using EIP-712 signature)
2. **Login**: Authenticate using the API key to obtain a session cookie
3. **API Access**: Call authenticated Trading API endpoints (e.g., `get_sub_accounts`)

## Prerequisites

- Python 3.7+
- Required packages:
  ```bash
  pip install requests eth-account
  ```

## Configuration

The script supports multiple environments:

- `dev` - Development environment (edge.dev.gravitymarkets.io)
- `staging` - Staging environment (edge.staging.gravitymarkets.io)
- `testnet` - Testnet environment (edge.testnet.grvt.io) **[default]**
- `prod` - Production environment (edge.grvt.io)

## Usage

### Option A: Use an Existing API Key

If you already have an API key, you can skip the authorization step:

```bash
python authorize.py --env testnet --api-key YOUR_API_KEY
```

### Option B: Full Authorization Flow

Generate a new API key and test the complete flow:

```bash
python authorize.py --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
  --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS \
  --builder-api-signer-privkey 0xA_FRESH_SIGNER_PRIVKEY
```

## Command Line Arguments

| Argument                       | Description                                             | Required       | Default              |
|--------------------------------|---------------------------------------------------------|----------------|----------------------|
| `--env`                        | Target environment (dev/staging/testnet/prod)           | No             | `testnet`            |
| `--api-key`                    | Existing API key to use (skips authorization)           | Conditional*   | None                 |
| `--authorize`                  | Flag to run the authorization step                      | Conditional*   | False                |
| `--user-privkey`               | User's main account private key (for EIP-712 signature) | If authorizing | None                 |
| `--main-account-id`            | User's main account address (0x...)                     | If authorizing | None                 |
| `--builder-account-id`         | Builder's main account address (0x...)                  | If authorizing | None                 |
| `--builder-api-signer-privkey` | Fresh signer private key for the API key                | If authorizing | None                 |
| `--permissions`                | Permission level for the API key                        | No             | `Trade`              |
| `--builder-api-key-label`      | Label for the generated API key                         | No             | `builder-smoke-test` |
| `--max-futures-fee-rate`       | Maximum futures fee rate (decimal string)               | No             | `0.001`              |
| `--max-spot-fee-rate`          | Maximum spot fee rate (decimal string)                  | No             | `0.0001`             |

\* Either provide `--api-key` OR use `--authorize` with required authorization arguments.

**Note:** The EIP-712 domain chain ID is automatically configured based on the selected environment:
- `dev` and `staging`: chain ID 327
- `testnet`: chain ID 326
- `prod`: chain ID 325

## How It Works

### 1. Authorization Step (Optional)

When you run with `--authorize`, the script:

1. Generates a random nonce (32-bit unsigned integer)
2. Calculates an expiration timestamp (7 days from now, in nanoseconds)
3. Builds an EIP-712 typed data structure with:
   - User's main account ID
   - Builder's main account ID
   - Builder API key signer address (derived from `--builder-api-signer-privkey`)
   - Permissions (default: "Trade")
   - Maximum fee rates (converted to uint32)
   - Nonce and expiration
4. Signs the typed data with the user's private key
5. Sends a POST request to `/auth/builder/authorize` with:
   - The signature components (v, r, s)
   - Account IDs and fee rates
   - Builder API key label and signer address
6. Returns the generated API key

**EIP-712 Domain:**
```json
{
  "name": "GRVT Exchange",
  "version": "0",
  "chainId": 326
}
```
*Note: chainId varies by environment (dev/staging: 327, testnet: 326, prod: 325)*

**Primary Type:** `AddAccountSignerWithBuilder`

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
- The `builder-api-signer-privkey` should be a fresh keypair generated specifically for this purpose
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

**Error:** `Missing required args for --authorize: ...`

**Solution:** When using `--authorize`, you must provide:
- `--user-privkey`
- `--main-account-id`
- `--builder-account-id`
- `--builder-api-signer-privkey`

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

python authorize.py --env testnet --api-key "$GRVT_API_KEY"
```

### Testing Different Environments

```bash
# Development
python authorize.py --env dev --api-key YOUR_API_KEY

# Staging
python authorize.py --env staging --api-key YOUR_API_KEY

# Production
python authorize.py --env prod --api-key YOUR_API_KEY
```

## Script Functions

The script is organized into reusable functions:

- `build_eip712_payload()` - Constructs the EIP-712 typed data structure
- `sign_eip712()` - Signs typed data with a private key (returns v, r, s)
- `authorize_builder()` - Calls the builder authorization endpoint
- `login_with_api_key()` - Authenticates with an API key
- `get_sub_accounts()` - Fetches sub-accounts from the Trading API
- `_ensure_0x()` - Normalizes Ethereum addresses (adds 0x prefix, lowercases)
- `_hex32()` - Converts integers to 32-byte hex strings
- `_parse_gravity_cookie()` - Extracts gravity cookie from Set-Cookie header
- `_print_http()` - Pretty-prints HTTP request/response details

## Contributing

When modifying this script:

1. Ensure all address/key handling uses `_ensure_0x()` for consistency
2. Add proper error handling with descriptive messages
3. Update this README if you add new arguments or change behavior
4. Test against multiple environments (dev, staging, testnet)

## License

This script is provided as-is for testing and integration purposes with GRVT's Builder Codes system.
