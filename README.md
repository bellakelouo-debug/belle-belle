# Overlayer Testnet Daily Tasks Bot

Automation bot for completing **all daily tasks** on the [Overlayer Testnet](https://testnet.overlayer.fi/) (Ethereum Sepolia).

## Daily Tasks Completed

| Task | Minimum | Points |
|------|---------|--------|
| Mint T+ | 10 T+ | +100 |
| Stake T+ | 113 T+ | +150 |
| Bridge C+ via OFT | 80 C+ | +150 |
| Send T+ | 422 T+ | +150 |
| Receive C+ | 409 C+ | +200 |
| Total Transactions | 32 tx | +1000 |

## Features

- **Faucet claims**: 7 Aave test tokens (DAI, LINK, USDC, WBTC, USDT, AAVE, EURS)
- **Overlayer Mint**: Converts USDT → T+ and USDC → C+ via OverlayerWrap
- **Staking**: Deposits T+ into StakedOverlayerWrap (sT+)
- **OFT Bridge**: Bridges C+ to Base Sepolia via LayerZero OFT
- **Send / Receive**: ERC-20 transfers for T+ and C+ tokens
- **32+ transactions per cycle**: Ensures daily minimum is met
- **Multiple accounts** — load private keys from `pk.txt`
- **Proxy support** — multiple formats via `proxy.txt` with auto-rotation
- **Colored & timestamped logs** — clean, easy-to-monitor output
- **Retry logic** — configurable retries with exponential backoff
- **24-hour loop** — inline countdown timer
- **Graceful shutdown** — Ctrl+C stops after current account

## Requirements

- Python 3.10+
- Sepolia ETH for gas fees (~0.02 ETH per account per cycle)

## Installation

```bash
cd overlayer-bot
pip install -r requirements.txt
```

## Setup

### 1. Private Keys (`pk.txt`)

Add your private keys, one per line. Lines starting with `#` are ignored.

```
65c6fd87f6286083a0a055c13361103b49950bec14011b12591ea35687a97ae1
aabbccdd...your_second_private_key...
```

### 2. Proxies (`proxy.txt`) — Optional

```
http://192.168.1.1:8080
socks5://user:pass@192.168.1.1:1080
```

## Usage

```bash
python bot.py
```

### Non-Interactive Mode

```bash
NON_INTERACTIVE=1 DEBUG=false USE_PROXY=false python bot.py
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PK_FILE` | `pk.txt` | Path to private keys file |
| `PROXY_FILE` | `proxy.txt` | Path to proxy file |
| `DEBUG` | `false` | Enable debug mode |
| `MAX_RETRIES` | `3` | Max retries per operation |
| `USE_PROXY` | `false` | Enable proxy rotation |
| `NON_INTERACTIVE` | - | Skip interactive prompts |

## Transaction Flow Per Cycle

1. **Phase 1** — Faucet: Claim 7 test tokens (USDT, USDC, DAI, LINK, WBTC, AAVE, EURS)
2. **Phase 2** — Approvals: Approve USDT→T+, USDC→C+
3. **Phase 3** — Mint T+: 5 × ~120 = ~600 T+ tokens
4. **Phase 4** — Mint C+: 4 × ~135 = ~540 C+ tokens
5. **Phase 5** — Stake T+: 3 × ~38 = ~114 T+ staked
6. **Phase 6** — Send T+: 3 × ~141 = ~423 T+ sent
7. **Phase 7** — Bridge C+: 3 × ~27 = ~81 C+ bridged via OFT
8. **Phase 8** — Receive C+: 5 × ~82 = ~410 C+ received
9. **Phase 9** — Extra TX if needed to reach 32 total

## Contracts

| Contract | Address |
|---|---|
| Aave Faucet | `0xC959483DBa39aa9E78757139af0e9a2EDEb3f42D` |
| USDT Sepolia | `0xaA8E23Fb1079EA71e0a56F48a2aA51851D8433D0` |
| USDC Sepolia | `0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8` |
| T+ (OverlayerWrap) | `0xe20534a32f9162488a90026F268a74fBE28d272D` |
| C+ (OverlayerWrap) | `0xE815718D44694ec4637CB775C468d87f6e15B538` |
| sT+ (StakedOverlayerWrap) | `0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82` |
| sC+ (StakedOverlayerWrap) | `0x753937137Eb92871A6F3517514d4f1Ee860e3FDF` |

**Network**: Ethereum Sepolia (Chain ID: 11155111)
**Bridge Destination**: Base Sepolia (LayerZero EID: 40245)

## Notes

- All tokens are testnet tokens with **no monetary value**
- You need Sepolia ETH for gas — get from [Google Cloud Faucet](https://cloud.google.com/application/web3/faucet/ethereum/sepolia)
- For Send/Receive tasks with a single wallet, the bot uses self-transfers
- With 2+ wallets, the bot sends between wallets for more reliable tracking

## Disclaimer

This bot is for testnet purposes only. Use responsibly and in accordance with the Overlayer and Aave testnet terms of service.
