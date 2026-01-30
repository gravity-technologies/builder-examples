# GRVT Builder Examples

A collection of Python scripts demonstrating integration with GRVT's Builder Codes system and Trading API.

## Overview

This repository contains example scripts for:
- **Builder Authorization** - Generate API keys through EIP-712 signature authorization
- **Order Creation** - Create and submit authenticated orders to the GRVT Trading API

These examples demonstrate the complete flow from user authorization to order execution, following GRVT's official API documentation.

## Repository Structure

```
builder-examples/
├── authorize.py                  # Builder authorization & API key generation
├── grvt_create_order_api.py     # Order creation with API key authentication
├── create_order_data.json       # Sample order data
├── docs/
│   ├── AUTHORIZE_README.md      # Detailed authorize.py documentation
│   └── CREATE_ORDER_README.md   # Detailed order creation documentation
└── README.md                    # This file
```

## Quick Start

### Prerequisites

- Python 3.7+
- Install required packages:

```bash
pip install requests eth-account
```

### 1. Generate an API Key

First, authorize a builder to generate an API key:

```bash
python authorize.py \
  --env testnet \
  --authorize \
  --user-privkey 0xYOUR_USER_PRIVATE_KEY \
  --main-account-id 0xYOUR_MAIN_ACCOUNT_ADDRESS \
  --builder-account-id 0xBUILDER_ACCOUNT_ADDRESS \
  --builder-api-signer-privkey 0xFRESH_SIGNER_PRIVATE_KEY
```

This will output an API key (e.g., `grvt_api_...`) that you'll use for authenticated requests.

**📖 See [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md) for complete documentation**

### 2. Create an Order

Use the generated API key to create and submit orders:

```bash
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json
```

**📖 See [docs/CREATE_ORDER_README.md](docs/CREATE_ORDER_README.md) for complete documentation**

## Scripts

### 1. authorize.py - Builder Authorization

**Purpose:** Generate API keys by authorizing a builder to act on behalf of a user's account.

**Key Features:**
- EIP-712 signature-based authorization
- Multi-environment support (dev, staging, testnet, prod)
- Automatic chain ID configuration per environment
- Session cookie and account ID extraction
- Test API access with authenticated endpoints

**Quick Example:**
```bash
# With existing API key
python authorize.py --env testnet --api-key YOUR_API_KEY

# Full authorization flow
python authorize.py --env testnet --authorize \
  --user-privkey 0x... \
  --main-account-id 0x... \
  --builder-account-id 0x... \
  --builder-api-signer-privkey 0x...
```

**Chain ID Configuration:**
- dev/staging: 327
- testnet: 326
- prod: 325

**📖 Full Documentation:** [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md)

---

### 2. grvt_create_order_api.py - Order Creation

**Purpose:** Create and submit signed orders to the GRVT Trading API using API key authentication.

**Key Features:**
- API key authentication flow
- EIP-712 order signing
- Multi-leg order support
- Automatic expiration and nonce updates
- Instrument metadata fetching
- Comprehensive error handling

**Quick Example:**
```bash
# Basic order creation
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json

# With auto-updated expiration
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json \
  --update-expiration \
  --expiration-hours 24
```

**📖 Full Documentation:** [docs/CREATE_ORDER_README.md](docs/CREATE_ORDER_README.md)

---

## Environments

All scripts support multiple GRVT environments:

| Environment | Chain ID | Edge API                       | Trading API                      | Market Data API                       |
|-------------|----------|--------------------------------|----------------------------------|---------------------------------------|
| **dev**     | 327      | edge.dev.gravitymarkets.io     | trades.dev.gravitymarkets.io     | market-data.dev.gravitymarkets.io     |
| **staging** | 327      | edge.staging.gravitymarkets.io | trades.staging.gravitymarkets.io | market-data.staging.gravitymarkets.io |
| **testnet** | 326      | edge.testnet.grvt.io           | trades.testnet.grvt.io           | market-data.testnet.grvt.io           |
| **prod**    | 325      | edge.grvt.io                   | trades.grvt.io                   | market-data.grvt.io                   |

Use `--env` flag to select the environment (default: `testnet`).

## Complete Workflow Example

Here's a complete workflow from authorization to order creation:

### Step 1: Authorization (One-time setup)

