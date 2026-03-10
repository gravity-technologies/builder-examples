/**
 * GRVT Builder Codes / Trading API smoke test
 *
 * What this script can do:
 * 1) (Optional) Authorize a builder for a user WITH API key creation
 *    (EIP-712 AddAccountSignerWithBuilder) -> returns an api_key
 * 2) (Optional) Authorize a builder for a user WITHOUT API key creation
 *    (EIP-712 AuthorizeBuilder) -> no api_key returned
 * 3) Login with api_key -> returns session cookie (gravity=...) + X-Grvt-Account-Id header
 * 4) Call Trading API: full/v1/get_sub_accounts (authenticated) -> prints subaccounts
 *
 * Install:
 *   npm install
 *
 * Examples:
 *
 * A) If you already have an API key:
 *   npx tsx src/authorize.ts --env testnet --api-key YOUR_API_KEY
 *
 * B) Full flow with API key creation:
 *   npx tsx src/authorize.ts --env testnet \
 *     --authorize \
 *     --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
 *     --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
 *     --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
 *
 * C) Authorize builder without API key creation:
 *   npx tsx src/authorize.ts --env testnet \
 *     --authorize-only \
 *     --user-privkey 0xYOUR_USERS_MAIN_ACCOUNT_PRIVKEY \
 *     --main-account-id 0xUSERS_MAIN_ACCOUNT_ADDRESS \
 *     --builder-account-id 0xYOUR_BUILDER_MAIN_ACCOUNT_ADDRESS
 */

import { Command } from "commander";
import crypto from "node:crypto";
import { ethers } from "ethers";

import {
  EnvConfig,
  ENVS,
  ensure0x,
  getServerTimeNs,
  signEip712,
  loginWithApiKey,
  getSubAccounts,
  printHttp,
} from "./grvt_common.js";

// ---------------------------------------------------------------------------
// EIP-712 payloads
// ---------------------------------------------------------------------------

export function buildEip712Payload(
  mainAccountId: string,
  builderAccountId: string,
  signerAddress: string,
  permissions: string,
  maxFutureFeeRateUint32: number,
  maxSpotFeeRateUint32: number,
  nonceUint32: number,
  expirationUnixNs: bigint,
  domainChainId: number
): Record<string, unknown> {
  return {
    domain: { chainId: domainChainId, name: "GRVT Exchange", version: "0" },
    message: {
      accountID: mainAccountId,
      signer: signerAddress,
      permissions,
      builderAccountID: builderAccountId,
      maxFutureFeeRate: maxFutureFeeRateUint32,
      maxSpotFeeRate: maxSpotFeeRateUint32,
      nonce: nonceUint32,
      expiration: expirationUnixNs,
    },
    primaryType: "AddAccountSignerWithBuilder",
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
      ],
      AddAccountSignerWithBuilder: [
        { name: "accountID", type: "address" },
        { name: "signer", type: "address" },
        { name: "permissions", type: "string" },
        { name: "builderAccountID", type: "address" },
        { name: "maxFutureFeeRate", type: "uint32" },
        { name: "maxSpotFeeRate", type: "uint32" },
        { name: "nonce", type: "uint32" },
        { name: "expiration", type: "int64" },
      ],
    },
  };
}

export function buildEip712PayloadAuthorizeOnly(
  mainAccountId: string,
  builderAccountId: string,
  maxFutureFeeRateUint32: number,
  maxSpotFeeRateUint32: number,
  nonceUint32: number,
  expirationUnixNs: bigint,
  domainChainId: number
): Record<string, unknown> {
  return {
    domain: { chainId: domainChainId, name: "GRVT Exchange", version: "0" },
    message: {
      mainAccountID: mainAccountId,
      builderAccountID: builderAccountId,
      maxFutureFeeRate: maxFutureFeeRateUint32,
      maxSpotFeeRate: maxSpotFeeRateUint32,
      nonce: nonceUint32,
      expiration: expirationUnixNs,
    },
    primaryType: "AuthorizeBuilder",
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
      ],
      AuthorizeBuilder: [
        { name: "mainAccountID", type: "address" },
        { name: "builderAccountID", type: "address" },
        { name: "maxFutureFeeRate", type: "uint32" },
        { name: "maxSpotFeeRate", type: "uint32" },
        { name: "nonce", type: "uint32" },
        { name: "expiration", type: "int64" },
      ],
    },
  };
}

// ---------------------------------------------------------------------------
// Authorize with API key creation
// ---------------------------------------------------------------------------

