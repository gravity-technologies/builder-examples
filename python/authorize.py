#!/usr/bin/env python3
"""
GRVT Builder Codes / Trading API smoke test

What this script can do:
1) (Optional) Authorize a builder for a user WITH API key creation (EIP-712 AddAccountSignerWithBuilder) -> returns an api_key
2) (Optional) Authorize a builder for a user WITHOUT API key creation (EIP-712 AuthorizeBuilder) -> no api_key returned
3) Login with api_key -> returns session cookie (gravity=...) + X-Grvt-Account-Id header
4) Call Trading API: full/v1/get_sub_accounts (authenticated) -> prints subaccounts

Docs used:
- Builder authorize endpoints + EIP-712 payload shape: https://api-docs.grvt.io/builder_codes/  :contentReference[oaicite:0]{index=0}
- API-key login + required cookie/header extraction: https://api-docs.grvt.io/auth/  :contentReference[oaicite:1]{index=1}
- get_sub_accounts endpoint + required headers/cookie: https://api-docs.grvt.io/trading_api/  :contentReference[oaicite:2]{index=2}

Install:
  pip install requests eth-account

Examples:

A) If you already have an API key:
  python authorize.py --env testnet --api-key YOUR_API_KEY

B) Full flow with API key creation (authorize -> login -> get_sub_accounts):
  python authorize.py --env testnet \
    --authorize \
    --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
    --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
    --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS

  # Optionally provide a specific signer private key (otherwise auto-generated):
  # --builder-api-signer-privkey 0xA_FRESH_SIGNER_PRIVKEY

C) Authorize builder without API key creation:
  python authorize.py --env testnet \
    --authorize-only \
    --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
    --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
    --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS

Notes:
- The authorize step MUST be signed by the user's main account private key (EIP-712). :contentReference[oaicite:3]{index=3}
- Permissions: docs say "Please use TRADE for now". :contentReference[oaicite:4]{index=4}
- Use --authorize when you need an API key for the builder to trade on behalf of the user.
- Use --authorize-only when you only need to register the builder's fee rates without granting trading permissions.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from typing import Any, Dict

import requests
from eth_account import Account

from grvt_common import (
    EnvConfig, ENVS, ensure_0x, get_server_time_ns,
    sign_eip712, login_with_api_key, get_sub_accounts, print_http,
)


def build_eip712_payload(
    main_account_id: str,
    builder_account_id: str,
    signer_address: str,
    permissions: str,
    max_future_fee_rate_uint32: int,
    max_spot_fee_rate_uint32: int,
    nonce_uint32: int,
    expiration_unix_ns: int,
    domain_chain_id: int,
) -> Dict[str, Any]:
    # Matches the structure shown in the Builder Integration docs. :contentReference[oaicite:6]{index=6}
    return {
        "domain": {"chainId": domain_chain_id, "name": "GRVT Exchange", "version": "0"},
        "message": {
            "accountID": main_account_id,
            "signer": signer_address,
            "permissions": permissions,
            "builderAccountID": builder_account_id,
            "maxFutureFeeRate": max_future_fee_rate_uint32,
            "maxSpotFeeRate": max_spot_fee_rate_uint32,
            "nonce": nonce_uint32,
            "expiration": expiration_unix_ns,
        },
        "primaryType": "AddAccountSignerWithBuilder",
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "AddAccountSignerWithBuilder": [
                {"name": "accountID", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "permissions", "type": "string"},
                {"name": "builderAccountID", "type": "address"},
                {"name": "maxFutureFeeRate", "type": "uint32"},
                {"name": "maxSpotFeeRate", "type": "uint32"},
                {"name": "nonce", "type": "uint32"},
                {"name": "expiration", "type": "int64"},
            ],
        },
    }


def build_eip712_payload_authorize_only(
    main_account_id: str,
    builder_account_id: str,
    max_future_fee_rate_uint32: int,
    max_spot_fee_rate_uint32: int,
    nonce_uint32: int,
    expiration_unix_ns: int,
    domain_chain_id: int,
) -> Dict[str, Any]:
    """EIP-712 payload for AuthorizeBuilder (no API key creation)."""
    # "AuthorizeBuilder(address mainAccountID,address builderAccountID,uint32 maxFutureFeeRate,uint32 maxSpotFeeRate,uint32 nonce,int64 expiration)"
    return {
        "domain": {"chainId": domain_chain_id, "name": "GRVT Exchange", "version": "0"},
        "message": {
            "mainAccountID": main_account_id,
            "builderAccountID": builder_account_id,
            "maxFutureFeeRate": max_future_fee_rate_uint32,
            "maxSpotFeeRate": max_spot_fee_rate_uint32,
            "nonce": nonce_uint32,
            "expiration": expiration_unix_ns,
        },
        "primaryType": "AuthorizeBuilder",
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "AuthorizeBuilder": [
                {"name": "mainAccountID", "type": "address"},
                {"name": "builderAccountID", "type": "address"},
                {"name": "maxFutureFeeRate", "type": "uint32"},
                {"name": "maxSpotFeeRate", "type": "uint32"},
                {"name": "nonce", "type": "uint32"},
                {"name": "expiration", "type": "int64"},
            ],
        },
    }


def authorize_builder(
    env: EnvConfig,
    *,
    main_account_id: str,
    builder_account_id: str,
    user_privkey: str,
    builder_api_key_signer_privkey: str,
    builder_api_key_label: str = "builder-smoke-test",
    permissions: str = "Trade",
    max_futures_fee_rate: str = "0.001",
    max_spot_fee_rate: str = "0.0001",
) -> str:
    """
    Calls: POST {edge}/auth/builder/authorize  :contentReference[oaicite:7]{index=7}
    Returns: api_key
    """

    # Builder API signer is an ETH keypair you generate for the user; its PUBLIC address goes into payload/request. :contentReference[oaicite:8]{index=8}
    builder_api_key_signer_privkey = ensure_0x(builder_api_key_signer_privkey)
    signer_addr = Account.from_key(builder_api_key_signer_privkey).address

    # Get the public address from user_privkey for the signature signer field
    user_privkey_normalized = ensure_0x(user_privkey)
    user_address = Account.from_key(user_privkey_normalized).address

    # Docs show maxFutureFeeRate/maxSpotFeeRate are uint32 in the signing payload. :contentReference[oaicite:9]{index=9}
    mf_uint32 = int(float(max_futures_fee_rate) * 10_000)
    ms_uint32 = int(float(max_spot_fee_rate) * 10_000)

    nonce = secrets.randbelow(2**32)
    expiration_ns = get_server_time_ns(env) + 7 * 24 * 3600 * 1_000_000_000  # 7 days from server time; docs allow up to 30 days. :contentReference[oaicite:11]{index=11}

    typed = build_eip712_payload(
        main_account_id=ensure_0x(main_account_id),
        builder_account_id=ensure_0x(builder_account_id),
        signer_address=ensure_0x(signer_addr),
        permissions=permissions,
        max_future_fee_rate_uint32=mf_uint32,
        max_spot_fee_rate_uint32=ms_uint32,
        nonce_uint32=nonce,
        expiration_unix_ns=expiration_ns,
        domain_chain_id=env.chain_id,
    )
    v, r, s = sign_eip712(user_privkey_normalized, typed)

    url = f"{env.edge_base}/auth/builder/authorize"
    payload = {
        "main_account_id": ensure_0x(main_account_id),
        "builder_account_id": ensure_0x(builder_account_id),
        "max_futures_fee_rate": max_futures_fee_rate,
        "max_spot_fee_rate": max_spot_fee_rate,
        "signature": {
            "signer": ensure_0x(user_address),
            "r": r,
            "s": s,
            "v": v,
            "expiration": str(expiration_ns),
            "nonce": nonce,
            "chain_id": str(env.chain_id),
        },
        "builder_api_key_label": builder_api_key_label,
        "builder_api_key_signer": ensure_0x(signer_addr),
        "builder_api_key_permissions": permissions,
    }
    print(json.dumps(payload))

    resp = requests.post(url, json=payload, timeout=30)
    print_http("Authorize Builder", resp)
    resp.raise_for_status()
    data = resp.json()
    api_key = data.get("api_key")
    if not api_key:
        raise RuntimeError("authorize response missing api_key")
    return api_key


def authorize_builder_only(
    env: EnvConfig,
    *,
    main_account_id: str,
    builder_account_id: str,
    user_privkey: str,
    max_futures_fee_rate: str = "0.001",
    max_spot_fee_rate: str = "0.0001",
) -> None:
    """
    Calls: POST {edge}/auth/builder/authorize (without API key creation)
    Sends an AuthorizeBuilder chain transaction. No API key is returned.
    Use this when you only need to authorize a builder's fee rates without
    granting trading permissions via an API key.
    """
    user_privkey_normalized = ensure_0x(user_privkey)
    user_address = Account.from_key(user_privkey_normalized).address

    mf_uint32 = int(float(max_futures_fee_rate) * 10_000)
    ms_uint32 = int(float(max_spot_fee_rate) * 10_000)

    nonce = secrets.randbelow(2**32)
    expiration_ns = get_server_time_ns(env) + 7 * 24 * 3600 * 1_000_000_000

    typed = build_eip712_payload_authorize_only(
        main_account_id=ensure_0x(main_account_id),
        builder_account_id=ensure_0x(builder_account_id),
        max_future_fee_rate_uint32=mf_uint32,
        max_spot_fee_rate_uint32=ms_uint32,
        nonce_uint32=nonce,
        expiration_unix_ns=expiration_ns,
        domain_chain_id=env.chain_id,
    )
    v, r, s = sign_eip712(user_privkey_normalized, typed)

    url = f"{env.edge_base}/auth/builder/authorize"
    payload = {
        "main_account_id": ensure_0x(main_account_id),
        "builder_account_id": ensure_0x(builder_account_id),
        "max_futures_fee_rate": max_futures_fee_rate,
        "max_spot_fee_rate": max_spot_fee_rate,
        "signature": {
            "signer": ensure_0x(user_address),
            "r": r,
            "s": s,
            "v": v,
            "expiration": str(expiration_ns),
            "nonce": nonce,
            "chain_id": str(env.chain_id),
        },
    }
    print(json.dumps(payload))

    resp = requests.post(url, json=payload, timeout=30)
    print_http("Authorize Builder (no API key)", resp)
    resp.raise_for_status()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--env", choices=ENVS.keys(), default="testnet")
    p.add_argument("--api-key", help="If provided, skips authorize step and logs in directly.")
    p.add_argument("--authorize", action="store_true", help="Run builder authorize step to mint an API key (requires signer + permissions).")
    p.add_argument("--authorize-only", action="store_true", help="Authorize builder on-chain without creating an API key (no signer required).")
    p.add_argument("--user-privkey", help="User main account private key (for EIP-712 builder authorize signature).")
    p.add_argument("--main-account-id", help="User funding account address (0x...).")
    p.add_argument("--builder-account-id", help="Builder funding account address (0x...).")
    p.add_argument("--builder-api-signer-privkey", help="Fresh signer privkey used by builder on behalf of user. If not provided, a new keypair will be generated.")
    p.add_argument("--permissions", default="Trade", help='Use "Trade" (recommended by docs).')
    p.add_argument("--builder-api-key-label", default="builder-smoke-test")
    p.add_argument("--max-futures-fee-rate", default="0.001")
    p.add_argument("--max-spot-fee-rate", default="0.0001")
    args = p.parse_args()

    env = ENVS[args.env]
    api_key = args.api_key

    if args.authorize_only:
        missing = [k for k in ["user_privkey", "main_account_id", "builder_account_id"]
                   if getattr(args, k) in (None, "")]
        if missing:
            print(f"Missing required args for --authorize-only: {', '.join(missing)}", file=sys.stderr)
            return 2

        authorize_builder_only(
            env,
            main_account_id=args.main_account_id,
            builder_account_id=args.builder_account_id,
            user_privkey=args.user_privkey,
            max_futures_fee_rate=args.max_futures_fee_rate,
            max_spot_fee_rate=args.max_spot_fee_rate,
        )
        print("\n✅ Builder authorized (no API key created).")
        return 0

    if args.authorize:
        missing = [k for k in ["user_privkey", "main_account_id", "builder_account_id"]
                   if getattr(args, k) in (None, "")]
        if missing:
            print(f"Missing required args for --authorize: {', '.join(missing)}", file=sys.stderr)
            return 2

        # Generate a new keypair if builder_api_signer_privkey is not provided
        builder_api_signer_privkey = args.builder_api_signer_privkey
        if not builder_api_signer_privkey:
            new_account = Account.create()
            builder_api_signer_privkey = new_account.key.hex()
            print(f"\n🔑 Generated new builder API signer keypair:")
            print(f"   Private Key: {builder_api_signer_privkey}")
            print(f"   Address: {new_account.address}")
            print("   ⚠️  Save this private key securely - you'll need it to use the API key!\n")

        api_key = authorize_builder(
            env,
            main_account_id=args.main_account_id,
            builder_account_id=args.builder_account_id,
            user_privkey=args.user_privkey,
            builder_api_key_signer_privkey=builder_api_signer_privkey,
            builder_api_key_label=args.builder_api_key_label,
            permissions=args.permissions,
            max_futures_fee_rate=args.max_futures_fee_rate,
            max_spot_fee_rate=args.max_spot_fee_rate,
        )
        print(f"\nMinted api_key: {api_key}")

    if not api_key:
        print("Provide --api-key or run with --authorize (and required args).", file=sys.stderr)
        return 2

    gravity_cookie, account_id = login_with_api_key(env, api_key)
    print(f"\nSession gravity cookie: {gravity_cookie}")
    print(f"X-Grvt-Account-Id: {account_id}")

    subaccounts = get_sub_accounts(env, gravity_cookie, account_id)
    print(f"Sub accounts: {subaccounts}")
    print("\n✅ Smoke test complete.")
    # Many responses include {"sub_account_ids": [...]} in full mode. :contentReference[oaicite:15]{index=15}
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
