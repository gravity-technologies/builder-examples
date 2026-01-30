#!/usr/bin/env python3
"""
GRVT Builder Codes / Trading API smoke test

What this script can do:
1) (Optional) Authorize a builder for a user (EIP-712 signature) -> returns an api_key
2) Login with api_key -> returns session cookie (gravity=...) + X-Grvt-Account-Id header
3) Call Trading API: full/v1/get_sub_accounts (authenticated) -> prints subaccounts

Docs used:
- Builder authorize endpoints + EIP-712 payload shape: https://api-docs.grvt.io/builder_codes/  :contentReference[oaicite:0]{index=0}
- API-key login + required cookie/header extraction: https://api-docs.grvt.io/auth/  :contentReference[oaicite:1]{index=1}
- get_sub_accounts endpoint + required headers/cookie: https://api-docs.grvt.io/trading_api/  :contentReference[oaicite:2]{index=2}

Install:
  pip install requests eth-account

Examples:

A) If you already have an API key:
  python grvt_test.py --env testnet --api-key YOUR_API_KEY

B) Full flow (authorize -> login -> get_sub_accounts):
  python grvt_test.py --env testnet \
    --authorize \
    --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
    --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
    --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS \
    --builder-api-signer-privkey 0xA_FRESH_SIGNER_PRIVKEY

Notes:
- The authorize step MUST be signed by the user's main account private key (EIP-712). :contentReference[oaicite:3]{index=3}
- Permissions: docs say “Please use TRADE for now”. :contentReference[oaicite:4]{index=4}
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests

# eth-account imports can differ slightly by version; we try both encode helpers.
from eth_account import Account
try:
    from eth_account.messages import encode_typed_data  # newer
except Exception:  # pragma: no cover
    encode_typed_data = None
try:
    from eth_account.messages import encode_structured_data  # older
except Exception:  # pragma: no cover
    encode_structured_data = None


@dataclass(frozen=True)
class EnvConfig:
    name: str
    edge_base: str
    trades_base: str
    chain_id: int


ENVS: Dict[str, EnvConfig] = {
    "dev": EnvConfig("dev", "https://edge.dev.gravitymarkets.io", "https://trades.dev.gravitymarkets.io", 327),
    "staging": EnvConfig("staging", "https://edge.staging.gravitymarkets.io", "https://trades.staging.gravitymarkets.io", 327),
    "testnet": EnvConfig("testnet", "https://edge.testnet.grvt.io", "https://trades.testnet.grvt.io", 326),
    "prod": EnvConfig("prod", "https://edge.grvt.io", "https://trades.grvt.io", 325),
}


def _ensure_0x(s: str) -> str:
    s = s.strip()
    s = s if s.startswith("0x") else "0x" + s
    return s.lower()


def _hex32(n: int) -> str:
    return "0x" + n.to_bytes(32, "big").hex()


def _parse_gravity_cookie(set_cookie_header: Optional[str]) -> Optional[str]:
    # Docs show extracting gravity=[^;]* from Set-Cookie. :contentReference[oaicite:5]{index=5}
    if not set_cookie_header:
        return None
    # Sometimes multiple cookies; requests exposes combined headers awkwardly.
    # We'll just look for 'gravity=' in the string.
    idx = set_cookie_header.lower().find("gravity=")
    if idx == -1:
        return None
    frag = set_cookie_header[idx:]
    end = frag.find(";")
    return frag if end == -1 else frag[:end]


def _print_http(title: str, resp: requests.Response) -> None:
    print(f"\n== {title} ==")
    print(f"URL: {resp.request.method} {resp.request.url}")
    print(f"Status: {resp.status_code}")
    ct = resp.headers.get("content-type", "")
    print(f"Content-Type: {ct}")
    if resp.headers.get("x-grvt-account-id"):
        print(f"X-Grvt-Account-Id (response): {resp.headers.get('x-grvt-account-id')}")
    if resp.headers.get("set-cookie"):
        print(f"Set-Cookie: {resp.headers.get('set-cookie')}")
    try:
        data = resp.json()
        print("JSON:")
        print(json.dumps(data, indent=2))
    except Exception:
        body = resp.text
        print("Body:")
        print(body[:2000] + ("..." if len(body) > 2000 else ""))


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


def sign_eip712(user_privkey: str, typed_data: Dict[str, Any]) -> Tuple[int, str, str]:
    if encode_typed_data is None and encode_structured_data is None:
        raise RuntimeError("eth-account is missing encode_typed_data/encode_structured_data; try upgrading eth-account.")

    user_privkey = _ensure_0x(user_privkey)
    acct = Account.from_key(user_privkey)

    if encode_typed_data is not None:
        msg = encode_typed_data(full_message=typed_data)
    else:
        msg = encode_structured_data(primitive=typed_data)

    signed = acct.sign_message(msg)
    v = int(signed.v)
    r = _hex32(int(signed.r))
    s = _hex32(int(signed.s))
    return v, r, s


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
    builder_api_key_signer_privkey = _ensure_0x(builder_api_key_signer_privkey)
    signer_addr = Account.from_key(builder_api_key_signer_privkey).address

    # Docs show maxFutureFeeRate/maxSpotFeeRate are uint32 in the signing payload. :contentReference[oaicite:9]{index=9}
    # The request params are "string"; examples show decimals. :contentReference[oaicite:10]{index=10}
    # For the typed payload we need uint32. Without a clear scaling rule in this page, we let you pass integers
    # by environment variables if you want. For a simple smoke test, we map fee strings to basis points-ish:
    #   typed_uint32 = int(fee * 1e4)  (arbitrary, but deterministic)
    # If GRVT uses a different scaling, adjust these two lines accordingly.
    mf_uint32 = int(float(max_futures_fee_rate) * 10_000)
    ms_uint32 = int(float(max_spot_fee_rate) * 10_000)

    nonce = secrets.randbelow(2**32)
    expiration_ns = int((time.time() + 7 * 24 * 3600) * 1e9)  # 7 days from now; docs allow up to 30 days. :contentReference[oaicite:11]{index=11}

    typed = build_eip712_payload(
        main_account_id=_ensure_0x(main_account_id),
        builder_account_id=_ensure_0x(builder_account_id),
        signer_address=_ensure_0x(signer_addr),
        permissions=permissions,
        max_future_fee_rate_uint32=mf_uint32,
        max_spot_fee_rate_uint32=ms_uint32,
        nonce_uint32=nonce,
        expiration_unix_ns=expiration_ns,
        domain_chain_id=env.chain_id,
    )
    print(typed)

    v, r, s = sign_eip712(user_privkey=_ensure_0x(user_privkey), typed_data=typed)

    url = f"{env.edge_base}/auth/builder/authorize"
    print(permissions)
    payload = {
        "main_account_id": _ensure_0x(main_account_id),
        "builder_account_id": _ensure_0x(builder_account_id),
        "max_futures_fee_rate": max_futures_fee_rate,
        "max_spot_fee_rate": max_spot_fee_rate,
        "signature": {
            "signer": _ensure_0x(main_account_id),
            "r": r,
            "s": s,
            "v": v,
            "expiration": str(expiration_ns),
            "nonce": nonce,
            "chain_id": str(env.chain_id),
        },
        "builder_api_key_label": builder_api_key_label,
        "builder_api_key_signer": _ensure_0x(signer_addr),
        "builder_api_key_permissions": permissions,
    }
    print(json.dumps(payload))

    resp = requests.post(url, json=payload, timeout=30)
    _print_http("Authorize Builder", resp)
    resp.raise_for_status()
    data = resp.json()
    api_key = data.get("api_key")
    if not api_key:
        raise RuntimeError("authorize response missing api_key")
    return api_key


def login_with_api_key(env: EnvConfig, api_key: str) -> Tuple[str, str]:
    """
    Calls: POST {edge}/auth/api_key/login  :contentReference[oaicite:12]{index=12}
    Returns: (gravity_cookie_value, x_grvt_account_id)
    """
    url = f"{env.edge_base}/auth/api_key/login"
    headers = {"Content-Type": "application/json", "Cookie": "rm=true;"}  # per docs :contentReference[oaicite:13]{index=13}
    resp = requests.post(url, headers=headers, json={"api_key": api_key}, timeout=30)
    _print_http("API Key Login", resp)
    resp.raise_for_status()

    gravity_cookie = _parse_gravity_cookie(resp.headers.get("set-cookie"))
    account_id = resp.headers.get("x-grvt-account-id")

    if not gravity_cookie:
        raise RuntimeError("Could not find gravity cookie in Set-Cookie response header.")
    if not account_id:
        raise RuntimeError("Could not find x-grvt-account-id in response headers.")
    return gravity_cookie, account_id


def get_sub_accounts(env: EnvConfig, gravity_cookie: str, x_grvt_account_id: str) -> Dict[str, Any]:
    """
    Calls: POST {trades}/full/v1/get_sub_accounts  :contentReference[oaicite:14]{index=14}
    """
    url = f"{env.trades_base}/full/v1/get_sub_accounts"
    headers = {
        "Content-Type": "application/json",
        "Cookie": gravity_cookie,
        "X-Grvt-Account-Id": x_grvt_account_id,
    }
    resp = requests.post(url, headers=headers, json={}, timeout=30)
    _print_http("Get Sub Accounts", resp)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--env", choices=ENVS.keys(), default="testnet")
    p.add_argument("--api-key", help="If provided, skips authorize step and logs in directly.")
    p.add_argument("--authorize", action="store_true", help="Run builder authorize step to mint an API key.")
    p.add_argument("--user-privkey", help="User main account private key (for EIP-712 builder authorize signature).")
    p.add_argument("--main-account-id", help="User main account address (0x...).")
    p.add_argument("--builder-account-id", help="Builder main account address (0x...).")
    p.add_argument("--builder-api-signer-privkey", help="Fresh signer privkey used by builder on behalf of user.")
    p.add_argument("--permissions", default="Trade", help='Use "Trade" (recommended by docs).')
    p.add_argument("--builder-api-key-label", default="builder-smoke-test")
    p.add_argument("--max-futures-fee-rate", default="0.001")
    p.add_argument("--max-spot-fee-rate", default="0.0001")
    args = p.parse_args()

    env = ENVS[args.env]
    api_key = args.api_key

    if args.authorize:
        missing = [k for k in ["user_privkey", "main_account_id", "builder_account_id", "builder_api_signer_privkey"]
                   if getattr(args, k) in (None, "")]
        if missing:
            print(f"Missing required args for --authorize: {', '.join(missing)}", file=sys.stderr)
            return 2

        api_key = authorize_builder(
            env,
            main_account_id=args.main_account_id,
            builder_account_id=args.builder_account_id,
            user_privkey=args.user_privkey,
            builder_api_key_signer_privkey=args.builder_api_signer_privkey,
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