export async function authorizeBuilder(
  env: EnvConfig,
  opts: {
    mainAccountId: string;
    builderAccountId: string;
    userPrivkey: string;
    builderApiKeySignerPrivkey: string;
    builderApiKeyLabel?: string;
    permissions?: string;
    maxFuturesFeeRate?: string;
    maxSpotFeeRate?: string;
  }
): Promise<string> {
  const signerPrivkey = ensure0x(opts.builderApiKeySignerPrivkey);
  const signerAddr = new ethers.Wallet(signerPrivkey).address;

  const userPrivkey = ensure0x(opts.userPrivkey);
  const userAddress = new ethers.Wallet(userPrivkey).address;

  const maxFuturesFeeRate = opts.maxFuturesFeeRate ?? "0.001";
  const maxSpotFeeRate = opts.maxSpotFeeRate ?? "0.0001";
  const permissions = opts.permissions ?? "Trade";
  const label = opts.builderApiKeyLabel ?? "builder-smoke-test";

  const mfUint32 = Math.floor(parseFloat(maxFuturesFeeRate) * 10_000);
  const msUint32 = Math.floor(parseFloat(maxSpotFeeRate) * 10_000);

  const nonce = crypto.randomInt(0, 2 ** 32);
  const expirationNs =
    (await getServerTimeNs(env)) +
    BigInt(7 * 24 * 3600) * 1_000_000_000n; // 7 days

  const typed = buildEip712Payload(
    ensure0x(opts.mainAccountId),
    ensure0x(opts.builderAccountId),
    ensure0x(signerAddr),
    permissions,
    mfUint32,
    msUint32,
    nonce,
    expirationNs,
    env.chainId
  );

  const { v, r, s } = await signEip712(userPrivkey, typed as Parameters<typeof signEip712>[1]);

  const url = `${env.edgeBase}/auth/builder/authorize`;
  const payload = {
    main_account_id: ensure0x(opts.mainAccountId),
    builder_account_id: ensure0x(opts.builderAccountId),
    max_futures_fee_rate: maxFuturesFeeRate,
    max_spot_fee_rate: maxSpotFeeRate,
    signature: {
      signer: ensure0x(userAddress),
      r,
      s,
      v,
      expiration: expirationNs.toString(),
      nonce,
      chain_id: String(env.chainId),
    },
    builder_api_key_label: label,
    builder_api_key_signer: ensure0x(signerAddr),
    builder_api_key_permissions: permissions,
  };

  console.log(JSON.stringify(payload));

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });

  const body = (await resp.json()) as Record<string, unknown>;
  printHttp("Authorize Builder", resp, body);

  if (!resp.ok) throw new Error(`Authorize Builder failed: ${resp.status}`);

  const apiKey = body.api_key as string | undefined;
  if (!apiKey) throw new Error("authorize response missing api_key");
  return apiKey;
}

// ---------------------------------------------------------------------------
// Authorize without API key creation
// ---------------------------------------------------------------------------

export async function authorizeBuilderOnly(
  env: EnvConfig,
  opts: {
    mainAccountId: string;
    builderAccountId: string;
    userPrivkey: string;
    maxFuturesFeeRate?: string;
    maxSpotFeeRate?: string;
  }
): Promise<void> {
  const userPrivkey = ensure0x(opts.userPrivkey);
  const userAddress = new ethers.Wallet(userPrivkey).address;

  const maxFuturesFeeRate = opts.maxFuturesFeeRate ?? "0.001";
  const maxSpotFeeRate = opts.maxSpotFeeRate ?? "0.0001";

  const mfUint32 = Math.floor(parseFloat(maxFuturesFeeRate) * 10_000);
  const msUint32 = Math.floor(parseFloat(maxSpotFeeRate) * 10_000);

  const nonce = crypto.randomInt(0, 2 ** 32);
  const expirationNs =
    (await getServerTimeNs(env)) +
    BigInt(7 * 24 * 3600) * 1_000_000_000n;

  const typed = buildEip712PayloadAuthorizeOnly(
    ensure0x(opts.mainAccountId),
    ensure0x(opts.builderAccountId),
    mfUint32,
    msUint32,
    nonce,
    expirationNs,
    env.chainId
  );

  const { v, r, s } = await signEip712(userPrivkey, typed as Parameters<typeof signEip712>[1]);

  const url = `${env.edgeBase}/auth/builder/authorize`;
  const payload = {
    main_account_id: ensure0x(opts.mainAccountId),
    builder_account_id: ensure0x(opts.builderAccountId),
    max_futures_fee_rate: maxFuturesFeeRate,
    max_spot_fee_rate: maxSpotFeeRate,
    signature: {
      signer: ensure0x(userAddress),
      r,
      s,
      v,
      expiration: expirationNs.toString(),
      nonce,
      chain_id: String(env.chainId),
    },
  };

  console.log(JSON.stringify(payload));

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });

  const body = await resp.json();
  printHttp("Authorize Builder (no API key)", resp, body);

  if (!resp.ok)
    throw new Error(`Authorize Builder (no API key) failed: ${resp.status}`);
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

