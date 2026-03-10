/**
 * GRVT Order Creation Script with API Key Authentication
 *
 * This script creates orders on GRVT Trading API using API Key authentication.
 * It combines the authentication flow from authorize.ts with order signing.
 *
 * Usage:
 *   npx tsx src/grvt_create_order_api.ts --env testnet \
 *     --api-key YOUR_API_KEY --private-key YOUR_PRIVATE_KEY
 *
 * Flow:
 * 1. Login with API key to get session cookie and account ID
 * 2. Load order data from JSON file
 * 3. Sign the order using EIP-712 signature
 * 4. Submit the order to the Trading API
 * 5. Display the order response
 *
 * Install:
 *   npm install
 */

import { Command } from "commander";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { ethers } from "ethers";

import {
  EnvConfig,
  ENVS,
  getServerTimeNs,
  loginWithApiKey,
  printHttp,
} from "./grvt_common.js";

// ---------------------------------------------------------------------------
// Order-specific constants and types
// ---------------------------------------------------------------------------

enum TimeInForce {
  GOOD_TILL_TIME = "GOOD_TILL_TIME",
  ALL_OR_NONE = "ALL_OR_NONE",
  IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL",
  FILL_OR_KILL = "FILL_OR_KILL",
}

const SIGN_TIME_IN_FORCE: Record<TimeInForce, number> = {
  [TimeInForce.GOOD_TILL_TIME]: 1,
  [TimeInForce.ALL_OR_NONE]: 2,
  [TimeInForce.IMMEDIATE_OR_CANCEL]: 3,
  [TimeInForce.FILL_OR_KILL]: 4,
};

const PRICE_MULTIPLIER = 1_000_000_000n;

const EIP712_ORDER_TYPES = {
  OrderWithBuilderFee: [
    { name: "subAccountID", type: "uint64" },
    { name: "isMarket", type: "bool" },
    { name: "timeInForce", type: "uint8" },
    { name: "postOnly", type: "bool" },
    { name: "reduceOnly", type: "bool" },
    { name: "legs", type: "OrderLeg[]" },
    { name: "builder", type: "address" },
    { name: "builderFee", type: "uint32" },
    { name: "nonce", type: "uint32" },
    { name: "expiration", type: "int64" },
  ],
  OrderLeg: [
    { name: "assetID", type: "uint256" },
    { name: "contractSize", type: "uint64" },
    { name: "limitPrice", type: "uint64" },
    { name: "isBuyingContract", type: "bool" },
  ],
};

// ---------------------------------------------------------------------------
// Instrument types
// ---------------------------------------------------------------------------

interface InstrumentMeta {
  instrument_hash: string;
  base_decimals: number;
}

// ---------------------------------------------------------------------------
// Instruments
// ---------------------------------------------------------------------------

async function fetchInstrumentsFromApi(
  env: EnvConfig
): Promise<Record<string, InstrumentMeta>> {
  const url = `${env.marketDataBase}/full/v1/all_instruments`;
  console.log(`\nFetching instruments from ${env.name} environment...`);

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: true }),
    signal: AbortSignal.timeout(30_000),
  });

  if (!resp.ok) throw new Error(`Fetch instruments failed: ${resp.status}`);

  const data = (await resp.json()) as {
    result?: Array<{
      instrument: string;
      instrument_hash: string;
      base_decimals: number;
    }>;
  };

  const instruments: Record<string, InstrumentMeta> = {};
  for (const inst of data.result ?? []) {
    instruments[inst.instrument] = {
      instrument_hash: inst.instrument_hash,
      base_decimals: inst.base_decimals,
    };
  }

  console.log(`Fetched ${Object.keys(instruments).length} instruments`);
  return instruments;
}

// ---------------------------------------------------------------------------
// Order signing
// ---------------------------------------------------------------------------

interface OrderLeg {
  instrument: string;
  size: string;
  limit_price: string;
  is_buying_asset: boolean;
}

