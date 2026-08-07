//+------------------------------------------------------------------+
//|                                              ScalperBrainEA.mq5 |
//|                                  Copyright 2026, Scalper Brain   |
//|                                       https://github.com/scalper |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Scalper Brain"
#property link      "https://github.com/scalper"
#property version   "1.20"
#property description "Autonomous Scalper Brain - On-Chart Interactive HUD Dashboard"
#property indicator_chart_window

// Input Parameters
input string   InpFileName = "scalper_state.txt"; // State File Name
input int      InpTimerInterval = 1;              // Update Interval (seconds)

// State variables
string m_symbols[50];
string m_statuses[50];
string m_prices[50];
int m_total_symbols = 0;

string m_trades_text[20];
int m_total_trades = 0;

string m_equity = "0.00";
string m_balance = "0.00";
string m_active_count = "0";
string m_active_session = "Quiet Session";

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//| Initializes timer and UI objects                                 |
//+------------------------------------------------------------------+
int OnInit()
{
   // Set timer for visual dashboard updates
   EventSetTimer(InpTimerInterval);

   // Redraw initial layout
   DrawHeader();
   UpdateDashboard();

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//| Deletes GUI objects cleanly on EA stop                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteDashboardObjects();
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//| Fires updates on new price ticks                                 |
//+------------------------------------------------------------------+
void OnTick()
{
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| Timer event function                                             |
//| Fires updates on set time interval                               |
//+------------------------------------------------------------------+
void OnTimer()
{
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| ParseStateFile                                                   |
//| Safely opens and parses the state file from FILE_COMMON          |
//+------------------------------------------------------------------+
bool ParseStateFile()
{
   ResetLastError();
   // Open the state file sharing the Python live data using FILE_COMMON flag
   int file_handle = FileOpen(InpFileName, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(file_handle == INVALID_HANDLE)
   {
      return false;
   }

   m_total_symbols = 0;
   m_total_trades = 0;
   bool in_scans_section = false;

   // Line 1: Header (equity|balance|active_count|active_session)
   if(!FileIsEnding(file_handle))
   {
      string header_line = FileReadString(file_handle);
      string parts[];
      int split_count = StringSplit(header_line, '|', parts);
      if(split_count >= 3)
      {
         m_equity = parts[0];
         m_balance = parts[1];
         m_active_count = parts[2];
         if(split_count >= 4)
         {
            m_active_session = parts[3];
         }
      }
   }

   // Parse subsequent rows
   while(!FileIsEnding(file_handle))
   {
      string line = FileReadString(file_handle);
      if(StringLen(line) < 3) continue;

      if(line == "SCANS_HEADER")
      {
         in_scans_section = true;
         continue;
      }

      string parts[];
      int split_count = StringSplit(line, '|', parts);

      if(!in_scans_section)
      {
         // This is a trade row: TRADE|ticket|symbol|direction|open_price|sl|tp|profit
         if(split_count >= 8 && parts[0] == "TRADE" && m_total_trades < 20)
         {
            string ticket = parts[1];
            string symbol = parts[2];
            string dir = parts[3];
            string open_p = parts[4];
            string profit = parts[7];

            m_trades_text[m_total_trades] = symbol + " " + dir + " | Ticket: " + ticket + " | Entry: " + open_p + " | Floating PnL: " + profit + " USD";
            m_total_trades++;
         }
      }
      else
      {
         // This is a scan row: Symbol|Price|EMA200|Trend|RSI|ATR|Status
         if(split_count >= 6 && m_total_symbols < 50)
         {
            m_symbols[m_total_symbols] = parts[0];
            m_prices[m_total_symbols] = parts[1];

            string trend = parts[3];
            string rsi = parts[4];
            string status = parts[6];
            m_statuses[m_total_symbols] = "[" + trend + " | RSI: " + rsi + "] " + status;

            m_total_symbols++;
         }
      }
   }

   FileClose(file_handle);
   return true;
}

//+------------------------------------------------------------------+
//| DrawHeader                                                       |
//| Renders static GUI panels                                        |
//+------------------------------------------------------------------+
void DrawHeader()
{
   // Title label object
   CreateLabel("SB_Title", "🤖 SCALPER BRAIN AUTONOMOUS SYSTEM", 20, 20, 14, clrSkyBlue, "Segoe UI Bold");
}

//+------------------------------------------------------------------+
//| UpdateDashboard                                                  |
//| Core engine that updates graphical labels                        |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   if(!ParseStateFile())
   {
      CreateLabel("SB_Status", "Status: WAITING FOR PYTHON BRAIN...", 20, 50, 10, clrYellow, "Segoe UI");
      return;
   }

   // Clean up any previously drawn rows
   for(int i = 0; i < 40; i++)
   {
      ObjectDelete(0, "SB_Row_Sym_" + (string)i);
      ObjectDelete(0, "SB_Row_Stat_" + (string)i);
      ObjectDelete(0, "SB_Row_Trade_" + (string)i);
   }
   ObjectDelete(0, "SB_No_Trades");

   // Update system metrics labels
   string metrics_text = "Balance: " + m_balance + " USD  |  Equity: " + m_equity + " USD  |  Session: " + m_active_session;
   CreateLabel("SB_Metrics", metrics_text, 20, 50, 11, clrWhite, "Segoe UI Semibold");

   // Section 1: Active Running Trades
   CreateLabel("SB_TradeSec", "💼 ACTIVE RUNNING TRADES (" + m_active_count + "/3):", 20, 80, 11, clrSkyBlue, "Segoe UI Bold");

   int current_y = 105;
   int spacing = 20;

   if(m_total_trades == 0)
   {
      CreateLabel("SB_No_Trades", "No active open positions. Brain is monitoring.", 20, current_y, 10, clrGray, "Segoe UI Italic");
      current_y += spacing;
   }
   else
   {
      for(int i = 0; i < m_total_trades; i++)
      {
         color trade_col = clrLightGray;
         if(StringFind(m_trades_text[i], "BUY") >= 0) trade_col = clrGreen;
         if(StringFind(m_trades_text[i], "SELL") >= 0) trade_col = clrRed;

         CreateLabel("SB_Row_Trade_" + (string)i, "• " + m_trades_text[i], 20, current_y, 10, trade_col, "Segoe UI");
         current_y += spacing;
      }
   }

   // Section 2: Scans Matrix
   current_y += 10;
   CreateLabel("SB_ScanSec", "🔍 MULTI-ASSET COGNITIVE SCANS MATRIX:", 20, current_y, 11, clrSkyBlue, "Segoe UI Bold");
   current_y += 25;

   for(int i = 0; i < m_total_symbols && i < 15; i++)
   {
      string sym_name = m_symbols[i];
      string price_val = m_prices[i];
      string status_val = m_statuses[i];

      color status_color = clrLightGray;
      if(StringFind(status_val, "Executing BUY") >= 0 || StringFind(status_val, "ACTIVE (BUY") >= 0)
         status_color = clrGreen;
      else if(StringFind(status_val, "Executing SELL") >= 0 || StringFind(status_val, "ACTIVE (SELL") >= 0)
         status_color = clrRed;
      else if(StringFind(status_val, "HOLD") >= 0)
         status_color = clrGray;

      CreateLabel("SB_Row_Sym_" + (string)i, sym_name + " (" + price_val + "):", 20, current_y, 10, clrYellow, "Segoe UI Semibold");
      CreateLabel("SB_Row_Stat_" + (string)i, status_val, 180, current_y, 10, status_color, "Segoe UI");
      current_y += spacing;
   }

   ChartRedraw();
}

//+------------------------------------------------------------------+
//| CreateLabel                                                      |
//| Helper routine to create or update drawing labels                |
//+------------------------------------------------------------------+
void CreateLabel(string name, string text, int x, int y, int size, color col, string font)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   }

   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
//| DeleteDashboardObjects                                           |
//| Clear all objects on shutdown                                    |
//+------------------------------------------------------------------+
void DeleteDashboardObjects()
{
   ObjectDelete(0, "SB_Title");
   ObjectDelete(0, "SB_Status");
   ObjectDelete(0, "SB_Metrics");
   ObjectDelete(0, "SB_TradeSec");
   ObjectDelete(0, "SB_No_Trades");
   ObjectDelete(0, "SB_ScanSec");

   for(int i = 0; i < 50; i++)
   {
      ObjectDelete(0, "SB_Row_Sym_" + (string)i);
      ObjectDelete(0, "SB_Row_Stat_" + (string)i);
      ObjectDelete(0, "SB_Row_Trade_" + (string)i);
   }

   ChartRedraw();
}
