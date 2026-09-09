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


"""
Hand-rolled EIP-712 typed structured data hashing.

Behaviour-compatible with the previously vendored
``eth_account.messages.encode_typed_data`` /
``eth_account._utils.encode_typed_data.encoding_and_hashing`` implementation
(in a manner compatible with the MetaMask and Ethers ``signTypedData``
functions), see https://eips.ethereum.org/EIPS/eip-712
"""

import re
from typing import Any, Dict, List, NamedTuple, Tuple, Union

from ccxt.static_dependencies.keccak import SHA3 as keccak

from .abi import encode

_HEX_REGEXP = re.compile("(0[xX])?[0-9a-fA-F]*")


def _is_hexstr(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return _HEX_REGEXP.fullmatch(value) is not None


def _is_0x_prefixed_hexstr(value: Any) -> bool:
    return _is_hexstr(value) and value.startswith("0x")


def _hexstr_to_bytes(hexstr: str) -> bytes:
    if hexstr[:2] in ("0x", "0X"):
        hexstr = hexstr[2:]
    if len(hexstr) % 2:
        hexstr = "0" + hexstr
    return bytes.fromhex(hexstr)


def _int_to_bytes(value: int) -> bytes:
    # minimal big-endian representation, b"\x00" for 0
    return value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")


def _text_to_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _get_eip712_solidity_types():
    types = ["bool", "address", "string", "bytes", "uint", "int"]
    ints = [f"int{(x + 1) * 8}" for x in range(32)]
    uints = [f"uint{(x + 1) * 8}" for x in range(32)]
    bytes_ = [f"bytes{x + 1}" for x in range(32)]
    return types + ints + uints + bytes_


EIP712_SOLIDITY_TYPES = _get_eip712_solidity_types()


def _is_array_type(type_: str) -> bool:
    return type_.endswith("]")


# strip all brackets: Person[][] -> Person
def _parse_core_array_type(type_: str) -> str:
    if _is_array_type(type_):
        type_ = type_[: type_.index("[")]
    return type_


# strip only last set of brackets: Person[3][1] -> Person[3]
def _parse_parent_array_type(type_: str) -> str:
    if _is_array_type(type_):
        type_ = type_[: type_.rindex("[")]
    return type_


def get_primary_type(types: dict[str, list[dict[str, str]]]) -> str:
    custom_types = set(types.keys())
    custom_types_that_are_deps = set()

    for type_ in custom_types:
        type_fields = types[type_]
        for field in type_fields:
            parsed_type = _parse_core_array_type(field["type"])
            if parsed_type in custom_types and parsed_type != type_:
                custom_types_that_are_deps.add(parsed_type)

    primary_type = list(custom_types.difference(custom_types_that_are_deps))
    if len(primary_type) == 1:
        return primary_type[0]
    msg = "Unable to determine primary type"
    raise ValueError(msg)


def encode_field(
    types: dict[str, list[dict[str, str]]],
    name: str,
    type_: str,
    value: Any,
) -> tuple[str, int | bytes]:
    if type_ in types:
        # type is a custom type
        if value is None:
            return ("bytes32", b"\x00" * 32)
        return ("bytes32", keccak(encode_data(type_, types, value)))

    if type_ in ["string", "bytes"] and value is None:
        return ("bytes32", b"")

    # None is allowed only for custom and dynamic types
    if value is None:
        msg = f"Missing value for field `{name}` of type `{type_}`"
        raise ValueError(msg)

    if _is_array_type(type_):
        # handle array type with non-array value
        if not isinstance(value, list):
            msg = (
                f"Invalid value for field `{name}` of type `{type_}`: expected array, "
                f"got `{value}` of type `{type(value)}`"
            )
            raise ValueError(msg)

        parsed_type = _parse_parent_array_type(type_)
        type_value_pairs = [encode_field(types, name, parsed_type, item) for item in value]
        if not type_value_pairs:
            # the keccak hash of `encode((), ())`
            return (
                "bytes32",
                b"\xc5\xd2F\x01\x86\xf7#<\x92~}\xb2\xdc\xc7\x03\xc0\xe5\x00\xb6S\xca\x82';{\xfa\xd8\x04]\x85\xa4p",
            )

        data_types, data_hashes = zip(*type_value_pairs, strict=False)
        return ("bytes32", keccak(encode(data_types, data_hashes)))

    if type_ == "bool":
        return (type_, bool(value))

    # all bytes types allow hexstr and str values
    if type_.startswith("bytes"):
        if not isinstance(value, bytes):
            if _is_0x_prefixed_hexstr(value):
                value = _hexstr_to_bytes(value)
            elif isinstance(value, str):
                value = _text_to_bytes(value)
            else:
                if isinstance(value, int) and value < 0:
                    value = 0

                value = _int_to_bytes(value)

        return (
            # keccak hash if dynamic `bytes` type
            ("bytes32", keccak(value))
            if type_ == "bytes"
            # if fixed bytesXX type, do not hash
            else (type_, value)
        )

    if type_ == "string":
        value = _int_to_bytes(value) if isinstance(value, int) else _text_to_bytes(value)
        return ("bytes32", keccak(value))

    # allow string values for int and uint types
    if type(value) == str and type_.startswith(("int", "uint")):
        if _is_0x_prefixed_hexstr(value):
            return (type_, int(value, 16))
        return (type_, int(value))

    return (type_, value)


def find_type_dependencies(type_, types, results=None):
    if results is None:
        results = set()

    # a type must be a string
    if not isinstance(type_, str):
        msg = f"Invalid find_type_dependencies input: expected string, got `{type_}` of type `{type(type_)}`"
        raise ValueError(msg)
    # get core type if it's an array type
    type_ = _parse_core_array_type(type_)

    if (
        # don't look for dependencies of solidity types
        type_ in EIP712_SOLIDITY_TYPES
        # found a type that's already been added
        or type_ in results
    ):
        return results

    # found a type that isn't defined
    if type_ not in types:
        msg = f"No definition of type `{type_}`"
        raise ValueError(msg)

    results.add(type_)

    for field in types[type_]:
        find_type_dependencies(field["type"], types, results)
    return results


def encode_type(type_: str, types: dict[str, list[dict[str, str]]]) -> str:
    result = ""
    unsorted_deps = find_type_dependencies(type_, types)
    if type_ in unsorted_deps:
        unsorted_deps.remove(type_)

    deps = [type_, *sorted(unsorted_deps)]
    for type_ in deps:
        children_list = []
        for child in types[type_]:
            children_list.append("{} {}".format(child["type"], child["name"]))

        result += "{}({})".format(type_, ",".join(children_list))
    return result


def hash_type(type_: str, types: dict[str, list[dict[str, str]]]) -> bytes:
    return keccak(_text_to_bytes(encode_type(type_, types)))


def encode_data(
    type_: str,
    types: dict[str, list[dict[str, str]]],
    data: dict[str, Any],
) -> bytes:
    encoded_types: list[str] = ["bytes32"]
    encoded_values: list[bytes | int] = [hash_type(type_, types)]

    for field in types[type_]:
        type, value = encode_field(types, field["name"], field["type"], data.get(field["name"]))
        encoded_types.append(type)
        encoded_values.append(value)

    return encode(encoded_types, encoded_values)


def hash_struct(
    type_: str,
    types: dict[str, list[dict[str, str]]],
    data: dict[str, Any],
) -> bytes:
    encoded = encode_data(type_, types, data)
    return keccak(encoded)


def hash_eip712_message(
    # returns the same hash as `hash_struct`, but automatically determines primary type
    message_types: dict[str, list[dict[str, str]]],
    message_data: dict[str, Any],
) -> bytes:
    primary_type = get_primary_type(message_types)
    return keccak(encode_data(primary_type, message_types, message_data))


def hash_domain(domain_data: dict[str, Any]) -> bytes:
    eip712_domain_map = {
        "name": {"name": "name", "type": "string"},
        "version": {"name": "version", "type": "string"},
        "chainId": {"name": "chainId", "type": "uint256"},
        "verifyingContract": {"name": "verifyingContract", "type": "address"},
        "salt": {"name": "salt", "type": "bytes32"},
    }

    for k in domain_data:
        if k not in eip712_domain_map:
            msg = f"Invalid domain key: `{k}`"
            raise ValueError(msg)

    domain_types = {"EIP712Domain": [eip712_domain_map[k] for k in eip712_domain_map if k in domain_data]}

    return hash_struct("EIP712Domain", domain_types, domain_data)


class SignableMessage(NamedTuple):
    """
    A message compatible with EIP-191 that is ready to be signed.
    """

    version: bytes  # must be length 1
    header: bytes  # aka "version specific data"
    body: bytes  # aka "data to sign"


def encode_typed_data(
    domain_data: dict[str, Any] | None = None,
    message_types: dict[str, Any] | None = None,
    message_data: dict[str, Any] | None = None,
) -> SignableMessage:
    """
    Encode an EIP-712 message in a manner compatible with other implementations
    in use, such as the MetaMask and Ethers ``signTypedData`` functions.
    """
    return SignableMessage(
        b"\x01",
        hash_domain(domain_data),
        hash_eip712_message(message_types, message_data),
    )
