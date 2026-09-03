"""
NSEFO All 26 Broker Integrations & Configuration Registry (EQATS Institutional Adaptation).
Adapted from sparlit/nsefo (NSE Futures & Options Broker Gateway Architecture)

Provides configurations and endpoint specifications for all 26 supported Indian NSE brokers:
1. Dhan (SDK)
2. Dhan Fenix Gateway
3. Zerodha Kite Connect
4. AngelOne SmartAPI
5. Upstox REST API
6. Fyers API v2
7. Kotak Securities
8. Kotak Neo
9. 5paisa
10. IIFL Markets
11. Motilal Oswal
12. Finvasia (Shoonya)
13. AliceBlue
14. Choice Broking
15. HDFC Securities
16. ICICI Direct (OAuth2)
17. SBI Securities
18. Bajaj Financial
19. Geojit
20. Sharekhan
21. Anand Rathi
22. Edelweiss
23. Axis Direct
24. Groww
25. Moneysukh
26. Master Trust
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import database

logger = logging.getLogger("NSeFoBrokerRegistry")


@dataclass
class NSeFoBrokerSpec:
    key: str
    display_name: str
    auth_type: str
    protocol_type: str
    rest_url: str
    ws_url: str
    required_fields: list[str]


NSEFO_BROKERS_REGISTRY: dict[str, NSeFoBrokerSpec] = {
    "dhan": NSeFoBrokerSpec(
        key="dhan",
        display_name="Dhan (SDK)",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.dhan.co",
        ws_url="wss://api-feed.dhan.co",
        required_fields=["client_id", "access_token"],
    ),
    "fenix_dhan": NSeFoBrokerSpec(
        key="fenix_dhan",
        display_name="Dhan (Fenix)",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.dhan.co",
        ws_url="wss://api-feed.dhan.co",
        required_fields=["client_id", "access_token"],
    ),
    "zerodha": NSeFoBrokerSpec(
        key="zerodha",
        display_name="Zerodha Kite Connect",
        auth_type="api_key_token",
        protocol_type="REST_WS",
        rest_url="https://api.kite.trade",
        ws_url="wss://ws.kite.trade",
        required_fields=["api_key", "access_token"],
    ),
    "angelone": NSeFoBrokerSpec(
        key="angelone",
        display_name="AngelOne SmartAPI",
        auth_type="totp",
        protocol_type="REST_WS",
        rest_url="https://apiconnect.angelone.in",
        ws_url="wss://smartapisocket.angelone.in/smart-stream",
        required_fields=["client_id", "password", "totp_secret", "api_key"],
    ),
    "upstox": NSeFoBrokerSpec(
        key="upstox",
        display_name="Upstox REST API",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.upstox.com/v2",
        ws_url="wss://api.upstox.com/v2/feed",
        required_fields=["client_id", "access_token"],
    ),
    "fyers": NSeFoBrokerSpec(
        key="fyers",
        display_name="Fyers API v2",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api-v2.fyers.in/api/v2",
        ws_url="wss://api-v2.fyers.in/socket/v2",
        required_fields=["client_id", "access_token"],
    ),
    "kotak": NSeFoBrokerSpec(
        key="kotak",
        display_name="Kotak Securities",
        auth_type="consumer_key_token",
        protocol_type="REST_WS",
        rest_url="https://tradeapi.kotaksecurities.com/apim/orders/1.0",
        ws_url="wss://tradeapi.kotaksecurities.com/apim/streaming/1.0",
        required_fields=["consumer_key", "access_token"],
    ),
    "kotak_neo": NSeFoBrokerSpec(
        key="kotak_neo",
        display_name="Kotak Neo API",
        auth_type="consumer_key_token",
        protocol_type="REST_WS",
        rest_url="https://gw-napi.kotaksecurities.com",
        ws_url="wss://gw-napi.kotaksecurities.com",
        required_fields=["consumer_key", "access_token"],
    ),
    "fivepaisa": NSeFoBrokerSpec(
        key="fivepaisa",
        display_name="5paisa Markets",
        auth_type="totp",
        protocol_type="REST_WS",
        rest_url="https://openapi.5paisa.com/VendorsAPI/V1",
        ws_url="wss://openfeed.5paisa.com/Feeds/api/chat",
        required_fields=["client_id", "password", "totp_secret", "app_key"],
    ),
    "iifl": NSeFoBrokerSpec(
        key="iifl",
        display_name="IIFL Markets",
        auth_type="api_key_password",
        protocol_type="REST_WS",
        rest_url="https://ttblaze.iifl.com/apimarketdata",
        ws_url="wss://ttblaze.iifl.com/apisocket",
        required_fields=["api_key", "password", "client_id"],
    ),
    "motilal": NSeFoBrokerSpec(
        key="motilal",
        display_name="Motilal Oswal",
        auth_type="api_key_password",
        protocol_type="REST_WS",
        rest_url="https://api.motilaloswal.com/v1",
        ws_url="wss://api.motilaloswal.com/v1/stream",
        required_fields=["api_key", "password", "client_id"],
    ),
    "finvasia": NSeFoBrokerSpec(
        key="finvasia",
        display_name="Finvasia (Shoonya)",
        auth_type="totp",
        protocol_type="REST_WS",
        rest_url="https://api.shoonya.com/NorenWSTp",
        ws_url="wss://api.shoonya.com/NorenWSTp",
        required_fields=["client_id", "password", "totp_secret", "vendor_code", "yob"],
    ),
    "aliceblue": NSeFoBrokerSpec(
        key="aliceblue",
        display_name="AliceBlue ANT",
        auth_type="app_code_secret",
        protocol_type="REST_WS",
        rest_url="https://ant.aliceblueonline.com/rest/AliceBlueAPIService",
        ws_url="wss://ws1.aliceblueonline.com/NXTWs",
        required_fields=["client_id", "app_code", "api_secret"],
    ),
    "choice": NSeFoBrokerSpec(
        key="choice",
        display_name="Choice Broking",
        auth_type="totp",
        protocol_type="REST_WS",
        rest_url="https://api.choiceindia.com/v1",
        ws_url="wss://api.choiceindia.com/v1/stream",
        required_fields=["client_id", "totp_secret"],
    ),
    "hdfc": NSeFoBrokerSpec(
        key="hdfc",
        display_name="HDFC Securities",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.hdfcsec.com/v1",
        ws_url="wss://api.hdfcsec.com/v1/feed",
        required_fields=["client_id", "access_token"],
    ),
    "icici": NSeFoBrokerSpec(
        key="icici",
        display_name="ICICI Direct (Breeze)",
        auth_type="oauth2",
        protocol_type="REST_WS",
        rest_url="https://api.icicidirect.com/breezeapi/v1",
        ws_url="wss://breezews.icicidirect.com",
        required_fields=["api_key", "api_secret", "refresh_token"],
    ),
    "sbi": NSeFoBrokerSpec(
        key="sbi",
        display_name="SBI Securities",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.sbisecurities.in/v1",
        ws_url="wss://api.sbisecurities.in/v1/stream",
        required_fields=["client_id", "access_token", "app_name"],
    ),
    "bajaj": NSeFoBrokerSpec(
        key="bajaj",
        display_name="Bajaj Financial",
        auth_type="api_key_token",
        protocol_type="REST_WS",
        rest_url="https://api.bajajbroking.in/v1",
        ws_url="wss://api.bajajbroking.in/v1/stream",
        required_fields=["api_key", "client_id", "access_token"],
    ),
    "geojit": NSeFoBrokerSpec(
        key="geojit",
        display_name="Geojit Financial",
        auth_type="password_yob",
        protocol_type="REST_WS",
        rest_url="https://api.geojit.com/v1",
        ws_url="wss://api.geojit.com/v1/stream",
        required_fields=["client_id", "password", "yob"],
    ),
    "sharekhan": NSeFoBrokerSpec(
        key="sharekhan",
        display_name="Sharekhan (Mirae Asset)",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.sharekhan.com/v1",
        ws_url="wss://api.sharekhan.com/v1/stream",
        required_fields=["client_id", "access_token"],
    ),
    "anand_rathi": NSeFoBrokerSpec(
        key="anand_rathi",
        display_name="Anand Rathi",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.rathi.com/v1",
        ws_url="wss://api.rathi.com/v1/stream",
        required_fields=["client_id", "access_token"],
    ),
    "edelweiss": NSeFoBrokerSpec(
        key="edelweiss",
        display_name="Edelweiss (Nuvama)",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.nuvama.com/v1",
        ws_url="wss://api.nuvama.com/v1/stream",
        required_fields=["client_id", "access_token"],
    ),
    "axis_direct": NSeFoBrokerSpec(
        key="axis_direct",
        display_name="Axis Direct",
        auth_type="client_id_token",
        protocol_type="REST_WS",
        rest_url="https://api.axisdirect.in/v1",
        ws_url="wss://api.axisdirect.in/v1/stream",
        required_fields=["client_id", "access_token"],
    ),
    "groww": NSeFoBrokerSpec(
        key="groww",
        display_name="Groww Trade API",
        auth_type="api_key_token",
        protocol_type="REST_WS",
        rest_url="https://api.groww.in/v1",
        ws_url="wss://api.groww.in/v1/stream",
        required_fields=["api_key", "access_token"],
    ),
    "moneysukh": NSeFoBrokerSpec(
        key="moneysukh",
        display_name="Moneysukh",
        auth_type="api_key_client",
        protocol_type="REST_WS",
        rest_url="https://api.moneysukh.com/v1",
        ws_url="wss://api.moneysukh.com/v1/stream",
        required_fields=["client_id", "api_key"],
    ),
    "master_trust": NSeFoBrokerSpec(
        key="master_trust",
        display_name="Master Trust",
        auth_type="app_key",
        protocol_type="REST_WS",
        rest_url="https://api.mastertrust.co.in/v1",
        ws_url="wss://api.mastertrust.co.in/v1/stream",
        required_fields=["client_id", "app_key"],
    ),
}


class NSeFoBrokerConfigManager:
    """
    Manager for registering and retrieving broker accounts from the 26 NSEFO broker registry.
    """

    def get_broker_spec(self, broker_key: str) -> NSeFoBrokerSpec | None:
        """Retrieves spec for given broker key."""
        return NSEFO_BROKERS_REGISTRY.get(broker_key.lower())

    def register_broker_account(
        self,
        broker_key: str,
        account_id: str,
        password: str = "",
        api_key: str = "",
        api_secret: str = "",
        environment: str = "Demo",
        is_active: bool = False,
    ) -> bool:
        """Registers an NSEFO broker account in the database."""
        spec = self.get_broker_spec(broker_key)
        if not spec:
            logger.error("Unknown NSEFO broker key: %s", broker_key)
            return False
        database.add_broker_account(
            broker_name=spec.display_name,
            server=broker_key,
            account_id=account_id,
            password=password,
            leverage="1:100",
            environment=environment,
            protocol_type=spec.protocol_type,
            api_key=api_key,
            api_secret=api_secret,
            rest_url=spec.rest_url,
            ws_url=spec.ws_url,
            is_active=1 if is_active else 0,
        )
        return True

    def list_all_supported_brokers(self) -> list[dict[str, Any]]:
        """Lists metadata for all 26 supported NSEFO brokers."""
        return [
            {
                "key": spec.key,
                "display_name": spec.display_name,
                "auth_type": spec.auth_type,
                "protocol_type": spec.protocol_type,
                "rest_url": spec.rest_url,
            }
            for spec in NSEFO_BROKERS_REGISTRY.values()
        ]
