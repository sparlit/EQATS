import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# Regenerate from the repository root:
# uv run --with hyperliquid-python-sdk==0.24.0 python src/hypercore/testdata/generate_signing.py
# The fixture uses only throwaway keys and performs no network/API transactions.
import json
from importlib.metadata import version
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from hyperliquid.utils import signing as ref

nonce = 1700000000000
user = "0x1111111111111111111111111111111111111111"
key = Account.from_key("0x" + "00" * 31 + "01")
lead = key.address.lower()
other = "0x2222222222222222222222222222222222222222"
agent_types = [
    {"name": n, "type": t}
    for n, t in [
        ("hyperliquidChain", "string"),
        ("agentAddress", "address"),
        ("agentName", "string"),
        ("nonce", "uint64"),
    ]
]


def encoded(data):
    signable = encode_typed_data(full_message=data)
    return "0x" + keccak(b"\x19" + signable.version + signable.header + signable.body).hex()


cases = []
contexts = []
for chain, chain_id in [("Mainnet", 42161), ("Testnet", 421614)]:
    base = {"signatureChainId": hex(chain_id), "hyperliquidChain": chain}
    actions = [
        (
            "ApproveAgent",
            dict(type="approveAgent", **base, agentAddress=other, agentName=name, nonce=nonce),
            agent_types,
        )
        for name in ["", "bot"]
    ] + [
        (
            "TokenDelegate",
            dict(
                type="tokenDelegate",
                **base,
                validator=other,
                wei=100000000,
                isUndelegate=undelegate,
                nonce=nonce,
            ),
            ref.TOKEN_DELEGATE_TYPES,
        )
        for undelegate in [False, True]
    ]
    for kind, action, types in actions:
        normal = ref.user_signed_payload("HyperliquidTransaction:" + kind, types, action)
        multi = ref.user_signed_payload(
            "HyperliquidTransaction:" + kind,
            ref.add_multi_sig_types(types),
            ref.add_multi_sig_fields(action, user, lead),
        )
        cases.append(
            {
                "chain": chain,
                "nonce": nonce,
                "action": action,
                "prehash": encoded(normal),
                "multisigPrehash": encoded(multi),
            }
        )
    for vault in [None, other]:
        for expiry in [None, nonce + 10000]:
            action = {"type": "borrowLend", "operation": "supply", "token": 0, "amount": "10"}
            connection = ref.action_hash([user, lead, action], vault, nonce, expiry)
            data = ref.l1_payload(ref.construct_phantom_agent(connection, chain == "Mainnet"))
            contexts.append(
                {
                    "chain": chain,
                    "nonce": nonce,
                    "action": action,
                    "vault": vault,
                    "expiresAfter": expiry,
                    "prehash": encoded(data),
                }
            )
fixture = {
    "source": "hyperliquid-python-sdk "
    + version("hyperliquid-python-sdk")
    + " hyperliquid/utils/signing.py",
    "multisigUser": user,
    "leader": lead,
    "userSigned": cases,
    "l1Contexts": contexts,
}
Path("src/hypercore/testdata/signing.json").write_text(json.dumps(fixture, indent=2) + "\n")
print(fixture["source"], ":", len(cases), "user-signed and", len(contexts), "L1 fixtures")
