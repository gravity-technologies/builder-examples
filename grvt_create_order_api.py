#!/usr/bin/env python3
"""
GRVT Order Creation Script with API Key Authentication

This script creates orders on GRVT Trading API using API Key authentication.
It combines the authentication flow from authorize.py with order signing from
grvt_order_with_builder_fee_signer.py.

Usage:
    python grvt_create_order_api.py --env testnet --api-key YOUR_API_KEY --private-key YOUR_PRIVATE_KEY

Flow:
1. Login with API key to get session cookie and account ID
2. Load order data from JSON file
3. Sign the order using EIP-712 signature
4. Submit the order to the Trading API
5. Display the order response

Requirements:
    pip install requests eth-account
"""

import argparse
import json
import secrets
import sys
import time
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data


# ================================================================================
# ENVIRONMENT CONFIGURATIONS
# ================================================================================

class GrvtEnv(Enum):
    """GRVT Environment enumeration."""
    DEV = "dev"
    STAGING = "staging"
    TESTNET = "testnet"
    PROD = "prod"


class TimeInForce(Enum):
    """Time in Force enumeration."""
    GOOD_TILL_TIME = "GOOD_TILL_TIME"
    ALL_OR_NONE = "ALL_OR_NONE"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"


class SignTimeInForce(Enum):
    """Sign Time in Force enumeration (numeric values for signing)."""
    GOOD_TILL_TIME = 1
    ALL_OR_NONE = 2
    IMMEDIATE_OR_CANCEL = 3
    FILL_OR_KILL = 4


# Chain IDs for each environment
CHAIN_IDS = {
    GrvtEnv.DEV: 327,
    GrvtEnv.STAGING: 327,
    GrvtEnv.TESTNET: 326,
    GrvtEnv.PROD: 325,
}

# Edge API endpoints (for authentication)
EDGE_API_ENDPOINTS = {
    GrvtEnv.DEV: "https://edge.dev.gravitymarkets.io",
    GrvtEnv.STAGING: "https://edge.staging.gravitymarkets.io",
    GrvtEnv.TESTNET: "https://edge.testnet.grvt.io",
    GrvtEnv.PROD: "https://edge.grvt.io",
}

# Trading API endpoints (for order submission)
TRADING_API_ENDPOINTS = {
    GrvtEnv.DEV: "https://trades.dev.gravitymarkets.io",
    GrvtEnv.STAGING: "https://trades.staging.gravitymarkets.io",
    GrvtEnv.TESTNET: "https://trades.testnet.grvt.io",
    GrvtEnv.PROD: "https://trades.grvt.io",
}

# Market Data API endpoints (for instruments)
MARKET_DATA_API_ENDPOINTS = {
    GrvtEnv.DEV: "https://market-data.dev.gravitymarkets.io",
    GrvtEnv.STAGING: "https://market-data.staging.gravitymarkets.io",
    GrvtEnv.TESTNET: "https://market-data.testnet.grvt.io",
    GrvtEnv.PROD: "https://market-data.grvt.io",
}

# Time in Force mapping
TIME_IN_FORCE_TO_SIGN_TIME_IN_FORCE = {
    TimeInForce.GOOD_TILL_TIME: SignTimeInForce.GOOD_TILL_TIME,
    TimeInForce.ALL_OR_NONE: SignTimeInForce.ALL_OR_NONE,
    TimeInForce.IMMEDIATE_OR_CANCEL: SignTimeInForce.IMMEDIATE_OR_CANCEL,
    TimeInForce.FILL_OR_KILL: SignTimeInForce.FILL_OR_KILL,
}

# Price multiplier for converting decimal prices to contract units
PRICE_MULTIPLIER = 1_000_000_000

# EIP-712 Type definitions for order signing
EIP712_ORDER_MESSAGE_TYPE = {
    "OrderWithBuilderFee": [
        {"name": "subAccountID", "type": "uint64"},
        {"name": "isMarket", "type": "bool"},
        {"name": "timeInForce", "type": "uint8"},
        {"name": "postOnly", "type": "bool"},
        {"name": "reduceOnly", "type": "bool"},
        {"name": "legs", "type": "OrderLeg[]"},
        {"name": "builder", "type": "address"},
        {"name": "builderFee", "type": "uint32"},
        {"name": "nonce", "type": "uint32"},
        {"name": "expiration", "type": "int64"},
    ],
    "OrderLeg": [
        {"name": "assetID", "type": "uint256"},
        {"name": "contractSize", "type": "uint64"},
        {"name": "limitPrice", "type": "uint64"},
        {"name": "isBuyingContract", "type": "bool"},
    ],
}


