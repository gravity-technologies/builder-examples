# GRVT Order Creation with API Key Authentication

This script (`grvt_create_order_api.py`) allows you to create orders on the GRVT Trading API using API Key authentication, following the official [GRVT Trading API documentation](https://api-docs.grvt.io/trading_api/#create-order).

## Overview

The script combines three key components:
1. **API Key Authentication** - Login to get session credentials
2. **EIP-712 Order Signing** - Sign orders with your private key
3. **Order Submission** - Submit signed orders to the Trading API

## Installation

```bash
pip install requests eth-account
```

## Prerequisites

Before using this script, you need:

1. **API Key** - Obtained through the builder authorization flow (see `authorize.py`)
2. **Private Key** - Your Ethereum private key for signing orders
3. **Order Data** - A JSON file with your order details (see `create_order_data.json`)

## Usage

### Basic Usage

```bash
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json
```

### With Auto-Update Expiration

To automatically update the order expiration and nonce before signing:

```bash
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json \
  --update-expiration \
  --expiration-hours 24
```

## Command Line Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--env` | No | `testnet` | GRVT environment: `dev`, `staging`, `testnet`, or `prod` |
| `--api-key` | **Yes** | - | API key for authentication |
| `--private-key` | **Yes** | - | Private key for signing orders (hex format, with or without 0x prefix) |
| `--order-file` | No | `create_order_data.json` | Path to order data JSON file |
| `--update-expiration` | No | `false` | Update order expiration and nonce before signing |
| `--expiration-hours` | No | `24` | Hours until order expiration (only used with --update-expiration) |

## Order Data Format

Your order JSON file should follow this structure:

```json
{
    "order": {
        "sub_account_id": "4110889093865147",
        "is_market": true,
        "time_in_force": "GOOD_TILL_TIME",
        "post_only": false,
        "reduce_only": false,
        "legs": [
            {
                "instrument": "BTC_USDT_Perp",
                "size": "0.1",
                "limit_price": "0",
                "is_buying_asset": true
            }
        ],
        "signature": {
            "expiration": "1767672926708000000",
            "nonce": 1234562
        },
        "metadata": {
            "client_order_id": "23043"
        },
        "builder": "0xdc93ed3bc9932915a5bc7f6313b946091afc7e86",
        "builder_fee": "0.1"
    }
}
```

### Key Fields Explained

- **sub_account_id**: Your sub-account ID (obtained from `get_sub_accounts`)
- **is_market**: `true` for market orders, `false` for limit orders
- **time_in_force**: Order execution policy (`GOOD_TILL_TIME`, `IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL`, `ALL_OR_NONE`)
- **post_only**: If `true`, order will only be posted to the order book (maker only)
- **reduce_only**: If `true`, order can only reduce existing positions
- **legs**: Array of order legs (multi-leg orders supported)
  - **instrument**: Instrument name (e.g., `BTC_USDT_Perp`)
  - **size**: Order size as decimal string
  - **limit_price**: Limit price (use `"0"` for market orders)
  - **is_buying_asset**: `true` for buy, `false` for sell
- **signature.expiration**: Order expiration timestamp in nanoseconds
- **signature.nonce**: Unique nonce for this order
- **builder**: Builder account address (if using builder integration)
- **builder_fee**: Builder fee percentage (e.g., `"0.1"` for 0.1%)

## How It Works

### 1. Authentication Flow

```
API Key → Login → Session Cookie + Account ID
```

The script calls `/auth/api_key/login` with your API key to obtain:
- **gravity cookie**: Session authentication cookie
- **X-Grvt-Account-Id**: Your account ID header

### 2. Instrument Fetching

```
Environment → Market Data API → Instrument Metadata
```

Fetches instrument metadata (hash, decimals) needed for order signing from `/full/v1/all_instruments`.

### 3. Order Signing (EIP-712)

```
Order Data + Private Key → EIP-712 Signature → Signed Order
```

The script signs your order using EIP-712 typed data signing:
- Converts order data to contract format (decimal → integer units)
- Creates EIP-712 domain and message structures
- Signs with your private key
- Attaches signature (r, s, v) to the order

### 4. Order Submission

```
Signed Order + Session Cookie → Trading API → Order Result
```

Submits the signed order to `/full/v1/create_order` with authenticated headers.

## Environment Endpoints

| Environment | Chain ID | Edge API | Trading API | Market Data API |
|-------------|----------|----------|-------------|-----------------|
| **dev** | 327 | edge.dev.gravitymarkets.io | trades.dev.gravitymarkets.io | market-data.dev.gravitymarkets.io |
| **staging** | 327 | edge.staging.gravitymarkets.io | trades.staging.gravitymarkets.io | market-data.staging.gravitymarkets.io |
| **testnet** | 326 | edge.testnet.grvt.io | trades.testnet.grvt.io | market-data.testnet.grvt.io |
| **prod** | 325 | edge.grvt.io | trades.grvt.io | market-data.grvt.io |

## Example Output

```
======================================================================
GRVT Order Creation with API Key Authentication
======================================================================
Environment: testnet

🔐 Logging in with API key to testnet environment...
✅ Login successful!
   Account ID: 0x1234567890abcdef...

🔄 Fetching instruments from testnet environment...
✅ Fetched 150 instruments

📂 Loading order data from create_order_data.json...
✅ Order data loaded

🔄 Updating order expiration and nonce...
✅ Updated expiration and nonce

🔐 Signing order with EIP-712 signature...
✅ Order signed
   Signer: 0x1234567890abcdef...

📤 Submitting order to testnet Trading API...
   Endpoint: https://trades.testnet.grvt.io/full/v1/create_order
✅ Order submitted successfully!

======================================================================
ORDER RESULT
======================================================================
{
  "result": {
    "order_id": "123456789",
    "sub_account_id": "4110889093865147",
    "status": "OPEN",
    ...
  }
}
```

## Error Handling

The script includes comprehensive error handling for:
- Authentication failures
- Invalid API keys
- Network errors
- Invalid order data
- Signature verification failures
- API validation errors

## Security Notes

⚠️ **IMPORTANT**: 
- Never commit your API keys or private keys to version control
- Store credentials securely (environment variables, secrets manager)
- Use testnet for testing before deploying to production
- Validate order parameters before submission

## Getting an API Key

If you don't have an API key, use the `authorize.py` script to generate one:

```bash
python authorize.py \
  --env testnet \
  --authorize \
  --user-privkey YOUR_USER_PRIVATE_KEY \
  --main-account-id YOUR_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id YOUR_BUILDER_ACCOUNT_ADDRESS \
  --builder-api-signer-privkey A_FRESH_SIGNER_PRIVATE_KEY
```

This will output an API key that you can use with `grvt_create_order_api.py`.

## Related Scripts

- **authorize.py** - Generate API keys through builder authorization
- **grvt_order_with_builder_fee_signer.py** - Original order signing script (uses private key only, no API key authentication)

## API Documentation

- Trading API: https://api-docs.grvt.io/trading_api/#create-order
- Authentication: https://api-docs.grvt.io/auth/
- Builder Integration: https://api-docs.grvt.io/builder_codes/

## Troubleshooting

### "Could not find gravity cookie"
- Check your API key is valid and not expired
- Ensure you're using the correct environment

### "Instrument not found"
- Verify the instrument name matches exactly (case-sensitive)
- Check the instrument is active in your environment

### "Signature verification failed"
- Ensure your private key matches the signer address
- Check that expiration timestamp is in the future
- Verify nonce is unique

### "Order validation failed"
- Check order size meets minimum requirements
- Verify price is within valid range
- Ensure sub_account_id is correct

## Support

For issues or questions:
1. Check the GRVT API documentation
2. Review error messages in the output
3. Test with smaller order sizes on testnet first
