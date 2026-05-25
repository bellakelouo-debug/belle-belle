#!/usr/bin/env python3
"""
Overlayer Testnet Daily Tasks Bot
Automates all daily transactions on Ethereum Sepolia for the Overlayer testnet:
  - Faucet claim (7 Aave test tokens)
  - Mint T+ and C+ via OverlayerWrap
  - Stake T+ via StakedOverlayerWrap
  - Bridge C+ via LayerZero OFT to Base Sepolia
  - Send T+ (ERC-20 transfer)
  - Receive C+ (ERC-20 transfer)
  - Ensures at least 32 total transactions per cycle (mint, stake, or bridge)
Each task uses randomized amounts (slightly above minimum) so every account differs.
"""

import os
import sys
import time
import json
import random
import signal
import logging
import datetime
import struct
from pathlib import Path
from typing import Optional

try:
    from web3 import Web3
    from eth_account import Account
    from fake_useragent import UserAgent
    import requests
except ImportError:
    print("\n[!] Missing dependencies. Install with:")
    print("    pip install -r requirements.txt\n")
    sys.exit(1)


# ─── Constants ────────────────────────────────────────────────────────────────

SEPOLIA_CHAIN_ID = 11155111

# Aave GHO Sepolia Faucet
FAUCET_CONTRACT = "0xC959483DBa39aa9E78757139af0e9a2EDEb3f42D"

# Stablecoins on Sepolia (used as collateral)
USDT_SEPOLIA = "0xaA8E23Fb1079EA71e0a56F48a2aA51851D8433D0"
USDC_SEPOLIA = "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8"

# Overlayer T+ (USDT-based OverlayerWrap)
T_PLUS_CONTRACT = "0xe20534a32f9162488a90026F268a74fBE28d272D"
# Overlayer C+ (USDC-based OverlayerWrap)
C_PLUS_CONTRACT = "0xE815718D44694ec4637CB775C468d87f6e15B538"

# StakedOverlayerWrap for T+
STAKED_T_PLUS = "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82"
# StakedOverlayerWrap for C+
STAKED_C_PLUS = "0x753937137Eb92871A6F3517514d4f1Ee860e3FDF"

# LayerZero OFT bridge destination
BASE_SEPOLIA_EID = 40245

# ─── Daily Task Requirements ──────────────────────────────────────────────────
# Amounts are randomized between (min, max) per tx so every account differs.

# Mint T+ and C+: done 5-6 times each, 500-1000 per tx (faucet gives 10K USDT+USDC daily)
MINT_PER_TX        = (500, 1000)    # Amount per individual mint tx
MINT_T_COUNT       = (5, 6)         # How many T+ mint tx
MINT_C_COUNT       = (5, 6)         # How many C+ mint tx

# Other tasks: 1 tx each, slightly above minimum
TASK_STAKE_T_PLUS  = (113, 125)     # Stake T+
TASK_BRIDGE_C_PLUS = (80, 92)       # Bridge C+ via OFT
TASK_SEND_T_PLUS   = (422, 440)     # Send T+
TASK_RECEIVE_C_PLUS = (409, 425)    # Receive C+
TASK_TOTAL_TX      = 32             # Min total tx (mint, stake, or bridge)

# ─── Faucet Tokens ────────────────────────────────────────────────────────────

FAUCET_TOKENS = [
    {"symbol": "USDT", "address": USDT_SEPOLIA, "decimals": 6, "amount": 10000},
    {"symbol": "USDC", "address": USDC_SEPOLIA, "decimals": 6, "amount": 10000},
    {"symbol": "DAI",  "address": "0xFF34B3d4Aee8ddCd6F9AFFFB6Fe49bD371b8a357", "decimals": 18, "amount": 10000},
    {"symbol": "LINK", "address": "0xf8Fb3713D459D7C1018BD0A49D19b4C44290EBE5", "decimals": 18, "amount": 1000},
    {"symbol": "WBTC", "address": "0x29f2D40B0605204364af54EC677bD022dA425d03", "decimals": 8,  "amount": 1},
    {"symbol": "AAVE", "address": "0x88541670E55cC00bEEFD87eB59EDd1b7C511AC9a", "decimals": 18, "amount": 100},
    {"symbol": "EURS", "address": "0x6d906e526a4e2Ca02097BA9d0caA3c382F52278E", "decimals": 2,  "amount": 10000},
]

# ─── ABIs ─────────────────────────────────────────────────────────────────────

FAUCET_ABI = [
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "mint",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

ERC20_ABI = [
    {
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

OVERLAYER_WRAP_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "benefactor", "type": "address"},
                    {"name": "beneficiary", "type": "address"},
                    {"name": "collateral", "type": "address"},
                    {"name": "collateralAmount", "type": "uint256"},
                    {"name": "overlayerWrapAmount", "type": "uint256"},
                ],
                "name": "order_",
                "type": "tuple",
            }
        ],
        "name": "mint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

