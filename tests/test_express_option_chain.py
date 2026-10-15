import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure modules/adapted/express-option-chain/src is in path
EXPRESS_SRC = Path(__file__).resolve().parent.parent / "modules" / "adapted" / "express-option-chain" / "src"
if str(EXPRESS_SRC) not in sys.path:
    sys.path.insert(0, str(EXPRESS_SRC))

from expressoptionchain.exceptions import OptionStreamValidationException
from expressoptionchain.option_stream import OptionStream


class TestExpressOptionStream:
    @patch("expressoptionchain.option_stream.KiteInstrumentManager")
    @patch("expressoptionchain.option_stream.KiteConnectionManager")
    @patch("expressoptionchain.option_stream.redis_helper.get_redis_instance")
    @patch("expressoptionchain.option_stream.KiteInstrumentFetcher")
    def test_option_stream_initialization_and_throttle(
        self, mock_fetcher, mock_redis_inst, mock_conn_mgr, mock_inst_mgr
    ):
        mock_db = MagicMock()
        mock_db.get.return_value = json.dumps(
            {"instrument_last_fetch_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        )
        mock_db.hkeys.return_value = ["NFO:HDFCBANK", "NFO:INFY"]
        mock_db.smembers.return_value = {"23-02-2023"}
        mock_redis_inst.return_value = mock_db

        fetcher_instance = MagicMock()
        fetcher_instance.get_tokens.return_value = [1001, 1002]
        mock_fetcher.return_value = fetcher_instance

        secrets = {"api_key": "test_key", "access_token": "test_token"}
        symbols = ["NFO:HDFCBANK", "NFO:INFY"]

        stream = OptionStream(
            trading_symbols=symbols,
            secrets=secrets,
            expiry="23-02-2023",
            throttle_interval=0.15,
        )

        assert stream.throttle_interval == 0.15
        assert stream.trading_symbols == symbols
        assert stream.expiry == "23-02-2023"

    @patch("expressoptionchain.option_stream.KiteInstrumentManager")
    @patch("expressoptionchain.option_stream.KiteConnectionManager")
    @patch("expressoptionchain.option_stream.redis_helper.get_redis_instance")
    @patch("expressoptionchain.option_stream.KiteInstrumentFetcher")
    def test_option_stream_validation_failure(
        self, mock_fetcher, mock_redis_inst, mock_conn_mgr, mock_inst_mgr
    ):
        mock_db = MagicMock()
        mock_db.get.return_value = json.dumps(
            {"instrument_last_fetch_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        )
        mock_redis_inst.return_value = mock_db

        secrets = {"api_key": "", "access_token": "test_token"}
        with pytest.raises(OptionStreamValidationException, match="Secrets does not contain api key"):
            OptionStream(
                trading_symbols=["NFO:HDFCBANK"],
                secrets=secrets,
                expiry="23-02-2023",
            )

    @patch("expressoptionchain.option_stream.time.sleep")
    @patch("expressoptionchain.option_stream.OptionChainCreator")
    @patch("expressoptionchain.option_stream.KiteInstrumentManager")
    @patch("expressoptionchain.option_stream.KiteConnectionManager")
    @patch("expressoptionchain.option_stream.redis_helper.get_redis_instance")
    @patch("expressoptionchain.option_stream.KiteInstrumentFetcher")
    def test_create_option_chain_throttling(
        self, mock_fetcher, mock_redis_inst, mock_conn_mgr, mock_inst_mgr, mock_creator_cls, mock_sleep
    ):
        mock_db = MagicMock()
        mock_db.get.return_value = json.dumps(
            {"instrument_last_fetch_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        )
        mock_db.hkeys.return_value = ["NFO:HDFCBANK"]
        mock_db.smembers.return_value = {"23-02-2023"}
        mock_redis_inst.return_value = mock_db

        fetcher_instance = MagicMock()
        fetcher_instance.get_tokens.return_value = [1001]
        mock_fetcher.return_value = fetcher_instance

        mock_creator = MagicMock()
        # Raise KeyboardInterrupt after 1 loop iteration to break while True loop cleanly
        mock_creator.create_option_chain.side_effect = [None, KeyboardInterrupt()]
        mock_creator_cls.return_value = mock_creator

        secrets = {"api_key": "test_key", "access_token": "test_token"}
        stream = OptionStream(
            trading_symbols=["NFO:HDFCBANK"],
            secrets=secrets,
            expiry="23-02-2023",
            throttle_interval=0.25,
        )

        with pytest.raises(KeyboardInterrupt):
            stream.create_option_chain()

        assert mock_sleep.called
        # Check that sleep duration was approximately throttle_interval (<= 0.25)
        sleep_arg = mock_sleep.call_args[0][0]
        assert 0.0 < sleep_arg <= 0.25
