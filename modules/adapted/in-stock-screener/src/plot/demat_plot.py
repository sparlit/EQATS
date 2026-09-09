
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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


#!/usr/bin/python

import plotly
import plotly.offline as offline
import plotly.plotly as py
import plotly.graph_objs as go
import plotly.figure_factory as FF
import plotly.io as pio

import numpy as np
import pandas as pd

import os

import sys
import re
import csv
import traceback

# input file name

mode   = sys.argv[1]
in_file = sys.argv[2]

if mode == 'offline':
	out_file = sys.argv[3]

plotly_api_key = os.environ.get('PLOTLY_API_KEY').rstrip()

df = pd.read_csv(in_file)

print df

print list(df)

# strip whitespace in columns
df.columns = df.columns.str.strip()

print list(df)

df_external_source = FF.create_table(df.head())

plotly.tools.set_credentials_file(username='surinder432', api_key=plotly_api_key)

# offline.iplot(df_external_source, filename='df-portfolio-bar')
# py.iplot(df_external_source, filename='df-portfolio-bar')

# trace = go.Scatter(x = df['YEAR'], y = df['Portfolio'],
#                   name='Portfolio in Rs ')


trace1 = go.Bar(x = df['YEAR'], y = df['Buy'], name='Buy' )
trace2 = go.Bar(x = df['YEAR'], y = df['Sale'], name='Sale')
trace3 = go.Bar(x = df['YEAR'], y = df['Portfolio'], name='Portfolio')


# layout = go.Layout(title='Portfolio',
#                   plot_bgcolor='rgb(230, 230,230)', 
#                   showlegend=True)

layout = go.Layout(
  barmode='group'
)

# fig = go.Figure(data=[trace], layout=layout)

fig = go.Figure(data=[trace1, trace2, trace3], layout=layout)

if mode == 'offline' :
	offline.iplot(fig, filename='portfolio-bar')
	pio.write_image(fig, out_file)
else:
	py.iplot(fig, filename='portfolio-bar')