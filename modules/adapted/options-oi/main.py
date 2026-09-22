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


#!/usr/bin/env python

import tkinter as tk

import json_handler
import plot

# global value holders
index_value = 0
expiry_value = 0
spot_price, strike_prices_list, expiry_dates_list = 0, [], []

# Start of the UI

# Create a base window for all the user interactions


def ui_space():

    global index_value

    indices_list = ["NIFTY", "BANKNIFTY"]

    # Create an instance of tkinter frame
    ui_win = tk.Tk()

    # Rename window title
    ui_win.title("Open interest analysis from Option chain API")

    # Define the size of window or frame
    ui_win.geometry("715x250")

    # Place the window at the center of the screen
    ui_win.eval("tk::PlaceWindow . center")

    def destroyer():

        ui_win.quit()
        ui_win.destroy()

    # Destroy windows on main window close detection and exit python
    ui_win.wm_protocol("WM_DELETE_WINDOW", destroyer)

    def plot_api_data():

        # forget all available widgets in the frame
        for widget in ui_win.slaves():
            widget.pack_forget()

        global spot_price
        global strike_prices_list
        global expiry_dates_list
        global expiry_value

        expiry_value = selection.get()

        print(f"Spot before passing : {spot_price}, expiry date = {expiry_value}")

        plot.plot_open_interest_data(
            spot=spot_price,
            strikes=strike_prices_list,
            expiry_list=expiry_dates_list,
            expiry=expiry_value,
            index=index_value,
            container_window=ui_win,
        )

    def process_api_data():

        global spot_price
        global strike_prices_list
        global expiry_dates_list
        global expiry_value
        #  get the needed data from json api downloaded data for further processing
        (
            spot_price,
            strike_prices_list,
            expiry_dates_list,
        ) = json_handler.filter_OC_json_data()

        #  Update reusable elements for this use case
        reusable_label.config(text=f"{index_value} Spot : {spot_price}", font="50", fg="brown")

        selection.set("Select Expiry Date")
        new_drop_down = tk.OptionMenu(ui_win, selection, *expiry_dates_list)
        new_drop_down.config(bg="lightblue")
        new_drop_down.pack()

        reusable_load_button.config(text="Plot OI", command=plot_api_data)
        reusable_load_button.pack()

    def fetch_api_data():

        global index_value

        index_value = selection.get()

        print(f"Button works ! and current value of buffer is :  {index_value}")

        if index_value != 0:
            #  once selction is available and button pressed pack_forget existing widgets to clear view
            reusable_drop_down.pack_forget()
            reusable_load_button.pack_forget()

            #  Downloading data message
            reusable_label.config(font="50", fg="green", text="Downloading data from NSE.............")
            reusable_label.pack()

            #  Trigger the api request in json_handler.py
            json_handler.get_OC_json(index_value)

            #  Add wait time for the json file to download data from API and get indented
            ui_win.after(5000, process_api_data)

            return

    # Create the reusable storage element
    selection = tk.StringVar()
    selection.set("Select Index")

    # Create a reusable dropdown Menu
    reusable_drop_down = tk.OptionMenu(ui_win, selection, *indices_list)
    reusable_drop_down.config(bg="lightblue")
    reusable_drop_down.pack()

    # Create a reusable load button
    reusable_load_button = tk.Button(ui_win, text="Load", command=fetch_api_data, pady=10)
    reusable_load_button.pack()

    # Create a reusable label
    reusable_label = tk.Label(ui_win, pady=10)
    reusable_label.pack()

    ui_win.mainloop()


if __name__ == "__main__":
    ui_space()
