#!/usr/bin/env python3
"""
Shared utilities for GRVT builder scripts.
"""
from __future__ import annotations

import json
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
    market_data_base: str
    chain_id: int


ENVS: Dict[str, EnvConfig] = {
    "staging": EnvConfig("staging", "https://edge.staging.gravitymarkets.io", "https://trades.staging.gravitymarkets.io", "https://market-data.staging.gravitymarkets.io", 327),
    "testnet": EnvConfig("testnet", "https://edge.testnet.grvt.io",           "https://trades.testnet.grvt.io",           "https://market-data.testnet.grvt.io",           326),
    "prod":    EnvConfig("prod",    "https://edge.grvt.io",                   "https://trades.grvt.io",                   "https://market-data.grvt.io",                   325),
}


def ensure_0x(s: str) -> str:
    """Ensure a hex string has a lowercase 0x prefix."""
    s = s.strip()
    s = s if s.startswith("0x") else "0x" + s
    return s.lower()


def hex32(n: int) -> str:
    """Encode an integer as a 0x-prefixed 32-byte hex string."""
    return "0x" + n.to_bytes(32, "big").hex()


def parse_gravity_cookie(set_cookie_header: Optional[str]) -> Optional[str]:
    """Extract the gravity=... token from a Set-Cookie header value."""
    if not set_cookie_header:
        return None
    idx = set_cookie_header.lower().find("gravity=")
    if idx == -1:
        return None
    frag = set_cookie_header[idx:]
    end = frag.find(";")
    return frag if end == -1 else frag[:end]


def print_http(title: str, resp: requests.Response) -> None:
    """Print HTTP request/response details for debugging."""
    print(f"\n== {title} ==")
    print(f"URL: {resp.request.method} {resp.request.url}")
    print(f"Status: {resp.status_code}")
    ct = resp.headers.get("content-type", "")
    if ct:
        print(f"Content-Type: {ct}")
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


def get_server_time_ns(env: EnvConfig) -> int:
    """Fetch current server time from GET /time and return it in nanoseconds."""
    resp = requests.get(f"{env.market_data_base}/time", timeout=10)
    resp.raise_for_status()
    server_time_ms = resp.json()["server_time"]
    return server_time_ms * 1_000_000


def sign_eip712(privkey: str, typed_data: Dict[str, Any]) -> Tuple[int, str, str]:
    """Sign EIP-712 typed data and return (v, r_hex, s_hex)."""
    if encode_typed_data is None and encode_structured_data is None:
        raise RuntimeError(
            "eth-account is missing encode_typed_data/encode_structured_data; "
            "try: pip install --upgrade eth-account"
        )
    privkey = ensure_0x(privkey)
    acct = Account.from_key(privkey)
    if encode_typed_data is not None:
        msg = encode_typed_data(full_message=typed_data)
    else:
        msg = encode_structured_data(primitive=typed_data)
    signed = acct.sign_message(msg)
    return int(signed.v), hex32(int(signed.r)), hex32(int(signed.s))


def login_with_api_key(env: EnvConfig, api_key: str) -> Tuple[str, str]:
    """
    Login with API key to get session cookie and account ID.

    Returns:
        Tuple of (gravity_cookie, x_grvt_account_id)
    """
    url = f"{env.edge_base}/auth/api_key/login"
    headers = {"Content-Type": "application/json", "Cookie": "rm=true;"}
    resp = requests.post(url, headers=headers, json={"api_key": api_key}, timeout=30)
    print_http("API Key Login", resp)
    resp.raise_for_status()
    gravity_cookie = parse_gravity_cookie(resp.headers.get("set-cookie"))
    account_id = resp.headers.get("x-grvt-account-id")
    if not gravity_cookie:
        raise RuntimeError("Could not find gravity cookie in Set-Cookie response header.")
    if not account_id:
        raise RuntimeError("Could not find x-grvt-account-id in response headers.")
    return gravity_cookie, account_id


def get_sub_accounts(env: EnvConfig, gravity_cookie: str, x_grvt_account_id: str) -> Dict[str, Any]:
    """Call POST /full/v1/get_sub_accounts to verify the session."""
    url = f"{env.trades_base}/full/v1/get_sub_accounts"
    headers = {
        "Content-Type": "application/json",
        "Cookie": gravity_cookie,
        "X-Grvt-Account-Id": x_grvt_account_id,
    }
    resp = requests.post(url, headers=headers, json={}, timeout=30)
    print_http("Get Sub Accounts", resp)
    resp.raise_for_status()
    return resp.json()
