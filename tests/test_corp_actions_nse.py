import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add modules/adapted/tickdownload to path for import compatibility
tickdownload_dir = str(Path(__file__).resolve().parent.parent / "modules" / "adapted" / "tickdownload")
if tickdownload_dir not in sys.path:
    sys.path.insert(0, tickdownload_dir)

# Mock tickerplot dependencies if tickerplot package is not directly installed in environment
mock_tickerplot = MagicMock()
mock_tickerplot_nse_utils = MagicMock()
mock_tickerplot_wrapper = MagicMock()
mock_tickerplot_logger = MagicMock()

sys.modules.setdefault("tickerplot", mock_tickerplot)
sys.modules.setdefault("tickerplot.nse", MagicMock())
sys.modules.setdefault("tickerplot.nse.nse_utils", mock_tickerplot_nse_utils)
sys.modules.setdefault("tickerplot.sql", MagicMock())
sys.modules.setdefault("tickerplot.sql.sqlalchemy_wrapper", mock_tickerplot_wrapper)
sys.modules.setdefault("tickerplot.utils", MagicMock())
sys.modules.setdefault("tickerplot.utils.logger", mock_tickerplot_logger)

import pandas as pd  # noqa: E402, I001

from corp_actions_nse import (  # noqa: E402, I001
    CorpAction,
    _CorpActionAll,
    _do_process_purpose,
    _process_ca_text,
    _process_purpose,
    adjust_prices_for_bonus_split,
    is_ist_market_session_active,
    process_corp_actions_from_date,
    round_to_ist_tick,
)


class TestCorpActionsNSE(unittest.TestCase):

    def setUp(self):
        self.sample_ca_all = [
            _CorpActionAll(
                sym="INFY",
                name="Infosys Ltd",
                industry="IT",
                series="EQ",
                fv="5",
                purpose="Bonus 1:1",
                ex_date=datetime.date(2018, 9, 4),
                rec_date="05-Sep-2018",
                bc_sdate="",
                bc_edate="",
                nd_sdate="",
                nd_edate="",
            ),
            _CorpActionAll(
                sym="INFY",
                name="Infosys Ltd",
                industry="IT",
                series="EQ",
                fv="5",
                purpose="Face Value Split From Rs 10 To Rs 5",
                ex_date=datetime.date(2020, 1, 15),
                rec_date="16-Jan-2020",
                bc_sdate="",
                bc_edate="",
                nd_sdate="",
                nd_edate="",
            ),
            _CorpActionAll(
                sym="INFY",
                name="Infosys Ltd",
                industry="IT",
                series="EQ",
                fv="5",
                purpose="Dividend Rs 12.50 Per Share",
                ex_date=datetime.date(2021, 6, 1),
                rec_date="02-Jun-2021",
                bc_sdate="",
                bc_edate="",
                nd_sdate="",
                nd_edate="",
            ),
        ]

    def test_do_process_purpose_bonus_and_split(self):
        ca_bonus = self.sample_ca_all[0]
        actions = _do_process_purpose(ca_bonus)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "B")
        self.assertAlmostEqual(actions[0].ratio, 0.5)

        ca_split = self.sample_ca_all[1]
        actions_split = _do_process_purpose(ca_split)
        self.assertEqual(len(actions_split), 1)
        self.assertEqual(actions_split[0].action, "S")
        self.assertAlmostEqual(actions_split[0].ratio, 0.5)

    def test_do_process_purpose_dividend(self):
        ca_div = self.sample_ca_all[2]
        actions = _do_process_purpose(ca_div)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "D")
        self.assertEqual(actions[0].delta, 12.50)

    def test_process_purpose_with_filter(self):
        actions = _process_purpose(self.sample_ca_all, start_date="2019-01-01", action_types=["B", "S"])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "S")
        self.assertEqual(actions[0].ex_date, datetime.date(2020, 1, 15))

    def test_process_corp_actions_from_date_and_types(self):
        corp_actions = [
            CorpAction("INFY", datetime.date(2015, 1, 1), "B", 0.5, 0.0),
            CorpAction("INFY", datetime.date(2018, 9, 4), "B", 0.5, 0.0),
            CorpAction("INFY", datetime.date(2020, 1, 15), "S", 0.5, 0.0),
            CorpAction("INFY", datetime.date(2021, 6, 1), "D", 1.0, 12.5),
        ]

        # Filter from 2018-01-01
        res = process_corp_actions_from_date(corp_actions, start_date="2018-01-01")
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0].ex_date, datetime.date(2018, 9, 4))

        # Filter bonus and split only
        res_bs = process_corp_actions_from_date(corp_actions, action_types=["B", "S"])
        self.assertEqual(len(res_bs), 3)
        self.assertTrue(all(a.action in ["B", "S"] for a in res_bs))

        # Filter from 2019-01-01 for Bonus/Split
        res_combined = process_corp_actions_from_date(
            corp_actions, start_date=datetime.date(2019, 1, 1), action_types=["B", "S"]
        )
        self.assertEqual(len(res_combined), 1)
        self.assertEqual(res_combined[0].action, "S")

    def test_adjust_prices_for_bonus_split(self):
        dates = pd.date_range("2018-08-30", periods=10, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100.0] * 10,
                "High": [105.0] * 10,
                "Low": [95.0] * 10,
                "Close": [100.0] * 10,
                "Volume": [1000] * 10,
            },
            index=dates,
        )

        actions = [CorpAction("INFY", datetime.date(2018, 9, 4), "B", 0.5, 0.0)]

        adj_df = adjust_prices_for_bonus_split(df, actions, start_date="2018-01-01")

        # Prior to ex_date (2018-09-04), close should be halved (50.0) and volume doubled (2000)
        pre_mask = adj_df.index < pd.Timestamp("2018-09-04")
        post_mask = adj_df.index >= pd.Timestamp("2018-09-04")

        self.assertTrue((adj_df.loc[pre_mask, "Close"] == 50.0).all())
        self.assertTrue((adj_df.loc[pre_mask, "Volume"] == 2000.0).all())

        # On or after ex_date, prices remain unadjusted
        self.assertTrue((adj_df.loc[post_mask, "Close"] == 100.0).all())
        self.assertTrue((adj_df.loc[post_mask, "Volume"] == 1000.0).all())

    def test_process_ca_text(self):
        raw_csv = (
            '"Symbol","Company","Industry","Series","Face Value(Rs.)","Purpose","Ex-Date","Record Date","BC Start Date","BC End Date","No Delivery Start Date","No Delivery End Date"\n'
            '"INFY","Infosys Ltd","IT","EQ","5","Bonus 1:1","04-Sep-2018","05-Sep-2018","","","",""\n'
            '"INFY","Infosys Ltd","IT","EQ","5","Dividend Rs 12.50","01-Jun-2021","02-Jun-2021","","","",""\n'
        )

        actions = _process_ca_text(raw_csv, start_date="2020-01-01")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "D")

    def test_ist_market_session_and_tick(self):
        self.assertEqual(round_to_ist_tick(100.03), 100.05)
        self.assertEqual(round_to_ist_tick(0.0), 0.0)

        dt_weekday_market = datetime.datetime(2023, 10, 16, 10, 0, 0, tzinfo=datetime.UTC)
        self.assertTrue(is_ist_market_session_active(dt_weekday_market))


if __name__ == "__main__":
    unittest.main()