interface OrderData {
  order: {
    sub_account_id: string;
    is_market?: boolean;
    time_in_force?: string;
    post_only?: boolean;
    reduce_only?: boolean;
    legs: OrderLeg[];
    signature: { expiration: string; nonce: number };
    metadata?: Record<string, unknown>;
    builder?: string;
    builder_fee?: string;
  };
}

function buildOrderMessageData(
  orderData: OrderData,
  instruments: Record<string, InstrumentMeta>
): Record<string, unknown> {
  const order = orderData.order;

  const legs = order.legs.map((leg) => {
    const inst = instruments[leg.instrument];
    if (!inst)
      throw new Error(
        `Instrument '${leg.instrument}' not found in instruments data`
      );

    const sizeMultiplier = 10n ** BigInt(inst.base_decimals);
    // Use BigInt arithmetic for precision
    const sizeInt = BigInt(
      Math.round(parseFloat(leg.size) * Number(sizeMultiplier))
    );
    const priceInt = BigInt(
      Math.round(parseFloat(leg.limit_price) * Number(PRICE_MULTIPLIER))
    );

    return {
      assetID: inst.instrument_hash,
      contractSize: sizeInt,
      limitPrice: priceInt,
      isBuyingContract: leg.is_buying_asset,
    };
  });

  const tifStr = (order.time_in_force ?? "GOOD_TILL_TIME") as TimeInForce;
  const signTif = SIGN_TIME_IN_FORCE[tifStr];

  const builderFeeInt = Math.round(
    parseFloat(order.builder_fee ?? "0.001") * 10000
  );

  return {
    subAccountID: BigInt(order.sub_account_id),
    isMarket: order.is_market ?? false,
    timeInForce: signTif,
    postOnly: order.post_only ?? false,
    reduceOnly: order.reduce_only ?? false,
    legs,
    builder: order.builder ?? "",
    builderFee: builderFeeInt,
    nonce: order.signature.nonce,
    expiration: BigInt(order.signature.expiration),
  };
}

async function signOrder(
  orderData: OrderData,
  instruments: Record<string, InstrumentMeta>,
  privateKey: string,
  env: EnvConfig
): Promise<Record<string, unknown>> {
  // Remove 0x prefix if present
  if (privateKey.startsWith("0x")) privateKey = privateKey.slice(2);

  const messageData = buildOrderMessageData(orderData, instruments);

  const domain: ethers.TypedDataDomain = {
    name: "GRVT Exchange",
    version: "0",
    chainId: env.chainId,
  };

  const wallet = new ethers.Wallet(privateKey);
  const rawSig = await wallet.signTypedData(domain, EIP712_ORDER_TYPES, messageData);
  const sig = ethers.Signature.from(rawSig);

  const signature = {
    r: "0x" + sig.r.slice(2).padStart(64, "0"),
    s: "0x" + sig.s.slice(2).padStart(64, "0"),
    v: sig.v,
    signer: wallet.address,
  };

  const order = { ...orderData.order };
  order.signature = {
    r: signature.r,
    s: signature.s,
    v: signature.v,
    expiration: order.signature.expiration,
    nonce: order.signature.nonce,
    signer: signature.signer,
  } as unknown as OrderData["order"]["signature"];

  return { order };
}

// ---------------------------------------------------------------------------
// Order creation
// ---------------------------------------------------------------------------

async function createOrder(
  env: EnvConfig,
  gravityCookie: string,
  accountId: string,
  orderPayload: Record<string, unknown>
): Promise<unknown> {
  const url = `${env.tradesBase}/full/v1/create_order`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Cookie: gravityCookie,
    "X-Grvt-Account-Id": accountId,
  };

  console.log(`\nSubmitting order to ${env.name} Trading API...`);
  console.log(`   Endpoint: ${url}`);
  console.log(JSON.stringify(orderPayload, null, 2));
  console.log(headers);

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(orderPayload),
    signal: AbortSignal.timeout(30_000),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    printHttp("Create Order Failed", resp, body);
    throw new Error(`Order creation failed with status ${resp.status}`);
  }

  console.log("Order submitted successfully!");
  return resp.json();
}

