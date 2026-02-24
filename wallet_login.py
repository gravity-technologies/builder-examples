#!/usr/bin/env python3
"""
GRVT Wallet Login — EIP-712 authentication for the main signing wallet.

Calls POST /auth/wallet/login with a WalletLogin EIP-712 signature and
then optionally verifies the session by calling get_sub_accounts.

Flow:
1. Client signs WalletLogin(address signer, uint32 nonce, int64 expiration)
   using the wallet private key (eth_signTypedData_v4 / EIP-712).
2. Client POSTs { address, signature: { v, r, s, nonce, expiration, chainID } }
   to /auth/wallet/login.
3. Server validates expiration (must be > now AND ≤ now + 5 minutes),
   verifies EIP-712 sig, atomically consumes nonce (replay prevention),
   and issues a session cookie.
4. Script extracts the gravity session cookie and X-Grvt-Account-Id header.

Key constraints (server-enforced):
- Expiration must be strictly in the future (nanoseconds).
- Expiration must be ≤ now + 5 minutes — the server rejects anything longer.
- Nonce is a client-chosen random uint32; identical (address, nonce) pairs
  are rejected within the signature's lifetime (Redis SETNX replay prevention).
- Wallet address must have the "0x" prefix.
- v must be 27 or 28.

Install:
  pip install requests eth-account

Examples:

A) Login and verify session:
  python wallet_login.py --env testnet \\
    --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY

B) Login only (print cookie, skip get_sub_accounts):
  python wallet_login.py --env testnet \\
    --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \\
    --no-verify

C) Provide wallet address explicitly (derived from privkey if omitted):
  python wallet_login.py --env testnet \\
    --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \\
    --wallet-address 0xYOUR_WALLET_ADDRESS
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

from eth_account import Account
try:
    from eth_account.messages import encode_typed_data  # eth-account >= 0.9
except Exception:  # pragma: no cover
    encode_typed_data = None
try:
    from eth_account.messages import encode_structured_data  # older fallback
except Exception:  # pragma: no cover
    encode_structured_data = None


@dataclass(frozen=True)
class EnvConfig:
    name: str
    edge_base: str
    trades_base: str
    chain_id: int


ENVS: Dict[str, EnvConfig] = {
    "dev":     EnvConfig("dev",     "https://edge.dev.gravitymarkets.io",     "https://trades.dev.gravitymarkets.io",     327),
    "staging": EnvConfig("staging", "https://edge.staging.gravitymarkets.io", "https://trades.staging.gravitymarkets.io", 327),
    "testnet": EnvConfig("testnet", "https://edge.testnet.grvt.io",            "https://trades.testnet.grvt.io",           326),
    "prod":    EnvConfig("prod",    "https://edge.grvt.io",                   "https://trades.grvt.io",                   325),
}

# Maximum signature lifetime the server will accept (5 minutes, in seconds).
# Use slightly less to account for clock skew and network latency.
_DEFAULT_EXPIRATION_SECS = 4 * 60  # 4 minutes


def _ensure_0x(s: str) -> str:
    s = s.strip()
    return s if s.startswith("0x") else "0x" + s


def _hex32(n: int) -> str:
    return "0x" + n.to_bytes(32, "big").hex()


def _parse_gravity_cookie(set_cookie_header: Optional[str]) -> Optional[str]:
    if not set_cookie_header:
        return None
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
    if resp.headers.get("x-grvt-account-id"):
        print(f"X-Grvt-Account-Id: {resp.headers.get('x-grvt-account-id')}")
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
    wallet_address: str,
    nonce_uint32: int,
    expiration_unix_ns: int,
    domain_chain_id: int,
) -> Dict[str, Any]:
    """
    Builds the EIP-712 typed data for WalletLogin.

    Primary type: WalletLogin(address signer, uint32 nonce, int64 expiration)
    Domain:       GRVT Exchange / version 0 / chainId
    """
    return {
        "domain": {
            "name": "GRVT Exchange",
            "version": "0",
            "chainId": domain_chain_id,
        },
        "message": {
            "signer": wallet_address,
            "nonce": nonce_uint32,
            "expiration": expiration_unix_ns,
        },
        "primaryType": "WalletLogin",
        "types": {
            "EIP712Domain": [
                {"name": "name",    "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "WalletLogin": [
                {"name": "signer",     "type": "address"},
                {"name": "nonce",      "type": "uint32"},
                {"name": "expiration", "type": "int64"},
            ],
        },
    }


def sign_eip712(privkey: str, typed_data: Dict[str, Any]) -> Tuple[int, str, str]:
    """Signs EIP-712 typed data and returns (v, r_hex, s_hex)."""
    if encode_typed_data is None and encode_structured_data is None:
        raise RuntimeError(
            "eth-account is missing encode_typed_data/encode_structured_data; "
            "try: pip install --upgrade eth-account"
        )

    privkey = _ensure_0x(privkey)
    acct = Account.from_key(privkey)

    if encode_typed_data is not None:
        msg = encode_typed_data(full_message=typed_data)
    else:
        msg = encode_structured_data(primitive=typed_data)

    signed = acct.sign_message(msg)
    v = int(signed.v)
    r = _hex32(int(signed.r))
    s = _hex32(int(signed.s))
    return v, r, s


def wallet_login(
    env: EnvConfig,
    *,
    wallet_privkey: str,
    wallet_address: Optional[str] = None,
    expiration_secs: int = _DEFAULT_EXPIRATION_SECS,
) -> Tuple[str, str]:
    """
    Signs a WalletLogin EIP-712 message and calls POST /auth/wallet/login.

    Returns: (gravity_cookie, x_grvt_account_id)

    The expiration must be ≤ now + 5 minutes (server-enforced).
    Defaults to 4 minutes to allow for clock skew.
    """
    wallet_privkey = _ensure_0x(wallet_privkey)
    acct = Account.from_key(wallet_privkey)
    addr = _ensure_0x(wallet_address if wallet_address else acct.address)

    nonce = secrets.randbelow(2**32)
    expiration_ns = int((time.time() + expiration_secs) * 1e9)

    typed = build_eip712_payload(
        wallet_address=addr,
        nonce_uint32=nonce,
        expiration_unix_ns=expiration_ns,
        domain_chain_id=env.chain_id,
    )

    v, r, s = sign_eip712(wallet_privkey, typed)

    url = f"{env.edge_base}/auth/wallet/login"
    payload = {
        "address": addr,
        "signature": {
            "v": v,
            "r": r,
            "s": s,
            "nonce": nonce,
            "expiration": expiration_ns,
            "chainID": env.chain_id,
        },
    }
    print(f"\nSigning as: {addr}")
    print(f"Nonce:      {nonce}")
    print(f"Expiration: {expiration_ns} ns (~{expiration_secs}s from now)")

    resp = requests.post(url, json=payload, timeout=30)
    _print_http("Wallet Login", resp)
    resp.raise_for_status()

    gravity_cookie = _parse_gravity_cookie(resp.headers.get("set-cookie"))
    account_id = resp.headers.get("x-grvt-account-id")

    if not gravity_cookie:
        raise RuntimeError("Could not find gravity cookie in Set-Cookie response header.")
    if not account_id:
        raise RuntimeError("Could not find x-grvt-account-id in response headers.")

    return gravity_cookie, account_id


def get_sub_accounts(env: EnvConfig, gravity_cookie: str, x_grvt_account_id: str) -> Dict[str, Any]:
    """Calls POST /full/v1/get_sub_accounts to verify the session."""
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
    p = argparse.ArgumentParser(
        description="Login to GRVT using an EIP-712 wallet signature (POST /auth/wallet/login)."
    )
    p.add_argument("--env", choices=ENVS.keys(), default="testnet",
                   help="Target environment (default: testnet).")
    p.add_argument("--wallet-privkey", required=True,
                   help="Main wallet private key (0x...). Used to sign the WalletLogin EIP-712 message.")
    p.add_argument("--wallet-address",
                   help="Wallet address (0x...). Derived from --wallet-privkey if not provided.")
    p.add_argument("--expiration-secs", type=int, default=_DEFAULT_EXPIRATION_SECS,
                   help=f"Seconds until the signature expires (max 300 / 5 min, default {_DEFAULT_EXPIRATION_SECS}).")
    p.add_argument("--no-verify", action="store_true",
                   help="Skip the get_sub_accounts verification step after login.")
    args = p.parse_args()

    if args.expiration_secs > 300:
        print("Error: --expiration-secs cannot exceed 300 (5 minutes, server-enforced).", file=sys.stderr)
        return 2

    env = ENVS[args.env]

    gravity_cookie, account_id = wallet_login(
        env,
        wallet_privkey=args.wallet_privkey,
        wallet_address=args.wallet_address,
        expiration_secs=args.expiration_secs,
    )

    print(f"\nSession gravity cookie: {gravity_cookie}")
    print(f"X-Grvt-Account-Id:      {account_id}")

    if args.no_verify:
        print("\n✅ Wallet login complete.")
        return 0

    subaccounts = get_sub_accounts(env, gravity_cookie, account_id)
    print(f"\nSub accounts: {subaccounts}")
    print("\n✅ Wallet login and session verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