# ================================================================================
# UTILITY FUNCTIONS
# ================================================================================

def _ensure_0x(s: str) -> str:
    """Ensure a hex string has 0x prefix."""
    s = s.strip()
    return s if s.startswith("0x") else "0x" + s


def _parse_gravity_cookie(set_cookie_header: Optional[str]) -> Optional[str]:
    """Parse gravity cookie from Set-Cookie header."""
    if not set_cookie_header:
        return None
    idx = set_cookie_header.lower().find("gravity=")
    if idx == -1:
        return None
    frag = set_cookie_header[idx:]
    end = frag.find(";")
    return frag if end == -1 else frag[:end]


def _print_http(title: str, resp: requests.Response) -> None:
    """Print HTTP request/response details."""
    print(f"\n== {title} ==")
    print(f"URL: {resp.request.method} {resp.request.url}")
    print(f"Status: {resp.status_code}")
    if resp.headers.get("x-grvt-account-id"):
        print(f"X-Grvt-Account-Id: {resp.headers.get('x-grvt-account-id')}")
    try:
        data = resp.json()
        print("Response:")
        print(json.dumps(data, indent=2))
    except Exception:
        body = resp.text
        print("Body:")
        print(body[:2000] + ("..." if len(body) > 2000 else ""))


# ================================================================================
# AUTHENTICATION FUNCTIONS
# ================================================================================

def login_with_api_key(env: GrvtEnv, api_key: str) -> Tuple[str, str]:
    """
    Login with API key to get session cookie and account ID.

    Args:
        env: GRVT environment
        api_key: API key for authentication

    Returns:
        Tuple of (gravity_cookie, x_grvt_account_id)
    """
    edge_base = EDGE_API_ENDPOINTS[env]
    url = f"{edge_base}/auth/api_key/login"
    headers = {"Content-Type": "application/json", "Cookie": "rm=true;"}

    print(f"\n🔐 Logging in with API key to {env.value} environment...")
    resp = requests.post(url, headers=headers, json={"api_key": api_key}, timeout=30)

    if resp.status_code != 200:
        _print_http("API Key Login Failed", resp)
        raise RuntimeError(f"Login failed with status {resp.status_code}")

    gravity_cookie = _parse_gravity_cookie(resp.headers.get("set-cookie"))
    account_id = resp.headers.get("x-grvt-account-id")

    if not gravity_cookie:
        raise RuntimeError("Could not find gravity cookie in Set-Cookie response header.")
    if not account_id:
        raise RuntimeError("Could not find x-grvt-account-id in response headers.")

    print(f"✅ Login successful!")
    print(f"   Account ID: {account_id}")
    return gravity_cookie, account_id


# ================================================================================
# INSTRUMENTS FUNCTIONS
# ================================================================================

def fetch_instruments_from_api(env: GrvtEnv) -> Dict[str, Dict[str, Any]]:
    """
    Fetch instruments data from GRVT Market Data API.

    Args:
        env: GRVT environment

    Returns:
        Dictionary mapping instrument names to their metadata
    """
    market_data_base = MARKET_DATA_API_ENDPOINTS[env]
    url = f"{market_data_base}/full/v1/all_instruments"
    payload = {"is_active": True}

    print(f"\n🔄 Fetching instruments from {env.value} environment...")
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()

    data = response.json()
    instruments = {}

    for instrument_data in data.get("result", []):
        instrument_name = instrument_data["instrument"]
        instruments[instrument_name] = {
            "instrument_hash": instrument_data["instrument_hash"],
            "base_decimals": instrument_data["base_decimals"]
        }

    print(f"✅ Fetched {len(instruments)} instruments")
    return instruments


# ================================================================================
# ORDER SIGNING FUNCTIONS
# ================================================================================

