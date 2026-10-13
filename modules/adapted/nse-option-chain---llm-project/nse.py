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


import code_snippts
import data
import GEN_AI
import pandas as pd
import streamlit as st


def main():

    left_column, space, right_column, social = st.columns([2, 1, 2, 3])

    # Apply the table CSS
    st.markdown(code_snippts.table_css, unsafe_allow_html=True)

    # Generate the HTML table for the complete data
    html_table = code_snippts.html_table

    with left_column:
        with left_column:
            # Ensure the user is logged in
            if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
                st.error("You need to be logged in to access this page.")

            # Logout button
            if st.button("Logout"):
                st.session_state["logged_in"] = False
                st.session_state["username"] = None
                st.session_state["page"] = "login"  # Set page to 'login' to redirect
                st.session_state.modified = True
                st.rerun()  # Redirect to login pa
        contract = st.selectbox(
            options={"NIFTY": "NIFTY", "BANKNIFTY": "Banknifty"},
            label="Select Option Contract",
            index=0,
        )

    if contract:
        response = data.data_extractor(contract)
        df = response.get("df", pd.DataFrame())
        underlying = response.get("underlying_price", "N/A")
        atm_strike = data.calculate_atm_price(contract, underlying)

        if not df.empty:
            for i in range(len(df)):
                if df.iloc[i]["Strike Price"] == atm_strike:
                    row_style = "background-color: white ; color:black; "
                else:
                    row_style = ""

                html_table += f"<tr style='{row_style}'>"
                for col in df.columns:
                    html_table += f"<td>{df.iloc[i][col]}</td>"
                html_table += "</tr>"

            html_table += "</tbody></table>"

            atm_index = df[df["Strike Price"] == int(atm_strike)].index[0]
            max_rows = min(atm_index, len(df) - atm_index - 1)
            options = [f"{i + 1} row(s) above and below ATM strike" for i in range(max_rows)]

            row_selection = st.selectbox(
                "To Calculate The PCR You Can Select The Number's Of Row From ATM Strike",
                options=options,
            )

            num_rows = int(row_selection.split()[0])
            start_index = max(atm_index - num_rows, 0)
            end_index = min(atm_index + num_rows + 1, len(df))

            st.write("Selected rows data:")
            selected_rows = df.iloc[start_index:end_index]
            st.write(selected_rows)

        else:
            st.write("No data available")

    chat_input = st.text_input(
        label="Ask Your Question Related To Trading ?",
        placeholder="My PCR is 1 then what should i do ?",
    )
    if chat_input:
        response = GEN_AI.gen_ai(chat_input)
        st.write(response)
    with right_column:
        st.write("Underlying Price: ", underlying)
        st.write("ATM Strike Price: ", atm_strike)
        st.write("PCR (Put/Call): ", data.calculate_pcr(selected_rows))
        st.write()

    # Display the full HTML table in Streamlit
    st.markdown(html_table, unsafe_allow_html=True)

    with social:
        st.write("Connact With Me")
        st.markdown(code_snippts.social, unsafe_allow_html=True)

    st.write()
    st.write()
    st.markdown(code_snippts.social, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