// ---------------------------------------------------------------------------
// File I/O
// ---------------------------------------------------------------------------

function loadJsonFile(filePath: string): OrderData {
  const content = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(content) as OrderData;
}

async function updateOrderSignatureFields(
  orderData: OrderData,
  env: EnvConfig,
  expirationHours: number = 24
): Promise<OrderData> {
  const expirationNs =
    (await getServerTimeNs(env)) +
    BigInt(expirationHours * 3600) * 1_000_000_000n;
  const nonce = crypto.randomInt(0, 2 ** 32);

  orderData.order.signature.expiration = expirationNs.toString();
  orderData.order.signature.nonce = nonce;
  return orderData;
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

async function main(): Promise<number> {
  const program = new Command();
  program
    .description(
      "Create orders on GRVT Trading API using API Key authentication"
    )
    .requiredOption("--api-key <key>", "API key for authentication")
    .requiredOption(
      "--private-key <key>",
      "Private key for signing orders (hex format)"
    )
    .option(
      "--env <env>",
      "GRVT environment (default: testnet)",
      "testnet"
    )
    .option(
      "--order-file <path>",
      "Path to order data JSON file",
      "create_order_data.json"
    )
    .option(
      "--update-expiration",
      "Update order expiration and nonce before signing"
    )
    .option(
      "--expiration-hours <hours>",
      "Hours until order expiration (default: 24)",
      "24"
    )
    .parse();

  const opts = program.opts<{
    env: string;
    apiKey: string;
    privateKey: string;
    orderFile: string;
    updateExpiration?: boolean;
    expirationHours: string;
  }>();

  try {
    const env = ENVS[opts.env];
    if (!env) {
      console.error(`Error: unknown environment "${opts.env}".`);
      return 2;
    }

    console.log("=".repeat(70));
    console.log("GRVT Order Creation with API Key Authentication");
    console.log("=".repeat(70));
    console.log(`Environment: ${env.name}`);

    // Step 1: Login with API key
    const [gravityCookie, accountId] = await loginWithApiKey(env, opts.apiKey);

    // Step 2: Fetch instruments
    const instruments = await fetchInstrumentsFromApi(env);

    // Step 3: Load order data
    const orderFilePath = path.resolve(opts.orderFile);
    console.log(`\nLoading order data from ${orderFilePath}...`);
    let orderData = loadJsonFile(orderFilePath);
    console.log("Order data loaded");

    // Step 4: Update signature fields if requested
    if (opts.updateExpiration) {
      console.log("\nUpdating order expiration and nonce...");
      orderData = await updateOrderSignatureFields(
        orderData,
        env,
        parseInt(opts.expirationHours, 10)
      );
      console.log("Updated expiration and nonce");
    }

    // Step 5: Sign the order
    console.log("\nSigning order with EIP-712 signature...");
    const signedOrder = await signOrder(orderData, instruments, opts.privateKey, env);
    console.log("Order signed");
    console.log(
      `   Signer: ${(signedOrder.order as Record<string, unknown> & { signature: { signer: string } }).signature.signer}`
    );

    // Step 6: Submit the order
    const result = await createOrder(env, gravityCookie, accountId, signedOrder);

    // Step 7: Display results
    console.log("\n" + "=".repeat(70));
    console.log("ORDER RESULT");
    console.log("=".repeat(70));
    console.log(JSON.stringify(result, null, 2));

    return 0;
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      console.error("\nOperation cancelled.");
      return 1;
    }
    console.error(`\nError: ${(err as Error).message}`);
    if (process.env.DEBUG) console.error(err);
    return 1;
  }
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