async function main(): Promise<number> {
  const program = new Command();
  program
    .option("--env <env>", "Target environment", "testnet")
    .option("--api-key <key>", "If provided, skips authorize step and logs in directly.")
    .option("--authorize", "Run builder authorize step to mint an API key.")
    .option("--authorize-only", "Authorize builder on-chain without creating an API key.")
    .option("--user-privkey <key>", "User main account private key (for EIP-712 builder authorize signature).")
    .option("--main-account-id <addr>", "User funding account address (0x...).")
    .option("--builder-account-id <addr>", "Builder funding account address (0x...).")
    .option("--builder-api-signer-privkey <key>", "Fresh signer privkey used by builder on behalf of user.")
    .option("--permissions <perms>", 'Use "Trade" (recommended by docs).', "Trade")
    .option("--builder-api-key-label <label>", "Label for the API key.", "builder-smoke-test")
    .option("--max-futures-fee-rate <rate>", "Max futures fee rate.", "0.001")
    .option("--max-spot-fee-rate <rate>", "Max spot fee rate.", "0.0001")
    .parse();

  const opts = program.opts<{
    env: string;
    apiKey?: string;
    authorize?: boolean;
    authorizeOnly?: boolean;
    userPrivkey?: string;
    mainAccountId?: string;
    builderAccountId?: string;
    builderApiSignerPrivkey?: string;
    permissions: string;
    builderApiKeyLabel: string;
    maxFuturesFeeRate: string;
    maxSpotFeeRate: string;
  }>();

  const env = ENVS[opts.env];
  if (!env) {
    console.error(`Error: unknown environment "${opts.env}".`);
    return 2;
  }

  let apiKey = opts.apiKey;

  if (opts.authorizeOnly) {
    const missing = (["userPrivkey", "mainAccountId", "builderAccountId"] as const).filter(
      (k) => !opts[k]
    );
    if (missing.length) {
      console.error(`Missing required args for --authorize-only: ${missing.join(", ")}`);
      return 2;
    }

    await authorizeBuilderOnly(env, {
      mainAccountId: opts.mainAccountId!,
      builderAccountId: opts.builderAccountId!,
      userPrivkey: opts.userPrivkey!,
      maxFuturesFeeRate: opts.maxFuturesFeeRate,
      maxSpotFeeRate: opts.maxSpotFeeRate,
    });

    console.log("\nBuilder authorized (no API key created).");
    return 0;
  }

  if (opts.authorize) {
    const missing = (["userPrivkey", "mainAccountId", "builderAccountId"] as const).filter(
      (k) => !opts[k]
    );
    if (missing.length) {
      console.error(`Missing required args for --authorize: ${missing.join(", ")}`);
      return 2;
    }

    // Generate a new keypair if builder_api_signer_privkey is not provided
    let builderApiSignerPrivkey = opts.builderApiSignerPrivkey;
    if (!builderApiSignerPrivkey) {
      const newWallet = ethers.Wallet.createRandom();
      builderApiSignerPrivkey = newWallet.privateKey;
      console.log(`\nGenerated new builder API signer keypair:`);
      console.log(`   Private Key: ${builderApiSignerPrivkey}`);
      console.log(`   Address: ${newWallet.address}`);
      console.log(
        "   Save this private key securely - you'll need it to use the API key!\n"
      );
    }

    apiKey = await authorizeBuilder(env, {
      mainAccountId: opts.mainAccountId!,
      builderAccountId: opts.builderAccountId!,
      userPrivkey: opts.userPrivkey!,
      builderApiKeySignerPrivkey: builderApiSignerPrivkey,
      builderApiKeyLabel: opts.builderApiKeyLabel,
      permissions: opts.permissions,
      maxFuturesFeeRate: opts.maxFuturesFeeRate,
      maxSpotFeeRate: opts.maxSpotFeeRate,
    });

    console.log(`\nMinted api_key: ${apiKey}`);
  }

  if (!apiKey) {
    console.error(
      "Provide --api-key or run with --authorize (and required args)."
    );
    return 2;
  }

  const [gravityCookie, accountId] = await loginWithApiKey(env, apiKey);
  console.log(`\nSession gravity cookie: ${gravityCookie}`);
  console.log(`X-Grvt-Account-Id: ${accountId}`);

  const subaccounts = await getSubAccounts(env, gravityCookie, accountId);
  console.log(`Sub accounts: ${JSON.stringify(subaccounts)}`);
  console.log("\nSmoke test complete.");
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
