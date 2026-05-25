# Overlayer Testnet Auto Faucet Bot

Automation bot for claiming test tokens from the **Aave GHO Sepolia Faucet** used by [Overlayer Testnet](https://testnet.overlayer.fi/).

## Features

- Claims **7 test tokens**: DAI, LINK, USDC, WBTC, USDT, AAVE, EURS
- **Multiple accounts** — load private keys from `pk.txt`
- **Proxy support** — multiple formats via `proxy.txt` with auto-rotation
- **Colored & timestamped logs** — clean, easy-to-monitor output
- **Retry logic** — configurable retries with exponential backoff
- **Fake User-Agent** — randomized per request via `fake-useragent`
- **Debug mode** — toggle on/off for verbose output
- **24-hour loop** — inline countdown timer (no log spam)
- **Human-like delays** — random pauses between accounts (5–15s)
- **Graceful shutdown** — Ctrl+C stops after current account

## Requirements

- Python 3.10+
- Sepolia ETH for gas fees (~0.01 ETH per account per cycle)

## Installation

```bash
# Clone or extract the bot
cd overlayer-bot

# Install dependencies
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

Add proxies in any of these formats:

```
# Default HTTP protocol
192.168.1.1:8080

# With protocol
http://192.168.1.1:8080
https://192.168.1.1:8443
socks5://192.168.1.1:1080

# With authentication
http://user:pass@192.168.1.1:8080
socks5://user:pass@192.168.1.1:1080
```

## Usage

```bash
python bot.py
```

The bot will ask:
1. **Debug mode?** (y/n) — Shows extra details like TX hashes, balances
2. **Use proxy?** (y/n) — Enable proxy rotation from `proxy.txt`

### Environment Variables

You can also configure via environment variables:

| Variable      | Default     | Description                    |
|---------------|-------------|--------------------------------|
| `PK_FILE`     | `pk.txt`    | Path to private keys file      |
| `PROXY_FILE`  | `proxy.txt` | Path to proxy file             |
| `DEBUG`       | `false`     | Enable debug mode              |
| `MAX_RETRIES` | `3`         | Max retries per token claim    |

Example:
```bash
DEBUG=true MAX_RETRIES=5 python bot.py
```

## Tokens Claimed

| Token | Amount  | Decimals |
|-------|---------|----------|
| DAI   | 10,000  | 18       |
| LINK  | 1,000   | 18       |
| USDC  | 10,000  | 6        |
| WBTC  | 1       | 8        |
| USDT  | 10,000  | 6        |
| AAVE  | 100     | 18       |
| EURS  | 10,000  | 2        |

## How It Works

1. Reads private keys from `pk.txt`
2. Optionally loads proxies from `proxy.txt`
3. For each account:
   - Connects to Sepolia via public RPC endpoints
   - Checks ETH balance for gas
   - Calls `mint()` on the Aave V3 Faucet contract for each token
   - Retries on failure with configurable backoff
4. Waits 24 hours with inline countdown
5. Repeats

## Contract Info

- **Network**: Ethereum Sepolia Testnet (Chain ID: 11155111)
- **Faucet Contract**: `0xC959483DBa39aa9E78757139af0e9a2EDEb3f42D`
- **Faucet Function**: `mint(address token, address to, uint256 amount)`

## Notes

- Tokens are testnet tokens with **no monetary value**
- You need Sepolia ETH for gas — get it from [Google Cloud Faucet](https://cloud.google.com/application/web3/faucet/ethereum/sepolia) or [Alchemy Faucet](https://www.alchemy.com/faucets/ethereum-sepolia)
- The faucet is not permissioned, so anyone can claim
- The bot automatically rotates through multiple RPC endpoints for reliability

## Disclaimer

This bot is for testnet purposes only. Use responsibly and in accordance with the Overlayer and Aave testnet terms of service.
