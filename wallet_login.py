#!/usr/bin/env python3
"""
GRVT Wallet Login — EIP-712 authentication for the main signing wallet.

Calls POST /auth/wallet/login with a WalletLogin EIP-712 signature and
then optionally verifies the session by calling get_sub_accounts.

Flow:
1. Client signs WalletLogin(address address, uint32 nonce, int64 expiration)
   using the wallet private key (eth_signTypedData_v4 / EIP-712).
2. Client POSTs { address, signature: { signer, v, r, s, nonce, expiration, chain_id } }
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
from typing import Any, Dict, Optional, Tuple

import requests
from eth_account import Account

from grvt_common import (
    EnvConfig, ENVS, ensure_0x, parse_gravity_cookie, print_http,
    get_server_time_ns, sign_eip712, get_sub_accounts,
)

# Maximum signature lifetime the server will accept (5 minutes, in seconds).
# Use slightly less to account for clock skew and network latency.
_DEFAULT_EXPIRATION_SECS = 4 * 60  # 4 minutes


def build_eip712_payload(
    wallet_address: str,
    nonce_uint32: int,
    expiration_unix_ns: int,
    domain_chain_id: int,
) -> Dict[str, Any]:
    """
    Builds the EIP-712 typed data for WalletLogin.

    Primary type: WalletLogin(address address, uint32 nonce, int64 expiration)
    Domain:       GRVT Exchange / version 0 / chainId
    """
    return {
        "domain": {
            "name": "GRVT Exchange",
            "version": "0",
            "chainId": domain_chain_id,
        },
        "message": {
            "address": wallet_address,
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
                {"name": "address",    "type": "address"},
                {"name": "nonce",      "type": "uint32"},
                {"name": "expiration", "type": "int64"},
            ],
        },
    }


def wallet_login(
    env: EnvConfig,
    *,
    wallet_privkey: str,
    wallet_address: Optional[str] = None,
    expiration_secs: int = _DEFAULT_EXPIRATION_SECS,
) -> Tuple[str, str, str]:
    """
    Signs a WalletLogin EIP-712 message and calls POST /auth/wallet/login.

    Returns: (gravity_cookie, x_grvt_account_id, funding_account_address)

    funding_account_address is the user's main account (chain account address)
    returned in the response body — use it as main_account_id in authorize_builder().

    The expiration must be ≤ now + 5 minutes (server-enforced).
    Defaults to 4 minutes to allow for clock skew.
    """
    wallet_privkey = ensure_0x(wallet_privkey)
    acct = Account.from_key(wallet_privkey)
    addr = ensure_0x(wallet_address if wallet_address else acct.address)

    nonce = secrets.randbelow(2**32)
    expiration_ns = get_server_time_ns(env) + expiration_secs * 1_000_000_000

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
            "signer": addr,
            "v": v,
            "r": r,
            "s": s,
            "nonce": nonce,
            "expiration": str(expiration_ns),
            "chain_id": str(env.chain_id),
        },
    }
    print(json.dumps(payload, indent=2))
    print(f"\nSigning as: {addr}")
    print(f"Nonce:      {nonce}")
    print(f"Expiration: {expiration_ns} ns (~{expiration_secs}s from server time)")

    resp = requests.post(url, json=payload, timeout=30)
    print_http("Wallet Login", resp)
    resp.raise_for_status()

    gravity_cookie = parse_gravity_cookie(resp.headers.get("set-cookie"))
    account_id = resp.headers.get("x-grvt-account-id")

    if not gravity_cookie:
        raise RuntimeError("Could not find gravity cookie in Set-Cookie response header.")
    if not account_id:
        raise RuntimeError("Could not find x-grvt-account-id in response headers.")

    # The response body contains the funding account address (chain account address).
    # This is the value to use as main_account_id in subsequent authorize calls.
    funding_account_address = resp.json().get("funding_account_address", "")

    return gravity_cookie, account_id, funding_account_address


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

    gravity_cookie, account_id, funding_account_address = wallet_login(
        env,
        wallet_privkey=args.wallet_privkey,
        wallet_address=args.wallet_address,
        expiration_secs=args.expiration_secs,
    )

    print(f"\nSession gravity cookie:   {gravity_cookie}")
    print(f"X-Grvt-Account-Id:        {account_id}")
    if funding_account_address:
        print(f"Funding account address:  {funding_account_address}")
        print(f"  (use as --main-account-id in authorize.py)")

    if args.no_verify:
        print("\n✅ Wallet login complete.")
        return 0

    subaccounts = get_sub_accounts(env, gravity_cookie, account_id)
    print(f"\nSub accounts: {subaccounts}")
    print("\n✅ Wallet login and session verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
