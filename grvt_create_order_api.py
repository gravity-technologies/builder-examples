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
from decimal import Decimal
from enum import Enum
from typing import Any, Dict

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

from grvt_common import (
    EnvConfig, ENVS, get_server_time_ns, login_with_api_key, print_http,
)


# ================================================================================
# ORDER-SPECIFIC CONSTANTS AND TYPES
# ================================================================================

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
# INSTRUMENTS FUNCTIONS
# ================================================================================

def fetch_instruments_from_api(env: EnvConfig) -> Dict[str, Dict[str, Any]]:
    """
    Fetch instruments data from GRVT Market Data API.

    Returns:
        Dictionary mapping instrument names to their metadata
    """
    url = f"{env.market_data_base}/full/v1/all_instruments"
    payload = {"is_active": True}

    print(f"\n🔄 Fetching instruments from {env.name} environment...")
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
    env: EnvConfig,
) -> Dict[str, Any]:
    """
    Sign an order using EIP-712 signature.

    Returns:
        Dictionary containing the complete signed order payload
    """
    # Remove 0x prefix if present
    if private_key.startswith("0x"):
        private_key = private_key[2:]

    # Build EIP-712 message data
    message_data = build_order_message_data(order_data, instruments)

    # Build EIP-712 domain and sign
    domain_data = {"name": "GRVT Exchange", "version": "0", "chainId": env.chain_id}
    signable_message = encode_typed_data(domain_data, EIP712_ORDER_MESSAGE_TYPE, message_data)

    account = Account.from_key(private_key)
    signed_message = account.sign_message(signable_message)

    signature = {
        "r": "0x" + signed_message.r.to_bytes(32, byteorder="big").hex(),
        "s": "0x" + signed_message.s.to_bytes(32, byteorder="big").hex(),
        "v": signed_message.v,
        "signer": account.address,
    }

    # Create complete order payload
    if "order" in order_data:
        order = order_data["order"].copy()
    else:
        order = order_data.copy()

    order["signature"] = {
        "r": signature["r"],
        "s": signature["s"],
        "v": signature["v"],
        "expiration": order["signature"]["expiration"],
        "nonce": order["signature"]["nonce"],
        "signer": signature["signer"],
    }

    return {"order": order}


# ================================================================================
# ORDER CREATION FUNCTIONS
# ================================================================================

def create_order(
    env: EnvConfig,
    gravity_cookie: str,
    account_id: str,
    order_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Submit an order to the GRVT Trading API.

    Returns:
        API response with order details
    """
    url = f"{env.trades_base}/full/v1/create_order"
    headers = {
        "Content-Type": "application/json",
        "Cookie": gravity_cookie,
        "X-Grvt-Account-Id": account_id,
    }

    print(f"\n📤 Submitting order to {env.name} Trading API...")
    print(f"   Endpoint: {url}")
    print(json.dumps(order_payload, indent=2))
    print(headers)
    resp = requests.post(url, headers=headers, json=order_payload, timeout=30)

    if resp.status_code != 200:
        print_http("Create Order Failed", resp)
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


def update_order_signature_fields(order_data: Dict[str, Any], env: EnvConfig, expiration_hours: int = 24) -> Dict[str, Any]:
    """
    Update order signature fields with fresh expiration and nonce.

    Args:
        order_data: Order data to update
        env: GRVT environment (used to fetch server time)
        expiration_hours: Hours until expiration (default 24)

    Returns:
        Updated order data
    """
    # Generate new expiration (in nanoseconds) based on server time
    expiration_ns = get_server_time_ns(env) + expiration_hours * 3600 * 1_000_000_000

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
        choices=ENVS.keys(),
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
        env = ENVS[args.env]

        print("=" * 70)
        print("GRVT Order Creation with API Key Authentication")
        print("=" * 70)
        print(f"Environment: {env.name}")

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
            order_data = update_order_signature_fields(order_data, env, args.expiration_hours)
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
