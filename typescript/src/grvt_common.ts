/**
 * Shared utilities for GRVT builder scripts.
 */

import { ethers } from "ethers";

// ---------------------------------------------------------------------------
// Environment configuration
// ---------------------------------------------------------------------------

export interface EnvConfig {
  name: string;
  edgeBase: string;
  tradesBase: string;
  marketDataBase: string;
  chainId: number;
}

export const ENVS: Record<string, EnvConfig> = {
  dev: {
    name: "dev",
    edgeBase: "https://edge.dev.gravitymarkets.io",
    tradesBase: "https://trades.dev.gravitymarkets.io",
    marketDataBase: "https://market-data.dev.gravitymarkets.io",
    chainId: 327,
  },
  staging: {
    name: "staging",
    edgeBase: "https://edge.staging.gravitymarkets.io",
    tradesBase: "https://trades.staging.gravitymarkets.io",
    marketDataBase: "https://market-data.staging.gravitymarkets.io",
    chainId: 327,
  },
  testnet: {
    name: "testnet",
    edgeBase: "https://edge.testnet.grvt.io",
    tradesBase: "https://trades.testnet.grvt.io",
    marketDataBase: "https://market-data.testnet.grvt.io",
    chainId: 326,
  },
  prod: {
    name: "prod",
    edgeBase: "https://edge.grvt.io",
    tradesBase: "https://trades.grvt.io",
    marketDataBase: "https://market-data.grvt.io",
    chainId: 325,
  },
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/** Ensure a hex string has a lowercase 0x prefix. */
export function ensure0x(s: string): string {
  s = s.trim();
  if (!s.startsWith("0x")) s = "0x" + s;
  return s.toLowerCase();
}

/** Encode an integer as a 0x-prefixed 32-byte hex string. */
export function hex32(n: bigint): string {
  return "0x" + n.toString(16).padStart(64, "0");
}

/** Extract the gravity=... token from a Set-Cookie header value. */
export function parseGravityCookie(
  setCookieHeader: string | null | undefined
): string | null {
  if (!setCookieHeader) return null;
  const lower = setCookieHeader.toLowerCase();
  const idx = lower.indexOf("gravity=");
  if (idx === -1) return null;
  const frag = setCookieHeader.substring(idx);
  const end = frag.indexOf(";");
  return end === -1 ? frag : frag.substring(0, end);
}

/** Print HTTP request/response details for debugging. */
export function printHttp(
  title: string,
  resp: Response,
  body: unknown
): void {
  console.log(`\n== ${title} ==`);
  console.log(`URL: ${resp.url}`);
  console.log(`Status: ${resp.status}`);
  const ct = resp.headers.get("content-type");
  if (ct) console.log(`Content-Type: ${ct}`);
  const accountId = resp.headers.get("x-grvt-account-id");
  if (accountId) console.log(`X-Grvt-Account-Id: ${accountId}`);
  const cookie = resp.headers.get("set-cookie");
  if (cookie) console.log(`Set-Cookie: ${cookie}`);
  if (body && typeof body === "object") {
    console.log("JSON:");
    console.log(JSON.stringify(body, null, 2));
  }
}

// ---------------------------------------------------------------------------
// Server time
// ---------------------------------------------------------------------------

/** Fetch current server time from GET /time and return it in nanoseconds. */
export async function getServerTimeNs(env: EnvConfig): Promise<bigint> {
  const resp = await fetch(`${env.marketDataBase}/time`, {
    signal: AbortSignal.timeout(10_000),
  });
  if (!resp.ok) throw new Error(`GET /time failed: ${resp.status}`);
  const data = (await resp.json()) as { server_time: number };
  return BigInt(data.server_time) * 1_000_000n;
}

// ---------------------------------------------------------------------------
// EIP-712 signing
// ---------------------------------------------------------------------------

/** Sign EIP-712 typed data and return { v, r, s }. */
export async function signEip712(
  privkey: string,
  typedData: {
    domain: Record<string, unknown>;
    types: Record<string, Array<{ name: string; type: string }>>;
    primaryType: string;
    message: Record<string, unknown>;
  }
): Promise<{ v: number; r: string; s: string }> {
  privkey = ensure0x(privkey);
  const wallet = new ethers.Wallet(privkey);

  // ethers v6 signTypedData expects (domain, types, value)
  // We need to remove EIP712Domain from types as ethers handles it automatically
  const { EIP712Domain: _, ...types } = typedData.types;

  const rawSig = await wallet.signTypedData(
    typedData.domain as ethers.TypedDataDomain,
    types,
    typedData.message
  );

  const sig = ethers.Signature.from(rawSig);
  return {
    v: sig.v,
    r: hex32(BigInt(sig.r)),
    s: hex32(BigInt(sig.s)),
  };
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

/**
 * Login with API key to get session cookie and account ID.
 * Returns [gravityCookie, xGrvtAccountId].
 */
export async function loginWithApiKey(
  env: EnvConfig,
  apiKey: string
): Promise<[string, string]> {
  const url = `${env.edgeBase}/auth/api_key/login`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Cookie: "rm=true;" },
    body: JSON.stringify({ api_key: apiKey }),
    signal: AbortSignal.timeout(30_000),
  });

  const body = await resp.json();
  printHttp("API Key Login", resp, body);

  if (!resp.ok) throw new Error(`API Key Login failed: ${resp.status}`);

  const gravityCookie = parseGravityCookie(resp.headers.get("set-cookie"));
  const accountId = resp.headers.get("x-grvt-account-id");

  if (!gravityCookie)
    throw new Error(
      "Could not find gravity cookie in Set-Cookie response header."
    );
  if (!accountId)
    throw new Error(
      "Could not find x-grvt-account-id in response headers."
    );

  return [gravityCookie, accountId];
}

/** Call POST /full/v1/get_sub_accounts to verify the session. */
export async function getSubAccounts(
  env: EnvConfig,
  gravityCookie: string,
  xGrvtAccountId: string
): Promise<unknown> {
  const url = `${env.tradesBase}/full/v1/get_sub_accounts`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Cookie: gravityCookie,
      "X-Grvt-Account-Id": xGrvtAccountId,
    },
    body: JSON.stringify({}),
    signal: AbortSignal.timeout(30_000),
  });

  const body = await resp.json();
  printHttp("Get Sub Accounts", resp, body);

  if (!resp.ok)
    throw new Error(`Get Sub Accounts failed: ${resp.status}`);

  return body;
}
