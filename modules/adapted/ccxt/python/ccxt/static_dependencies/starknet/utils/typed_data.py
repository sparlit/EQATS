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


from dataclasses import dataclass
from typing import Dict, List, Union, cast

from ..cairo.felt import encode_shortstring
from ..hash.selector import get_selector_from_name
from ..hash.utils import compute_hash_on_elements
from ..models.typed_data import StarkNetDomainDict, TypedDataDict


@dataclass(frozen=True)
class Parameter:
    """
    Dataclass representing a Parameter object
    """

    name: str
    type: str


@dataclass(frozen=True)
class TypedData:
    """
    Dataclass representing a TypedData object
    """

    types: dict[str, list[Parameter]]
    primary_type: str
    domain: StarkNetDomainDict
    message: dict

    @staticmethod
    def from_dict(data: TypedDataDict) -> "TypedData":
        """
        Create TypedData dataclass from dictionary.

        :param data: TypedData dictionary.
        :return: TypedData dataclass instance.
        """
        return _typed_data_from_dict(data)

    def _is_struct(self, type_name: str) -> bool:
        return type_name in self.types

    def _encode_value(self, type_name: str, value: int | str | dict | list) -> int:
        if is_pointer(type_name) and isinstance(value, list):
            type_name = strip_pointer(type_name)

            if self._is_struct(type_name):
                return compute_hash_on_elements([self.struct_hash(type_name, data) for data in value])
            return compute_hash_on_elements([int(get_hex(val), 16) for val in value])

        if self._is_struct(type_name) and isinstance(value, dict):
            return self.struct_hash(type_name, value)

        value = cast("int | str", value)
        return int(get_hex(value), 16)

    def _encode_data(self, type_name: str, data: dict) -> list[int]:
        values = []
        for param in self.types[type_name]:
            encoded_value = self._encode_value(param.type, data[param.name])
            values.append(encoded_value)

        return values

    def _get_dependencies(self, type_name: str) -> list[str]:
        if type_name not in self.types:
            # type_name is a primitive type, has no dependencies
            return []

        dependencies = set()

        def collect_deps(type_name: str) -> None:
            for param in self.types[type_name]:
                fixed_type = strip_pointer(param.type)
                if fixed_type in self.types and fixed_type not in dependencies:
                    dependencies.add(fixed_type)
                    # recursive call
                    collect_deps(fixed_type)

        # collect dependencies into a set
        collect_deps(type_name)
        return [type_name, *list(dependencies)]

    def _encode_type(self, type_name: str) -> str:
        primary, *dependencies = self._get_dependencies(type_name)
        types = [primary, *sorted(dependencies)]

        def make_dependency_str(dependency):
            lst = [f"{t.name}:{t.type}" for t in self.types[dependency]]
            return f"{dependency}({','.join(lst)})"

        return "".join([make_dependency_str(x) for x in types])

    def type_hash(self, type_name: str) -> int:
        """
        Calculate the hash of a type name.

        :param type_name: Name of the type.
        :return: Hash of the type name.
        """
        return get_selector_from_name(self._encode_type(type_name))

    def struct_hash(self, type_name: str, data: dict) -> int:
        """
        Calculate the hash of a struct.

        :param type_name: Name of the type.
        :param data: Data defining the struct.
        :return: Hash of the struct.
        """
        return compute_hash_on_elements([self.type_hash(type_name), *self._encode_data(type_name, data)])

    def message_hash(self, account_address: int) -> int:
        """
        Calculate the hash of the message.

        :param account_address: Address of an account.
        :return: Hash of the message.
        """
        message = [
            encode_shortstring("StarkNet Message"),
            self.struct_hash("StarkNetDomain", cast("dict", self.domain)),
            account_address,
            self.struct_hash(self.primary_type, self.message),
        ]

        return compute_hash_on_elements(message)


def get_hex(value: int | str) -> str:
    if isinstance(value, int):
        return hex(value)
    if value[:2] == "0x":
        return value
    if value.isnumeric():
        return hex(int(value))
    return hex(encode_shortstring(value))


def is_pointer(value: str) -> bool:
    return len(value) > 0 and value[-1] == "*"


def strip_pointer(value: str) -> str:
    if is_pointer(value):
        return value[:-1]
    return value


# Plain-dict validation replacing the former marshmallow ParameterSchema/TypedDataSchema.
# Malformed input raises ValueError (marshmallow raised ValidationError, a ValueError subclass).


def _expect_str(value, where: str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if not isinstance(value, str):
        msg = f"{where}: Not a valid string."
        raise ValueError(msg)
    return value


def _expect_dict(value, where: str) -> dict:
    if not isinstance(value, dict):
        msg = f"{where}: Not a valid mapping type."
        raise ValueError(msg)
    return dict(value)


def _parse_parameter(raw, where: str) -> Parameter:
    raw = _expect_dict(raw, where)
    extra = set(raw) - {"name", "type"}
    if extra:
        msg = f"{where}: Unknown field(s) {sorted(extra)}."
        raise ValueError(msg)
    for key in ("name", "type"):
        if key not in raw:
            msg = f"{where}.{key}: Missing data for required field."
            raise ValueError(msg)
    return Parameter(
        name=_expect_str(raw["name"], f"{where}.name"),
        type=_expect_str(raw["type"], f"{where}.type"),
    )


def _typed_data_from_dict(data) -> TypedData:
    data = _expect_dict(data, "typedData")
    extra = set(data) - {"types", "primaryType", "domain", "message"}
    if extra:
        msg = f"typedData: Unknown field(s) {sorted(extra)}."
        raise ValueError(msg)
    for key in ("types", "primaryType", "domain", "message"):
        if key not in data:
            msg = f"typedData.{key}: Missing data for required field."
            raise ValueError(msg)
    raw_types = _expect_dict(data["types"], "typedData.types")
    types: dict[str, list[Parameter]] = {}
    for type_name, params in raw_types.items():
        type_name = _expect_str(type_name, "typedData.types<key>")
        if not isinstance(params, (list, tuple)):
            msg = f"typedData.types.{type_name}: Not a valid list."
            raise ValueError(msg)
        types[type_name] = [
            _parse_parameter(param, f"typedData.types.{type_name}[{i}]") for i, param in enumerate(params)
        ]
    return TypedData(
        types=types,
        primary_type=_expect_str(data["primaryType"], "typedData.primaryType"),
        domain=cast("StarkNetDomainDict", _expect_dict(data["domain"], "typedData.domain")),
        message=_expect_dict(data["message"], "typedData.message"),
    )
