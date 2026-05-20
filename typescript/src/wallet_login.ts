/**
 * GRVT Wallet Login — EIP-712 authentication for the main signing wallet.
 *
 * Calls POST /auth/wallet/login with a WalletLogin EIP-712 signature and
 * then optionally verifies the session by calling get_sub_accounts.
 *
 * Flow:
 * 1. Client signs WalletLogin(address signer, uint32 nonce, int64 expiration)
 *    using the wallet private key (eth_signTypedData_v4 / EIP-712).
 * 2. Client POSTs { address, signature: { signer, v, r, s, nonce, expiration, chain_id } }
 *    to /auth/wallet/login.
 * 3. Server validates expiration (must be > now AND <= now + 5 minutes),
 *    verifies EIP-712 sig, atomically consumes nonce (replay prevention),
 *    and issues a session cookie.
 * 4. Script extracts the gravity session cookie and X-Grvt-Account-Id header.
 *
 * Key constraints (server-enforced):
 * - Expiration must be strictly in the future (nanoseconds).
 * - Expiration must be <= now + 5 minutes — the server rejects anything longer.
 * - Nonce is a client-chosen random uint32; identical (address, nonce) pairs
 *   are rejected within the signature's lifetime (Redis SETNX replay prevention).
 * - Wallet address must have the "0x" prefix.
 * - v must be 27 or 28.
 *
 * Install:
 *   npm install
 *
 * Examples:
 *
 * A) Login and verify session:
 *   npx tsx src/wallet_login.ts --env testnet \
 *     --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY
 *
 * B) Login only (print cookie, skip get_sub_accounts):
 *   npx tsx src/wallet_login.ts --env testnet \
 *     --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
 *     --no-verify
 *
 * C) Provide wallet address explicitly (derived from privkey if omitted):
 *   npx tsx src/wallet_login.ts --env testnet \
 *     --wallet-privkey 0xYOUR_WALLET_PRIVATE_KEY \
 *     --wallet-address 0xYOUR_WALLET_ADDRESS
 */

import { Command } from "commander";
import crypto from "node:crypto";
import { ethers } from "ethers";

import {
  EnvConfig,
  ENVS,
  ensure0x,
  parseGravityCookie,
  printHttp,
  getServerTimeNs,
  signEip712,
  getSubAccounts,
} from "./grvt_common.js";

// Maximum signature lifetime the server will accept (5 minutes, in seconds).
// Use slightly less to account for clock skew and network latency.
const DEFAULT_EXPIRATION_SECS = 4 * 60; // 4 minutes

// ---------------------------------------------------------------------------
// EIP-712 payload
// ---------------------------------------------------------------------------

export function buildEip712Payload(
  walletAddress: string,
  nonceUint32: number,
  expirationUnixNs: bigint,
  domainChainId: number
): Record<string, unknown> {
  return {
    domain: {
      name: "GRVT Exchange",
      version: "0",
      chainId: domainChainId,
    },
    message: {
      signer: walletAddress,
      nonce: nonceUint32,
      expiration: expirationUnixNs,
    },
    primaryType: "WalletLogin",
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
      ],
      WalletLogin: [
        { name: "signer", type: "address" },
        { name: "nonce", type: "uint32" },
        { name: "expiration", type: "int64" },
      ],
    },
  };
}

// ---------------------------------------------------------------------------
// Wallet login
// ---------------------------------------------------------------------------

export async function walletLogin(
  env: EnvConfig,
  opts: {
    walletPrivkey: string;
    walletAddress?: string;
    expirationSecs?: number;
  }
): Promise<[string, string, string]> {
  const expirationSecs = opts.expirationSecs ?? DEFAULT_EXPIRATION_SECS;
  const privkey = ensure0x(opts.walletPrivkey);
  const wallet = new ethers.Wallet(privkey);
  const addr = ensure0x(opts.walletAddress ?? wallet.address);

  const nonce = crypto.randomInt(0, 2 ** 32);
  const expirationNs =
    (await getServerTimeNs(env)) + BigInt(expirationSecs) * 1_000_000_000n;

  const typed = buildEip712Payload(addr, nonce, expirationNs, env.chainId);

  const { v, r, s } = await signEip712(privkey, typed as Parameters<typeof signEip712>[1]);

  const url = `${env.edgeBase}/auth/wallet/login`;
  const payload = {
    address: addr,
    signature: {
      signer: addr,
      v,
      r,
      s,
      nonce,
      expiration: expirationNs.toString(),
      chain_id: String(env.chainId),
    },
  };

  console.log(JSON.stringify(payload, null, 2));
  console.log(`\nSigning as: ${addr}`);
  console.log(`Nonce:      ${nonce}`);
  console.log(
    `Expiration: ${expirationNs} ns (~${expirationSecs}s from server time)`
  );

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });

  const body = (await resp.json()) as Record<string, unknown>;
  printHttp("Wallet Login", resp, body);

  if (!resp.ok) throw new Error(`Wallet Login failed: ${resp.status}`);

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

  const fundingAccountAddress =
    (body.funding_account_address as string) ?? "";

  return [gravityCookie, accountId, fundingAccountAddress];
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

async function main(): Promise<number> {
  const program = new Command();
  program
    .description(
      "Login to GRVT using an EIP-712 wallet signature (POST /auth/wallet/login)."
    )
    .requiredOption(
      "--wallet-privkey <key>",
      "Main wallet private key (0x...). Used to sign the WalletLogin EIP-712 message."
    )
    .option(
      "--env <env>",
      "Target environment (staging/testnet/prod).",
      "testnet"
    )
    .option(
      "--wallet-address <addr>",
      "Wallet address (0x...). Derived from --wallet-privkey if not provided."
    )
    .option(
      "--expiration-secs <secs>",
      `Seconds until the signature expires (max 300 / 5 min, default ${DEFAULT_EXPIRATION_SECS}).`,
      String(DEFAULT_EXPIRATION_SECS)
    )
    .option(
      "--no-verify",
      "Skip the get_sub_accounts verification step after login."
    )
    .parse();

  const opts = program.opts<{
    env: string;
    walletPrivkey: string;
    walletAddress?: string;
    expirationSecs: string;
    verify: boolean;
  }>();

  const expirationSecs = parseInt(opts.expirationSecs, 10);
  if (expirationSecs > 300) {
    console.error(
      "Error: --expiration-secs cannot exceed 300 (5 minutes, server-enforced)."
    );
    return 2;
  }

  const env = ENVS[opts.env];
  if (!env) {
    console.error(`Error: unknown environment "${opts.env}".`);
    return 2;
  }

  const [gravityCookie, accountId, fundingAccountAddress] = await walletLogin(
    env,
    {
      walletPrivkey: opts.walletPrivkey,
      walletAddress: opts.walletAddress,
      expirationSecs,
    }
  );

  console.log(`\nSession gravity cookie:   ${gravityCookie}`);
  console.log(`X-Grvt-Account-Id:        ${accountId}`);
  if (fundingAccountAddress) {
    console.log(`Funding account address:  ${fundingAccountAddress}`);
    console.log(`  (use as --main-account-id in authorize.ts)`);
  }

  if (!opts.verify) {
    console.log("\nWallet login complete.");
    return 0;
  }

  const subaccounts = await getSubAccounts(env, gravityCookie, accountId);
  console.log(`\nSub accounts: ${JSON.stringify(subaccounts)}`);
  console.log("\nWallet login and session verification complete.");
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