def get_eip712_domain_data(env: GrvtEnv) -> Dict[str, Any]:
    """Get EIP-712 domain data for the environment."""
    return {
        "name": "GRVT Exchange",
        "version": "0",
        "chainId": CHAIN_IDS[env],
    }


def build_order_message_data(order_data: Dict[str, Any], instruments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build EIP-712 order message data from order payload.

    Args:
        order_data: Order data containing legs, sub_account_id, etc.
        instruments: Dictionary mapping instrument names to their metadata

    Returns:
        Dictionary containing the message data for signing
    """
    # Extract order data (handle both wrapped and direct formats)
    if "order" in order_data:
        order = order_data["order"]
    else:
        order = order_data

    # Process order legs
    legs = []
    for leg in order["legs"]:
        instrument_name = leg["instrument"]
        if instrument_name not in instruments:
            raise ValueError(f"Instrument '{instrument_name}' not found in instruments data")

        instrument = instruments[instrument_name]
        size_multiplier = 10 ** instrument["base_decimals"]

        # Use Decimal for precision
        size_int = int(Decimal(leg["size"]) * Decimal(size_multiplier))
        price_int = int(Decimal(leg["limit_price"]) * Decimal(PRICE_MULTIPLIER))

        legs.append({
            "assetID": instrument["instrument_hash"],
            "contractSize": size_int,
            "limitPrice": price_int,
            "isBuyingContract": leg["is_buying_asset"],
        })

    # Convert time in force to contract enum value
    time_in_force_str = order.get("time_in_force", "GOOD_TILL_TIME")
    time_in_force = TimeInForce(time_in_force_str)
    sign_time_in_force = TIME_IN_FORCE_TO_SIGN_TIME_IN_FORCE[time_in_force]

    # Build message data
    builder_fee_int = int(Decimal(order.get("builder_fee", "0.001")) * Decimal(10000))

    return {
        "subAccountID": int(order["sub_account_id"]),
        "isMarket": order.get("is_market", False),
        "timeInForce": sign_time_in_force.value,
        "postOnly": order.get("post_only", False),
        "reduceOnly": order.get("reduce_only", False),
        "legs": legs,
        "builder": order.get("builder", ""),
        "builderFee": builder_fee_int,
        "nonce": order["signature"]["nonce"],
        "expiration": order["signature"]["expiration"],
    }


def sign_order(
    order_data: Dict[str, Any],
    instruments: Dict[str, Dict[str, Any]],
    private_key: str,
    env: GrvtEnv
) -> Dict[str, Any]:
    """
    Sign an order using EIP-712 signature.

    Args:
        order_data: Order data containing legs, signature info, etc.
        instruments: Dictionary mapping instrument names to their metadata
        private_key: Private key in hex format
        env: GRVT environment

    Returns:
        Dictionary containing the complete signed order payload
    """
    # Remove 0x prefix if present
    if private_key.startswith("0x"):
        private_key = private_key[2:]

    # Build EIP-712 message data
    message_data = build_order_message_data(order_data, instruments)

    # Build EIP-712 domain data
    domain_data = get_eip712_domain_data(env)

    # Create signable message
    signable_message = encode_typed_data(domain_data, EIP712_ORDER_MESSAGE_TYPE, message_data)

    # Sign the message
    account = Account.from_key(private_key)
    signed_message = account.sign_message(signable_message)

    # Extract signature components
    signature = {
        "r": "0x" + signed_message.r.to_bytes(32, byteorder="big").hex(),
        "s": "0x" + signed_message.s.to_bytes(32, byteorder="big").hex(),
        "v": signed_message.v,
        "signer": account.address
    }

    # Create complete order payload
    if "order" in order_data:
        order = order_data["order"].copy()
    else:
        order = order_data.copy()

    # Update the signature in the order data
    order["signature"] = {
        "r": signature["r"],
        "s": signature["s"],
        "v": signature["v"],
        "expiration": order["signature"]["expiration"],
        "nonce": order["signature"]["nonce"],
        "signer": signature["signer"]
    }

    return {"order": order}


# ================================================================================
# ORDER CREATION FUNCTIONS
# ================================================================================

def create_order(
    env: GrvtEnv,
    gravity_cookie: str,
    account_id: str,
    order_payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Submit an order to the GRVT Trading API.

    Args:
        env: GRVT environment
        gravity_cookie: Session cookie from login
        account_id: Account ID from login
        order_payload: Complete signed order payload

    Returns:
        API response with order details
    """
    trades_base = TRADING_API_ENDPOINTS[env]
    url = f"{trades_base}/full/v1/create_order"

    headers = {
        "Content-Type": "application/json",
        "Cookie": gravity_cookie,
        "X-Grvt-Account-Id": account_id,
    }

    print(f"\n📤 Submitting order to {env.value} Trading API...")
    print(f"   Endpoint: {url}")
    print(json.dumps(order_payload, indent=2))
    print(headers)
    resp = requests.post(url, headers=headers, json=order_payload, timeout=30)

    if resp.status_code != 200:
        _print_http("Create Order Failed", resp)
        raise RuntimeError(f"Order creation failed with status {resp.status_code}")

    print(f"✅ Order submitted successfully!")
    return resp.json()


# ================================================================================
# FILE I/O FUNCTIONS
# ================================================================================

def load_json_file(file_path: str) -> Dict[str, Any]:
    """Load JSON data from a file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in file {file_path}: {e}")


def update_order_signature_fields(order_data: Dict[str, Any], expiration_hours: int = 24) -> Dict[str, Any]:
    """
    Update order signature fields with fresh expiration and nonce.

    Args:
        order_data: Order data to update
        expiration_hours: Hours until expiration (default 24)

    Returns:
        Updated order data
    """
    # Generate new expiration (in nanoseconds)
    expiration_ns = int((time.time() + expiration_hours * 3600) * 1_000_000_000)

    # Generate new nonce
    nonce = secrets.randbelow(2**32)

    # Update signature fields
    if "order" in order_data:
        order_data["order"]["signature"]["expiration"] = str(expiration_ns)
        order_data["order"]["signature"]["nonce"] = nonce
    else:
        order_data["signature"]["expiration"] = str(expiration_ns)
        order_data["signature"]["nonce"] = nonce

    return order_data


# ================================================================================
# MAIN FUNCTION
# ================================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create orders on GRVT Trading API using API Key authentication"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "staging", "testnet", "prod"],
        default="testnet",
        help="GRVT environment (default: testnet)"
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API key for authentication"
    )
    parser.add_argument(
        "--private-key",
        required=True,
        help="Private key for signing orders (hex format)"
    )
    parser.add_argument(
        "--order-file",
        default="create_order_data.json",
        help="Path to order data JSON file (default: create_order_data.json)"
    )
    parser.add_argument(
        "--update-expiration",
        action="store_true",
        help="Update order expiration and nonce before signing"
    )
    parser.add_argument(
        "--expiration-hours",
        type=int,
        default=24,
        help="Hours until order expiration (default: 24)"
    )

    args = parser.parse_args()

    try:
        # Parse environment
        env = GrvtEnv(args.env)

        print("=" * 70)
        print("GRVT Order Creation with API Key Authentication")
        print("=" * 70)
        print(f"Environment: {env.value}")

        # Step 1: Login with API key
        gravity_cookie, account_id = login_with_api_key(env, args.api_key)

        # Step 2: Fetch instruments
        instruments = fetch_instruments_from_api(env)

        # Step 3: Load order data
        print(f"\n📂 Loading order data from {args.order_file}...")
        order_data = load_json_file(args.order_file)
        print(f"✅ Order data loaded")

        # Step 4: Update signature fields if requested
        if args.update_expiration:
            print(f"\n🔄 Updating order expiration and nonce...")
            order_data = update_order_signature_fields(order_data, args.expiration_hours)
            print(f"✅ Updated expiration and nonce")

        # Step 5: Sign the order
        print(f"\n🔐 Signing order with EIP-712 signature...")
        signed_order = sign_order(order_data, instruments, args.private_key, env)
        print(f"✅ Order signed")
        print(f"   Signer: {signed_order['order']['signature']['signer']}")

        # Step 6: Submit the order
        result = create_order(env, gravity_cookie, account_id, signed_order)

        # Step 7: Display results
        print("\n" + "=" * 70)
        print("ORDER RESULT")
        print("=" * 70)
        print(json.dumps(result, indent=2))

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user.")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