```bash
# Set environment variables for security
export USER_PRIVKEY="0x..."
export MAIN_ACCOUNT="0x..."
export BUILDER_ACCOUNT="0x..."
export BUILDER_SIGNER_PRIVKEY="0x..."

# Generate API key
python authorize.py --env testnet \
  --authorize \
  --user-privkey "$USER_PRIVKEY" \
  --main-account-id "$MAIN_ACCOUNT" \
  --builder-account-id "$BUILDER_ACCOUNT" \
  --builder-api-signer-privkey "$BUILDER_SIGNER_PRIVKEY"

# Save the output API key
export GRVT_API_KEY="grvt_api_..."
```

### Step 2: Create Your Order Data

Edit `create_order_data.json`:

```json
{
    "order": {
        "sub_account_id": "YOUR_SUB_ACCOUNT_ID",
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
        "builder": "0xYOUR_BUILDER_ADDRESS",
        "builder_fee": "0.1"
    }
}
```

### Step 3: Submit the Order

```bash
export ORDER_SIGNING_KEY="0x..."  # Private key for signing orders

python grvt_create_order_api.py \
  --env testnet \
  --api-key "$GRVT_API_KEY" \
  --private-key "$ORDER_SIGNING_KEY" \
  --order-file create_order_data.json \
  --update-expiration \
  --expiration-hours 24
```

## Security Best Practices

⚠️ **IMPORTANT SECURITY NOTES:**

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
- Ensure all four required arguments are provided when using `--authorize`
- See [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md#missing-required-arguments)

#### "Could not find gravity cookie"
- API key may be invalid or expired
- Check you're using the correct environment
- See [docs/AUTHORIZE_README.md](docs/AUTHORIZE_README.md#login-cookie-not-found)

#### "Instrument not found"
- Verify instrument name is correct and case-sensitive
- Check instrument is active in your environment
- See [docs/CREATE_ORDER_README.md](docs/CREATE_ORDER_README.md#troubleshooting)

#### "Signature verification failed"
- Ensure private key matches the signer address
- Check expiration timestamp is in the future
- Verify nonce is unique
- See [docs/CREATE_ORDER_README.md](docs/CREATE_ORDER_README.md#troubleshooting)

### Getting Help

1. Check the detailed documentation for each script in the `docs/` folder
2. Review GRVT's official API documentation
3. Verify your environment configuration and credentials
4. Test with smaller values on testnet first

## Development

### Running Tests

```bash
# Test authorization (without actual keys)
python authorize.py --help

# Test order creation (without actual keys)
python grvt_create_order_api.py --help
```

### Project Dependencies

- **requests** - HTTP client for API calls
- **eth-account** - Ethereum key management and EIP-712 signing

Install with:
```bash
pip install requests eth-account
```

## Contributing

When modifying these scripts:

1. **Test on testnet** before committing changes
2. **Update documentation** if you add new features or arguments
3. **Follow security best practices** for key handling
4. **Validate against all environments** (dev, staging, testnet)
5. **Add error handling** for new edge cases

## License

These examples are provided as-is for testing and integration purposes with GRVT's Builder Codes system.

## Additional Resources

- **GRVT Website:** https://grvt.io/
- **API Documentation:** https://api-docs.grvt.io/
- **Discord Community:** [Join GRVT Discord](https://discord.gg/grvt)

---

## Quick Reference

### authorize.py Commands

```bash
# Get help
python authorize.py --help

# Test with API key
python authorize.py --env testnet --api-key YOUR_API_KEY

# Full authorization
python authorize.py --env testnet --authorize \
  --user-privkey 0x... \
  --main-account-id 0x... \
  --builder-account-id 0x... \
  --builder-api-signer-privkey 0x...
```

### grvt_create_order_api.py Commands

```bash
# Get help
python grvt_create_order_api.py --help

# Create order
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json

# Create order with auto-expiration
python grvt_create_order_api.py \
  --env testnet \
  --api-key YOUR_API_KEY \
  --private-key YOUR_PRIVATE_KEY \
  --order-file create_order_data.json \
  --update-expiration \
  --expiration-hours 24
```

---

**Ready to get started?** Check out the detailed documentation:
- 📘 [Authorization Guide](docs/AUTHORIZE_README.md)
- 📗 [Order Creation Guide](docs/CREATE_ORDER_README.md)