STAKED_OVERLAYER_ABI = [
    {
        "inputs": [
            {"name": "assets_", "type": "uint256"},
            {"name": "receiver_", "type": "address"},
        ],
        "name": "deposit",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

OFT_SEND_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "dstEid", "type": "uint32"},
                    {"name": "to", "type": "bytes32"},
                    {"name": "amountLD", "type": "uint256"},
                    {"name": "minAmountLD", "type": "uint256"},
                    {"name": "extraOptions", "type": "bytes"},
                    {"name": "composeMsg", "type": "bytes"},
                    {"name": "oftCmd", "type": "bytes"},
                ],
                "name": "_sendParam",
                "type": "tuple",
            },
            {
                "components": [
                    {"name": "nativeFee", "type": "uint256"},
                    {"name": "lzTokenFee", "type": "uint256"},
                ],
                "name": "_fee",
                "type": "tuple",
            },
            {"name": "_refundAddress", "type": "address"},
        ],
        "name": "send",
        "outputs": [
            {
                "components": [
                    {"name": "guid", "type": "bytes32"},
                    {"name": "nonce", "type": "uint64"},
                    {"name": "fee", "type": "tuple", "components": [
                        {"name": "nativeFee", "type": "uint256"},
                        {"name": "lzTokenFee", "type": "uint256"},
                    ]},
                ],
                "name": "",
                "type": "tuple",
            },
            {
                "components": [
                    {"name": "amountSentLD", "type": "uint256"},
                    {"name": "amountReceivedLD", "type": "uint256"},
                ],
                "name": "",
                "type": "tuple",
            },
        ],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"name": "dstEid", "type": "uint32"},
                    {"name": "to", "type": "bytes32"},
                    {"name": "amountLD", "type": "uint256"},
                    {"name": "minAmountLD", "type": "uint256"},
                    {"name": "extraOptions", "type": "bytes"},
                    {"name": "composeMsg", "type": "bytes"},
                    {"name": "oftCmd", "type": "bytes"},
                ],
                "name": "_sendParam",
                "type": "tuple",
            },
            {"name": "_payInLzToken", "type": "bool"},
        ],
        "name": "quoteSend",
        "outputs": [
            {
                "components": [
                    {"name": "nativeFee", "type": "uint256"},
                    {"name": "lzTokenFee", "type": "uint256"},
                ],
                "name": "msgFee",
                "type": "tuple",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

# ─── RPC Endpoints ────────────────────────────────────────────────────────────

RPC_ENDPOINTS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://sepolia.drpc.org",
    "https://eth-sepolia.public.blastapi.io",
    "https://1rpc.io/sepolia",
    "https://rpc2.sepolia.org",
]

LOOP_INTERVAL = 24 * 60 * 60  # 24 hours


# ─── Helpers ──────────────────────────────────────────────────────────────────

def rand_amount(min_val, max_val):
    """Random float between min and max, rounded to 2 decimals."""
    return round(random.uniform(min_val, max_val), 2)


class C:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    DIM    = "\033[2m"
    BOLD   = "\033[1m"
    MAGENTA = "\033[95m"


# ─── Logger Setup ─────────────────────────────────────────────────────────────

class ColorFormatter(logging.Formatter):
    LEVELS = {
        logging.DEBUG:    C.DIM,
        logging.INFO:     C.CYAN,
        logging.WARNING:  C.YELLOW,
        logging.ERROR:    C.RED,
        logging.CRITICAL: C.RED + C.BOLD,
    }

    def format(self, record):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = self.LEVELS.get(record.levelno, C.RESET)
        level = record.levelname.ljust(8)
        return f"{C.DIM}{ts}{C.RESET} {color}{level}{C.RESET} {record.getMessage()}"


def setup_logger(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("overlayer")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(ColorFormatter())
    logger.addHandler(ch)
    return logger


log = setup_logger()


# ─── Proxy Handling ───────────────────────────────────────────────────────────

def parse_proxy(line: str) -> Optional[dict]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        parts = line.split("://", 1)
        protocol = parts[0].lower()
        rest = parts[1]
    else:
        protocol = "http"
        rest = line
    if "@" in rest:
        auth, hostport = rest.rsplit("@", 1)
        proxy_url = f"{protocol}://{auth}@{hostport}"
    else:
        proxy_url = f"{protocol}://{rest}"
    return {"http": proxy_url, "https": proxy_url}


def load_proxies(filepath: str) -> list:
    path = Path(filepath)
    if not path.exists():
        return []
    proxies = []
    for line in path.read_text().splitlines():
        p = parse_proxy(line)
        if p:
            proxies.append(p)
    return proxies


class ProxyRotator:
    def __init__(self, proxies: list):
        self.proxies = proxies
        self.index = 0

    def next(self) -> Optional[dict]:
        if not self.proxies:
            return None
        proxy = self.proxies[self.index % len(self.proxies)]
        self.index += 1
        return proxy

    def __len__(self):
        return len(self.proxies)


# ─── Private Key Handling ─────────────────────────────────────────────────────

def load_private_keys(filepath: str) -> list:
    path = Path(filepath)
    if not path.exists():
        log.error(f"Private key file not found: {filepath}")
        sys.exit(1)
    keys = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("0x"):
            line = "0x" + line
        try:
            Account.from_key(line)
            keys.append(line)
        except Exception as e:
            log.warning(f"Invalid key on line {i}: {e}")
    return keys


# ─── Web3 Connection ──────────────────────────────────────────────────────────

def get_web3(proxy: Optional[dict] = None, ua: Optional[str] = None) -> Optional[Web3]:
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    session = requests.Session()
    if proxy:
        session.proxies.update(proxy)
    for rpc in RPC_ENDPOINTS:
        try:
            provider = Web3.HTTPProvider(
                rpc,
                request_kwargs={"timeout": 15, "headers": headers},
                session=session,
            )
            w3 = Web3(provider)
            if w3.is_connected():
                log.debug(f"Connected to RPC: {rpc}")
                return w3
        except Exception:
            continue
    return None


# ─── Transaction Helpers ──────────────────────────────────────────────────────

def send_tx(w3, account, tx, nonce, debug=False, label="TX"):
    """Build, sign, and send a transaction. Returns (receipt, new_nonce) or (None, nonce)."""
    tx["from"] = account.address
    tx["nonce"] = nonce
    tx["chainId"] = SEPOLIA_CHAIN_ID
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = w3.eth.gas_price

    try:
        gas = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas * 1.3)
    except Exception as e:
        log.error(f"  [{label}] Gas estimate failed: {str(e)[:120]}")
        return None, nonce

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    if debug:
        log.debug(f"  [{label}] TX: {tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 1:
        return receipt, nonce + 1
    else:
        log.warning(f"  [{label}] TX reverted")
        return None, nonce + 1


def approve_if_needed(w3, account, token_addr, spender_addr, amount, nonce, debug=False, label="Approve"):
    """Approve spender if current allowance is insufficient. Returns (tx_sent, new_nonce)."""
    token = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    current = token.functions.allowance(account.address, Web3.to_checksum_address(spender_addr)).call()
    if current >= amount:
        log.debug(f"  [{label}] Already approved")
        return False, nonce

    log.info(f"  {C.BLUE}[APPROVE]{C.RESET} {label}")
    tx = token.functions.approve(
        Web3.to_checksum_address(spender_addr),
        2**256 - 1
    ).build_transaction({"from": account.address, "value": 0})
    receipt, nonce = send_tx(w3, account, tx, nonce, debug, label)
    if receipt:
        log.info(f"  {C.GREEN}[OK]{C.RESET} {label} | Gas: {receipt.gasUsed}")
        return True, nonce
    return False, nonce


# ─── Explorer Helper ──────────────────────────────────────────────────────────

def fetch_random_explorer_address(exclude_addrs=None):
    """Fetch a random active T+ holder address from Blockscout explorer."""
    if exclude_addrs is None:
        exclude_addrs = set()
    exclude_lower = {a.lower() for a in exclude_addrs}

    # Known contract/special addresses to skip
    skip_lower = {
        STAKED_T_PLUS.lower(), STAKED_C_PLUS.lower(),
        T_PLUS_CONTRACT.lower(), C_PLUS_CONTRACT.lower(),
        FAUCET_CONTRACT.lower(),
        "0x0000000000000000000000000000000000055555",
        "0x1100000000000000000000000000000000000000",
        "0x6666666666666666666666666666666666666666",
    }

    try:
        url = f"https://eth-sepolia.blockscout.com/api/v2/tokens/{T_PLUS_CONTRACT}/holders"
        resp = requests.get(url, timeout=10)
        items = resp.json().get("items", [])
        candidates = []
        for item in items:
            addr = item.get("address", {}).get("hash", "")
            if not addr:
                continue
            if addr.lower() in exclude_lower or addr.lower() in skip_lower:
                continue
            candidates.append(addr)
        if candidates:
            return random.choice(candidates)
    except Exception as e:
        log.warning(f"  Failed to fetch explorer address: {str(e)[:80]}")

    return None


# ─── Task Functions ───────────────────────────────────────────────────────────

def do_faucet_claims(w3, account, nonce, debug, max_retries=3):
    """Claim all 7 faucet tokens. Returns (success_count, new_nonce)."""
    faucet = w3.eth.contract(
        address=Web3.to_checksum_address(FAUCET_CONTRACT),
        abi=FAUCET_ABI,
    )
    success = 0
    for token in FAUCET_TOKENS:
        symbol = token["symbol"]
        token_addr = Web3.to_checksum_address(token["address"])
        mint_amount = token["amount"] * (10 ** token["decimals"])

        for attempt in range(1, max_retries + 1):
            try:
                tx = faucet.functions.mint(
                    token_addr, account.address, mint_amount
                ).build_transaction({"from": account.address, "value": 0})
                receipt, nonce = send_tx(w3, account, tx, nonce, debug, f"Faucet-{symbol}")
                if receipt:
                    log.info(f"  {C.GREEN}[OK]{C.RESET} Faucet {symbol.ljust(5)} | {token['amount']} {symbol} | Gas: {receipt.gasUsed}")
                    success += 1
                    break
                else:
                    if attempt < max_retries:
                        time.sleep(3)
            except Exception as e:
                log.error(f"  [Faucet-{symbol}] Error (attempt {attempt}/{max_retries}): {str(e)[:120]}")
                if attempt < max_retries:
                    time.sleep(3 * attempt)

        time.sleep(random.uniform(0.5, 1.5))

    return success, nonce


def do_overlayer_mint(w3, account, nonce, debug, token_type="T+", amount_human=100, max_retries=2):
    """Mint T+ or C+ via OverlayerWrap. Single transaction."""
    if token_type == "T+":
        wrap_addr = Web3.to_checksum_address(T_PLUS_CONTRACT)
        collateral_addr = Web3.to_checksum_address(USDT_SEPOLIA)
        collateral_decimals = 6
    else:
        wrap_addr = Web3.to_checksum_address(C_PLUS_CONTRACT)
        collateral_addr = Web3.to_checksum_address(USDC_SEPOLIA)
        collateral_decimals = 6

    wrap_contract = w3.eth.contract(address=wrap_addr, abi=OVERLAYER_WRAP_ABI)
    collateral_amount = int(amount_human * (10 ** collateral_decimals))
    wrap_amount = int(amount_human * (10 ** 18))

    order = (
        account.address,
        account.address,
        collateral_addr,
        collateral_amount,
        wrap_amount,
    )

    for attempt in range(1, max_retries + 1):
        try:
            tx = wrap_contract.functions.mint(order).build_transaction({
                "from": account.address,
                "value": 0,
            })
            receipt, nonce = send_tx(w3, account, tx, nonce, debug, f"Mint-{token_type}")
            if receipt:
                log.info(f"  {C.GREEN}[OK]{C.RESET} Mint {token_type.ljust(3)} | {amount_human} {token_type} | Gas: {receipt.gasUsed}")
                return True, nonce
            else:
                if attempt < max_retries:
                    time.sleep(3)
        except Exception as e:
            log.error(f"  [Mint-{token_type}] Error (attempt {attempt}/{max_retries}): {str(e)[:120]}")
            if attempt < max_retries:
                time.sleep(3 * attempt)

    return False, nonce


def do_stake(w3, account, nonce, debug, token_type="T+", amount_human=40, max_retries=2):
    """Stake T+ or C+ into StakedOverlayerWrap. Single transaction."""
    if token_type == "T+":
        staked_addr = Web3.to_checksum_address(STAKED_T_PLUS)
    else:
        staked_addr = Web3.to_checksum_address(STAKED_C_PLUS)

    staked_contract = w3.eth.contract(address=staked_addr, abi=STAKED_OVERLAYER_ABI)
    amount_wei = int(amount_human * (10 ** 18))

    for attempt in range(1, max_retries + 1):
        try:
            tx = staked_contract.functions.deposit(
                amount_wei, account.address
            ).build_transaction({"from": account.address, "value": 0})
            receipt, nonce = send_tx(w3, account, tx, nonce, debug, f"Stake-{token_type}")
            if receipt:
                log.info(f"  {C.GREEN}[OK]{C.RESET} Stake {token_type.ljust(3)} | {amount_human} {token_type} | Gas: {receipt.gasUsed}")
                return True, nonce
            else:
                if attempt < max_retries:
                    time.sleep(3)
        except Exception as e:
            log.error(f"  [Stake-{token_type}] Error (attempt {attempt}/{max_retries}): {str(e)[:120]}")
            if attempt < max_retries:
                time.sleep(3 * attempt)

    return False, nonce


def do_send(w3, account, nonce, debug, token_type="T+", amount_human=150, to_address=None, max_retries=2):
    """Send T+ or C+ via ERC-20 transfer. Single transaction."""
    if token_type == "T+":
        token_addr = Web3.to_checksum_address(T_PLUS_CONTRACT)
    else:
        token_addr = Web3.to_checksum_address(C_PLUS_CONTRACT)

    if to_address is None:
        to_address = account.address

    token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
    amount_wei = int(amount_human * (10 ** 18))

    for attempt in range(1, max_retries + 1):
        try:
            tx = token.functions.transfer(
                Web3.to_checksum_address(to_address), amount_wei
            ).build_transaction({"from": account.address, "value": 0})
            receipt, nonce = send_tx(w3, account, tx, nonce, debug, f"Send-{token_type}")
            if receipt:
                short_to = f"{to_address[:6]}...{to_address[-4:]}"
                log.info(f"  {C.GREEN}[OK]{C.RESET} Send {token_type.ljust(3)} | {amount_human} {token_type} → {short_to} | Gas: {receipt.gasUsed}")
                return True, nonce
            else:
                if attempt < max_retries:
                    time.sleep(3)
        except Exception as e:
            log.error(f"  [Send-{token_type}] Error (attempt {attempt}/{max_retries}): {str(e)[:120]}")
            if attempt < max_retries:
                time.sleep(3 * attempt)

    return False, nonce


def do_bridge_oft(w3, account, nonce, debug, token_type="C+", amount_human=28, max_retries=2):
    """Bridge C+ or T+ via LayerZero OFT to Base Sepolia. Single transaction."""
    if token_type == "C+":
        token_addr = Web3.to_checksum_address(C_PLUS_CONTRACT)
    else:
        token_addr = Web3.to_checksum_address(T_PLUS_CONTRACT)

    oft_contract = w3.eth.contract(address=token_addr, abi=OFT_SEND_ABI)
    amount_wei = int(amount_human * (10 ** 18))
    min_amount_wei = int(amount_wei * 0.9)

    to_bytes32 = b'\x00' * 12 + bytes.fromhex(account.address[2:])

    exec_gas = 200000
    extra_options = (
        b'\x00\x03'
        + b'\x01'
        + struct.pack('>H', 1 + 16 + 16)
        + b'\x01'
        + exec_gas.to_bytes(16, 'big')
        + (0).to_bytes(16, 'big')
    )

    send_param = (
        BASE_SEPOLIA_EID,
        to_bytes32,
        amount_wei,
        min_amount_wei,
        extra_options,
        b'',
        b'',
    )

    for attempt in range(1, max_retries + 1):
        try:
            quote = oft_contract.functions.quoteSend(send_param, False).call()
            native_fee = int(quote[0] * 1.1)
            fee_param = (native_fee, 0)

            tx = oft_contract.functions.send(
                send_param, fee_param, account.address
            ).build_transaction({
                "from": account.address,
                "value": native_fee,
            })
            receipt, nonce = send_tx(w3, account, tx, nonce, debug, f"Bridge-{token_type}")
            if receipt:
                fee_eth = Web3.from_wei(native_fee, 'ether')
                log.info(
                    f"  {C.GREEN}[OK]{C.RESET} Bridge {token_type.ljust(3)} "
                    f"| {amount_human} {token_type} → Base Sepolia "
                    f"| Fee: {fee_eth:.6f} ETH | Gas: {receipt.gasUsed}"
                )
                return True, nonce
            else:
                if attempt < max_retries:
                    time.sleep(3)
        except Exception as e:
            log.error(f"  [Bridge-{token_type}] Error (attempt {attempt}/{max_retries}): {str(e)[:120]}")
            if attempt < max_retries:
                time.sleep(3 * attempt)

    return False, nonce


# ─── Main Daily Task Orchestrator ─────────────────────────────────────────────

def run_daily_tasks(
    private_key: str,
    account_index: int,
    proxy: Optional[dict],
    ua: str,
    debug: bool,
    max_retries: int = 3,
    all_keys: list = None,
):
    """Execute all daily tasks for a single account."""
    account = Account.from_key(private_key)
    short_addr = f"{account.address[:6]}...{account.address[-4:]}"
    log.info(f"{C.BOLD}Account #{account_index}{C.RESET} | {C.GREEN}{short_addr}{C.RESET}")

    if proxy:
        proxy_display = list(proxy.values())[0]
        if "@" in proxy_display:
            proto, rest = proxy_display.split("://", 1)
            _, hostport = rest.rsplit("@", 1)
            proxy_display = f"{proto}://***@{hostport}"
        log.debug(f"  Proxy: {proxy_display}")

    w3 = get_web3(proxy, ua)
    if not w3:
        log.error("  Failed to connect to any RPC endpoint")
        return False

    eth_balance = w3.eth.get_balance(account.address)
    eth_amount = Web3.from_wei(eth_balance, "ether")
    log.info(f"  ETH Balance: {C.YELLOW}{eth_amount:.6f}{C.RESET} ETH")

    if eth_balance == 0:
        log.warning("  No ETH for gas fees, skipping...")
        return False

    nonce = w3.eth.get_transaction_count(account.address)
    msb_tx = 0  # mint/stake/bridge tx counter

    # Collect all other wallet addresses from pk.txt (excluding self)
    other_addresses = []
    if all_keys:
        for k in all_keys:
            if k != private_key:
                try:
                    other_addresses.append(Account.from_key(k).address)
                except Exception:
                    pass

    # Randomize amounts for this account
    amt_stake_tp  = rand_amount(*TASK_STAKE_T_PLUS)
    amt_bridge_cp = rand_amount(*TASK_BRIDGE_C_PLUS)
    amt_send_tp   = rand_amount(*TASK_SEND_T_PLUS)
    amt_recv_cp   = rand_amount(*TASK_RECEIVE_C_PLUS)

    # Randomize mint counts (5-6 each)
    mint_tp_count = random.randint(*MINT_T_COUNT)
    mint_cp_count = random.randint(*MINT_C_COUNT)

    # Generate per-tx mint amounts
    mint_tp_amounts = [rand_amount(*MINT_PER_TX) for _ in range(mint_tp_count)]
    mint_cp_amounts = [rand_amount(*MINT_PER_TX) for _ in range(mint_cp_count)]
    total_tp_minted = sum(mint_tp_amounts)
    total_cp_minted = sum(mint_cp_amounts)

    log.info(f"  {C.CYAN}Plan:{C.RESET} "
             f"mint T+ {mint_tp_count}x (total ~{total_tp_minted:.0f}), "
             f"mint C+ {mint_cp_count}x (total ~{total_cp_minted:.0f})")
    log.info(f"  {C.CYAN}Tasks:{C.RESET} "
             f"stake={amt_stake_tp} T+, bridge={amt_bridge_cp} C+, "
             f"send={amt_send_tp} T+, receive={amt_recv_cp} C+")

    # ─── Phase 1: Faucet Claims (7 tx) ─────────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 1: Faucet Claims{C.RESET}")
    faucet_ok, nonce = do_faucet_claims(w3, account, nonce, debug, max_retries)
    log.info(f"  Faucet: {C.GREEN}{faucet_ok}/7{C.RESET} claimed")
    time.sleep(random.uniform(1, 3))

    # ─── Phase 2: Approve collateral ────────────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 2: Approvals{C.RESET}")
    approve_if_needed(w3, account, USDT_SEPOLIA, T_PLUS_CONTRACT, int(total_tp_minted * 10**6), nonce, debug, "USDT→T+")
    nonce = w3.eth.get_transaction_count(account.address)
    approve_if_needed(w3, account, USDC_SEPOLIA, C_PLUS_CONTRACT, int(total_cp_minted * 10**6), nonce, debug, "USDC→C+")
    nonce = w3.eth.get_transaction_count(account.address)
    time.sleep(random.uniform(1, 2))

    # ─── Phase 3: Mint T+ (5-6 tx) ─────────────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 3: Mint T+ ({mint_tp_count}x){C.RESET}")
    for i, amt in enumerate(mint_tp_amounts, 1):
        ok, nonce = do_overlayer_mint(w3, account, nonce, debug, "T+", amt, max_retries)
        if ok:
            msb_tx += 1
        time.sleep(random.uniform(1, 2.5))

    # ─── Phase 4: Mint C+ (5-6 tx) ─────────────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 4: Mint C+ ({mint_cp_count}x){C.RESET}")
    for i, amt in enumerate(mint_cp_amounts, 1):
        ok, nonce = do_overlayer_mint(w3, account, nonce, debug, "C+", amt, max_retries)
        if ok:
            msb_tx += 1
        time.sleep(random.uniform(1, 2.5))

    # ─── Phase 5: Stake T+ (1 tx) ──────────────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 5: Stake T+ ({amt_stake_tp}){C.RESET}")
    approve_if_needed(w3, account, T_PLUS_CONTRACT, STAKED_T_PLUS, int(amt_stake_tp * 10**18), nonce, debug, "T+→sT+")
    nonce = w3.eth.get_transaction_count(account.address)
    ok, nonce = do_stake(w3, account, nonce, debug, "T+", amt_stake_tp, max_retries)
    if ok:
        msb_tx += 1
    time.sleep(random.uniform(1, 2))

    # ─── Phase 6: Send T+ (to each wallet in pk.txt + 1 random explorer) ──
    send_targets = list(other_addresses)  # all other wallets
    if not send_targets:
        send_targets = [account.address]  # fallback: self-transfer

    # Fetch 1 random address from explorer
    all_own_addrs = {account.address} | set(other_addresses)
    explorer_addr = fetch_random_explorer_address(exclude_addrs=all_own_addrs)
    if explorer_addr:
        send_targets.append(explorer_addr)
        log.info(f"  {C.CYAN}Explorer wallet:{C.RESET} {explorer_addr[:6]}...{explorer_addr[-4:]}")

    # Distribute send amount across targets
    num_targets = len(send_targets)
    per_target = round(amt_send_tp / num_targets, 2)
    log.info(f"  {C.MAGENTA}▸ Phase 6: Send T+ ({amt_send_tp}) to {num_targets} wallets ({per_target} each){C.RESET}")

    for target in send_targets:
        ok, nonce = do_send(w3, account, nonce, debug, "T+", per_target, target, max_retries)
        time.sleep(random.uniform(1, 2))

    # ─── Phase 7: Bridge C+ via OFT (1 tx) ─────────────────────────────
    log.info(f"  {C.MAGENTA}▸ Phase 7: Bridge C+ ({amt_bridge_cp}){C.RESET}")
    ok, nonce = do_bridge_oft(w3, account, nonce, debug, "C+", amt_bridge_cp, max_retries)
    if ok:
        msb_tx += 1
    time.sleep(random.uniform(1, 2))

    # ─── Phase 8: Receive C+ (1 tx, self-transfer or cross-wallet) ─────
    log.info(f"  {C.MAGENTA}▸ Phase 8: Receive C+ ({amt_recv_cp}){C.RESET}")
    ok, nonce = do_send(w3, account, nonce, debug, "C+", amt_recv_cp, account.address, max_retries)
    time.sleep(random.uniform(1, 2))

    # ─── Phase 9: Smart extra tx to reach 32 ───────────────────────────
    remaining = TASK_TOTAL_TX - msb_tx
    if remaining > 0:
        log.info(f"  {C.MAGENTA}▸ Phase 9: Smart fill ({remaining} more mint/stake/bridge needed){C.RESET}")

        # Build a smart task queue: mix of mint, stake, bridge
        # Use amounts that are at or slightly above each task's minimum
        task_queue = []
        for _ in range(remaining):
            roll = random.random()
            if roll < 0.45:
                # Extra mint (alternate T+/C+), amount near task minimums
                token = random.choice(["T+", "C+"])
                task_queue.append(("mint", token, rand_amount(10, 50)))
            elif roll < 0.75:
                # Extra stake, amount near minimum
                task_queue.append(("stake", "T+", rand_amount(10, 30)))
            else:
                # Extra bridge, amount near minimum
                task_queue.append(("bridge", "C+", rand_amount(5, 15)))

        random.shuffle(task_queue)

        # Pre-approve for extra stakes
        has_stakes = any(t[0] == "stake" for t in task_queue)
        if has_stakes:
            approve_if_needed(w3, account, T_PLUS_CONTRACT, STAKED_T_PLUS, 1000 * 10**18, nonce, debug, "T+→sT+ extra")
            nonce = w3.eth.get_transaction_count(account.address)

        for task_type, token, amt in task_queue:
            if task_type == "mint":
                ok, nonce = do_overlayer_mint(w3, account, nonce, debug, token, amt, max_retries)
            elif task_type == "stake":
                ok, nonce = do_stake(w3, account, nonce, debug, token, amt, max_retries)
            elif task_type == "bridge":
                ok, nonce = do_bridge_oft(w3, account, nonce, debug, token, amt, max_retries)
            else:
                ok = False
            if ok:
                msb_tx += 1
            time.sleep(random.uniform(0.5, 2))

    # ─── Summary ────────────────────────────────────────────────────────
    print(f"{C.DIM}{'─' * 58}{C.RESET}")
    log.info(f"  {C.BOLD}Daily Summary:{C.RESET}")
    log.info(f"    Faucet:            {C.GREEN}{faucet_ok}/7{C.RESET}")
    log.info(f"    Mint T+:           {C.GREEN}{total_tp_minted:.0f}{C.RESET} T+ in {mint_tp_count} tx")
    log.info(f"    Mint C+:           {C.GREEN}{total_cp_minted:.0f}{C.RESET} C+ in {mint_cp_count} tx")
    log.info(f"    Stake T+:          {C.GREEN}{amt_stake_tp}{C.RESET} (min {TASK_STAKE_T_PLUS[0]})")
    log.info(f"    Bridge C+ (OFT):   {C.GREEN}{amt_bridge_cp}{C.RESET} (min {TASK_BRIDGE_C_PLUS[0]})")
    log.info(f"    Send T+:           {C.GREEN}{amt_send_tp}{C.RESET} (min {TASK_SEND_T_PLUS[0]})")
    log.info(f"    Receive C+:        {C.GREEN}{amt_recv_cp}{C.RESET} (min {TASK_RECEIVE_C_PLUS[0]})")
    log.info(f"    Mint/Stake/Bridge: {C.GREEN}{msb_tx}{C.RESET} tx (min {TASK_TOTAL_TX})")

    return True


# ─── Countdown Timer ──────────────────────────────────────────────────────────

def countdown(seconds: int):
    end_time = time.time() + seconds
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        hours = remaining // 3600
        mins = (remaining % 3600) // 60
        secs = remaining % 60
        sys.stdout.write(
            f"\r{C.DIM}[LOOP]{C.RESET} Next cycle in "
            f"{C.YELLOW}{hours:02d}:{mins:02d}:{secs:02d}{C.RESET}   "
        )
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


# ─── Banner ───────────────────────────────────────────────────────────────────

def show_banner():
    banner = f"""
{C.CYAN}╔══════════════════════════════════════════════════════════╗
║       Overlayer Testnet Daily Tasks Bot                   ║
║       Mint | Stake | Bridge | Send | Receive              ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
"""
    print(banner)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    show_banner()

    pk_file = os.getenv("PK_FILE", "pk.txt")
    proxy_file = os.getenv("PROXY_FILE", "proxy.txt")
    debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    use_proxy = os.getenv("USE_PROXY", "").lower() in ("true", "1", "yes")

    if sys.stdin.isatty() and not os.getenv("NON_INTERACTIVE"):
        debug_input = input(f"{C.CYAN}[?]{C.RESET} Enable debug mode? (y/n, default: n): ").strip().lower()
        if debug_input in ("y", "yes", "true", "1"):
            debug = True

        use_proxy_input = input(f"{C.CYAN}[?]{C.RESET} Use proxy? (y/n, default: n): ").strip().lower()
        use_proxy = use_proxy_input in ("y", "yes", "true", "1")

    print()

    global log
    log = setup_logger(debug)

    private_keys = load_private_keys(pk_file)
    if not private_keys:
        log.error("No valid private keys found in pk.txt")
        sys.exit(1)
    log.info(f"Loaded {C.GREEN}{len(private_keys)}{C.RESET} account(s)")

    rotator = ProxyRotator([])
    if use_proxy:
        proxies = load_proxies(proxy_file)
        if proxies:
            rotator = ProxyRotator(proxies)
            log.info(f"Loaded {C.GREEN}{len(proxies)}{C.RESET} proxy(ies)")
        else:
            log.warning(f"No proxies found in {proxy_file}, running without proxy")

    try:
        ua_gen = UserAgent()
    except Exception:
        ua_gen = None
        log.warning("fake-useragent failed to initialize, using default UA")

    log.info(f"Debug: {C.YELLOW}{'ON' if debug else 'OFF'}{C.RESET} | "
             f"Retries: {C.YELLOW}{max_retries}{C.RESET}")

    log.info(f"{C.BOLD}Daily Task Targets (randomized per account):{C.RESET}")
    log.info(f"  Mint T+:    {C.YELLOW}{MINT_T_COUNT[0]}-{MINT_T_COUNT[1]}x ({MINT_PER_TX[0]}-{MINT_PER_TX[1]} each){C.RESET}")
    log.info(f"  Mint C+:    {C.YELLOW}{MINT_C_COUNT[0]}-{MINT_C_COUNT[1]}x ({MINT_PER_TX[0]}-{MINT_PER_TX[1]} each){C.RESET}")
    log.info(f"  Stake T+:   {C.YELLOW}{TASK_STAKE_T_PLUS[0]}-{TASK_STAKE_T_PLUS[1]}{C.RESET}")
    log.info(f"  Bridge C+:  {C.YELLOW}{TASK_BRIDGE_C_PLUS[0]}-{TASK_BRIDGE_C_PLUS[1]}{C.RESET}")
    log.info(f"  Send T+:    {C.YELLOW}{TASK_SEND_T_PLUS[0]}-{TASK_SEND_T_PLUS[1]}{C.RESET}")
    log.info(f"  Receive C+: {C.YELLOW}{TASK_RECEIVE_C_PLUS[0]}-{TASK_RECEIVE_C_PLUS[1]}{C.RESET}")
    log.info(f"  Total TX:   {C.YELLOW}{TASK_TOTAL_TX}{C.RESET} (mint/stake/bridge)")
    print(f"{C.DIM}{'─' * 58}{C.RESET}")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print()
        log.info("Shutdown signal received, stopping after current account...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    cycle = 0
    while running:
        cycle += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"{C.BOLD}Cycle #{cycle}{C.RESET} started at {C.CYAN}{ts}{C.RESET}")
        print(f"{C.DIM}{'─' * 58}{C.RESET}")

        for idx, pk in enumerate(private_keys, 1):
            if not running:
                break

            proxy = rotator.next() if use_proxy else None
            ua = ua_gen.random if ua_gen else "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

            run_daily_tasks(pk, idx, proxy, ua, debug, max_retries, private_keys)

            if idx < len(private_keys) and running:
                delay = random.uniform(5, 15)
                log.info(f"{C.DIM}Waiting {delay:.1f}s before next account...{C.RESET}")
                time.sleep(delay)

            print(f"{C.DIM}{'─' * 58}{C.RESET}")

        if not running:
            break

        log.info(f"{C.GREEN}Cycle #{cycle} completed{C.RESET}")
        log.info("Next cycle in 24 hours")

        try:
            countdown(LOOP_INTERVAL)
        except KeyboardInterrupt:
            running = False
            break

    print()
    log.info("Bot stopped. Goodbye!")


if __name__ == "__main__":
    main()
