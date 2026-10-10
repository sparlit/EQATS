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


import datetime

import psycopg2


def get_max_pain(symbol, lot_size, trade_date_str, fix_expiry_date_str):
    eq_sql = """
        select symbol, trade_Date, close from nse_cash_market_tab
        where symbol = 'TATAMOTORS' and trade_Date = to_Date('2011-11-11','yyyy-MM-dd')
    """
    call_sql = """
        select symbol, trade_date, expiry_date, option_type, strike_price strike, close, open_int/2800 oi, change_in_oi/2800 oic
        from nse_option_market_tab
        where symbol = 'TATAMOTORS' and option_type = 'CE' and trade_Date = to_Date('2011-11-11','yyyy-MM-dd')
        and feds = '2011-11-25'
        order by strike_price
    """
    putt_sql = """
        select symbol, trade_date, expiry_date, option_type, strike_price strike, close, open_int/2800 oi, change_in_oi/2800 oic
        from nse_option_market_tab
        where symbol = 'TATAMOTORS' and option_type = 'PE' and trade_Date = to_Date('2011-11-11','yyyy-MM-dd')
        and feds = '2011-11-25'
        order by strike_price
    """
    eq_sql = eq_sql.replace("TATAMOTORS", symbol)
    call_sql = call_sql.replace("TATAMOTORS", symbol)
    putt_sql = putt_sql.replace("TATAMOTORS", symbol)

    call_sql = call_sql.replace("2800", str(lot_size))
    putt_sql = putt_sql.replace("2800", str(lot_size))

    eq_sql = eq_sql.replace("2011-11-11", trade_date_str)
    call_sql = call_sql.replace("2011-11-11", trade_date_str)
    putt_sql = putt_sql.replace("2011-11-11", trade_date_str)

    call_sql = call_sql.replace("2011-11-25", fix_expiry_date_str)
    putt_sql = putt_sql.replace("2011-11-25", fix_expiry_date_str)

    connection = psycopg2.connect(
        database="postgres", user="postgres", password="postgres", host="localhost", port=5432
    )
    cursor = connection.cursor()

    cursor.execute(eq_sql)
    eq_records = cursor.fetchall()

    cursor.execute(call_sql)

    # print(datetime.datetime.now())
    call_records = cursor.fetchall()
    # print(datetime.datetime.now())

    # print('symbol, trade_date, expiry_date, option_type, strike_price strike, close,  oi,oic')
    # for each_record in call_records:
    #     print(each_record)

    cursor.execute(putt_sql)

    # print(datetime.datetime.now())
    putt_records = cursor.fetchall()
    # print(datetime.datetime.now())

    # print('symbol, trade_date, expiry_date, option_type, strike_price strike, close,  oi,oic')
    # for each_record in putt_records:
    #     print(each_record)

    # print("Data from Database:- ", records)
    connection.close()
    # ================================================================================================
    eq_close = 0
    for each_record in eq_records:
        eq_close = each_record[2]

    strike_map = {}
    strike_array = []

    for each_record in call_records:
        strike_map[each_record[4]] = each_record[4]

    for each_record in putt_records:
        strike_map[each_record[4]] = each_record[4]

    for each_key in strike_map:
        strike_array.append(each_key)

    call_vertical_sum_map = {}
    putt_vertical_sum_map = {}
    for each_strike in strike_array:
        call_vertical_sum_map[each_strike] = 0
        putt_vertical_sum_map[each_strike] = 0

    # --------------------------------------------------------------------------------------------------
    lot_size = lot_size
    call_strike_to_oi_map = {}
    call_strike_to_close_map = {}
    ce_total_oi = 0

    for each_record in call_records:
        strike = each_record[4]
        oi = each_record[6]
        call_strike_to_oi_map[strike] = oi
        ce_total_oi = ce_total_oi + oi
        close = each_record[5]
        call_strike_to_close_map[strike] = float(close)

    for vertical_strike in strike_array:
        oi = call_strike_to_oi_map.get(vertical_strike, 0)
        for horizontal_strike in strike_array:
            # calc is reverse or pe
            intrinsic_value = horizontal_strike - vertical_strike
            calculated_value = intrinsic_value * oi * lot_size if intrinsic_value > 0 else 0
            call_vertical_sum_map[horizontal_strike] = (
                call_vertical_sum_map[horizontal_strike] + calculated_value
            )

    # ---------------------------------------------------------------------------------------
    lot_size = lot_size
    putt_strike_to_oi_map = {}
    putt_strike_to_close_map = {}
    pe_total_oi = 0

    for each_record in putt_records:
        strike = each_record[4]
        oi = each_record[6]
        putt_strike_to_oi_map[strike] = oi
        pe_total_oi = pe_total_oi + oi
        close = each_record[5]
        putt_strike_to_close_map[strike] = float(close)

    for vertical_strike in strike_array:
        oi = putt_strike_to_oi_map.get(vertical_strike, 0)
        for horizontal_strike in strike_array:
            # calc is reverse or cal
            intrinsic_value = vertical_strike - horizontal_strike
            calculated_value = intrinsic_value * oi * lot_size if intrinsic_value > 0 else 0
            putt_vertical_sum_map[horizontal_strike] = (
                putt_vertical_sum_map[horizontal_strike] + calculated_value
            )

    # ---------------------------------------------------------------------------------------
    putt_call_array = []
    putt_call_map = {}
    for each_strike in strike_array:
        cal_sum = call_vertical_sum_map.get(each_strike, 0)
        putt_sum = putt_vertical_sum_map.get(each_strike, 0)
        putt_cal = cal_sum + putt_sum
        putt_call_map[each_strike] = putt_cal
        if putt_cal > 0:
            putt_call_array.append(putt_cal)

    putt_call_array.sort()
    # print(putt_call_array[0])

    max_pain = 0
    if len(putt_call_array) > 0:
        m = putt_call_array[0]
        for each_strike in putt_call_map:
            if putt_call_map[each_strike] == m:
                # print(each_strike)
                max_pain = each_strike

    # ---------------------------------------------------------------------------------------
    call_oi_list = list(call_strike_to_oi_map.values())
    call_oi_list.sort(reverse=True)

    call_max_oi = call_oi_list[0] if len(call_oi_list) > 0 else 0

    #
    putt_oi_list = list(putt_strike_to_oi_map.values())
    putt_oi_list.sort(reverse=True)

    putt_max_oi = putt_oi_list[0] if len(putt_oi_list) > 0 else 0

    #
    support = 0
    resistance = 0
    call_close = 0
    putt_close = 0
    for each_strike in strike_array:
        local_putt_strike_to_oi = putt_strike_to_oi_map[each_strike]
        if putt_max_oi == local_putt_strike_to_oi:
            support = each_strike
            putt_close = putt_strike_to_close_map[each_strike]
        local_call_strike_to_oi = call_strike_to_oi_map[each_strike]
        if call_max_oi == local_call_strike_to_oi:
            resistance = each_strike
            call_close = call_strike_to_close_map[each_strike]

    return (
        float(support),
        putt_max_oi,
        pe_total_oi,
        putt_close,
        float(max_pain),
        float(resistance),
        call_max_oi,
        ce_total_oi,
        call_close,
        eq_close,
    )

    # =====================================================================
    # wb = xw.Book() # wb = xw.Book(filename) would open an existing file
    #
    # # creates a worksheet object assigns it to ws
    # ws1 = wb.sheets["Sheet1"]
    # ws1.name = "ce-max-pain"
    #
    # #ws.range("A1") is a Range object
    # ws1.range("C1").value = strike_array
    # array_idx = 0
    # for each_strike in strike_array:
    #     cell_value = strike_array[array_idx]
    #     array_idx = array_idx + 1
    #     cell_idx = array_idx + 3
    #     cell_name = "A" + str(cell_idx)
    #     ws1.range(cell_name).value = cell_value
    #     #
    #     oi_cell_name = "B" + str(cell_idx)
    #     if cell_value in ce_oi_map:
    #         oi_value = ce_oi_map[cell_value]
    #     else:
    #         oi_value = 0
    #     ws1.range(oi_cell_name).value = oi_value
    #
    #
    # # ws.clear_contents()
    # # ws.range("A1").options(index=False).value = strike_array
    #
    # wb.save('ce-max-pain-1.xlsx')
    # # xw.apps[0].quit()
    #
    # # ---------------------------------------------------------------------------------------
    # wb2 = xw.Book() # wb = xw.Book(filename) would open an existing file
    #
    # #creates a worksheet object assigns it to ws
    # ws2 = wb2.sheets["Sheet1"]
    # # ws2.name = "pe-max-pain"
    #
    # #ws.range("A1") is a Range object
    # ws2.range("C1").value = strike_array
    # array_idx = 0
    # for each_strike in strike_array:
    #     cell_value = strike_array[array_idx]
    #     array_idx = array_idx + 1
    #     cell_idx = array_idx + 3
    #     cell_name = "A" + str(cell_idx)
    #     ws2.range(cell_name).value = cell_value
    #     #
    #     oi_cell_name = "B" + str(cell_idx)
    #     if cell_value in pe_oi_map:
    #         oi_value = pe_oi_map[cell_value]
    #     else:
    #         oi_value = 0
    #     ws2.range(oi_cell_name).value = oi_value
    #
    #
    # # ws.clear_contents()
    # # ws.range("A1").options(index=False).value = strike_array
    #
    # wb2.save('pe-max-pain-1.xlsx')
    # xw.apps[0].quit()
