//+------------------------------------------------------------------+
//|                                              ScalperBrainEA.mq5 |
//|                                  Copyright 2026, Scalper Brain   |
//|                                       https://github.com/scalper |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Scalper Brain"
#property link      "https://github.com/scalper"
#property version   "2.00"
#property description "Autonomous Scalper Brain - On-Chart Interactive HUD Dashboard"
#property indicator_chart_window

// Input Parameters
input string   InpFileName = "scalper_state.txt"; // State File Name
input int      InpTimerInterval = 1;              // Update Interval (seconds)

// State variables
string m_symbols[50];
string m_prices[50];
string m_ema200[50];
string m_trends[50];
string m_rsis[50];
string m_atrs[50];
string m_statuses[50];
string m_avg_w_ih[50];
string m_avg_w_ho[50];
string m_bias_out[50];
string m_hidden_act[50];
int m_total_symbols = 0;

string m_trades_text[20];
int m_total_trades = 0;

string m_equity = "0.00";
string m_balance = "0.00";
string m_active_count = "0";
string m_active_session = "Quiet Session";
string m_overlaps = "No active overlap";
string m_next_session = "Tokyo";
string m_countdown = "00:00:00";

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

   // Line 1: Header (equity|balance|active_count|active_session|overlaps|next_session|countdown)
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
         if(split_count >= 4) m_active_session = parts[3];
         if(split_count >= 5) m_overlaps = parts[4];
         if(split_count >= 6) m_next_session = parts[5];
         if(split_count >= 7) m_countdown = parts[6];
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

            m_trades_text[m_total_trades] = symbol + " " + dir + " | Ticket: " + ticket + " | Entry: " + open_p + " | PnL: " + profit + " USD";
            m_total_trades++;
         }
      }
      else
      {
         // This is a scan row: Symbol|Price|EMA200|Trend|RSI|ATR|Status|avg_w_ih|avg_w_ho|bias_output|hidden_activations
         if(split_count >= 6 && m_total_symbols < 50)
         {
            m_symbols[m_total_symbols] = parts[0];
            m_prices[m_total_symbols] = parts[1];
            m_ema200[m_total_symbols] = parts[2];
            m_trends[m_total_symbols] = parts[3];
            m_rsis[m_total_symbols] = parts[4];
            m_atrs[m_total_symbols] = parts[5];
            m_statuses[m_total_symbols] = parts[6];

            // AI internals columns
            if(split_count >= 11)
            {
               m_avg_w_ih[m_total_symbols] = parts[7];
               m_avg_w_ho[m_total_symbols] = parts[8];
               m_bias_out[m_total_symbols] = parts[9];
               m_hidden_act[m_total_symbols] = parts[10];
            }
            else
            {
               m_avg_w_ih[m_total_symbols] = "0.0";
               m_avg_w_ho[m_total_symbols] = "0.0";
               m_bias_out[m_total_symbols] = "0.0";
               m_hidden_act[m_total_symbols] = "0,0,0,0,0";
            }

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
      ObjectDelete(0, "SB_Row_P_" + (string)i);
      ObjectDelete(0, "SB_Row_EMA_" + (string)i);
      ObjectDelete(0, "SB_Row_Tr_" + (string)i);
      ObjectDelete(0, "SB_Row_RSI_" + (string)i);
      ObjectDelete(0, "SB_Row_ATR_" + (string)i);
      ObjectDelete(0, "SB_Row_Stat_" + (string)i);
      ObjectDelete(0, "SB_Row_Trade_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_W1_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_W2_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_Act_" + (string)i);
   }
   ObjectDelete(0, "SB_No_Trades");
   ObjectDelete(0, "SB_H_Sym");
   ObjectDelete(0, "SB_H_P");
   ObjectDelete(0, "SB_H_EMA");
   ObjectDelete(0, "SB_H_Tr");
   ObjectDelete(0, "SB_H_RSI");
   ObjectDelete(0, "SB_H_ATR");
   ObjectDelete(0, "SB_H_Stat");
   ObjectDelete(0, "SB_Timeline_Lbl");
   ObjectDelete(0, "SB_H_AI_W1");
   ObjectDelete(0, "SB_H_AI_W2");
   ObjectDelete(0, "SB_H_AI_Act");

   // Update system metrics labels
   string metrics_text = "Balance: " + m_balance + " USD  |  Equity: " + m_equity + " USD  |  Session: " + m_active_session;
   CreateLabel("SB_Metrics", metrics_text, 20, 50, 11, clrWhite, "Segoe UI Semibold");

   // Section 1: Sessions Timeline Countdown HUD
   string timeline_text = "⏳ SESSIONS TIMELINE  |  Active Overlaps: " + m_overlaps + "  |  Next Session: " + m_next_session + " starts in " + m_countdown;
   CreateLabel("SB_Timeline_Lbl", timeline_text, 20, 75, 10, clrOrange, "Segoe UI Bold");

   // Section 2: Active Running Trades
   CreateLabel("SB_TradeSec", "💼 ACTIVE RUNNING TRADES (" + m_active_count + "/3):", 20, 100, 11, clrSkyBlue, "Segoe UI Bold");

   int current_y = 125;
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

   // Section 3: Scans Matrix Table
   current_y += 10;
   CreateLabel("SB_ScanSec", "🧠 MULTI-ASSET COGNITIVE SCANS & AI NEURONS ACTIVATION MATRIX:", 20, current_y, 11, clrSkyBlue, "Segoe UI Bold");
   current_y += 22;

   // Table Column Headers
   color head_col = clrSkyBlue;
   CreateLabel("SB_H_Sym", "SYMBOL", 20, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_P", "PRICE", 100, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_EMA", "EMA-200", 180, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_Tr", "TREND", 260, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_RSI", "RSI", 320, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_ATR", "ATR", 370, current_y, 9, head_col, "Segoe UI Bold");

   // AI columns headers
   CreateLabel("SB_H_AI_W1", "IN-WEIGHTS", 420, current_y, 9, clrOrange, "Segoe UI Bold");
   CreateLabel("SB_H_AI_W2", "OUT-WEIGHTS", 500, current_y, 9, clrOrange, "Segoe UI Bold");
   CreateLabel("SB_H_AI_Act", "NEURONS ACTIVATIONS", 585, current_y, 9, clrOrange, "Segoe UI Bold");

   CreateLabel("SB_H_Stat", "STATUS DETAILS", 735, current_y, 9, head_col, "Segoe UI Bold");
   current_y += spacing;

   for(int i = 0; i < m_total_symbols && i < 15; i++)
   {
      string sym_name = m_symbols[i];
      string price_val = m_prices[i];
      string ema_val = m_ema200[i];
      string trend_val = m_trends[i];
      string rsi_val = m_rsis[i];
      string atr_val = m_atrs[i];
      string status_val = m_statuses[i];

      string w1_val = m_avg_w_ih[i];
      string w2_val = m_avg_w_ho[i];
      string act_val = m_hidden_act[i];

      color status_color = clrLightGray;
      if(StringFind(status_val, "Executing BUY") >= 0 || StringFind(status_val, "Consensus BUY") >= 0)
         status_color = clrGreen;
      else if(StringFind(status_val, "Executing SELL") >= 0 || StringFind(status_val, "Consensus SELL") >= 0)
         status_color = clrRed;
      else if(StringFind(status_val, "Hold") >= 0)
         status_color = clrGray;

      color trend_color = (trend_val == "UP") ? clrGreen : clrRed;

      CreateLabel("SB_Row_Sym_" + (string)i, sym_name, 20, current_y, 10, clrYellow, "Segoe UI Semibold");
      CreateLabel("SB_Row_P_" + (string)i, price_val, 100, current_y, 10, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_EMA_" + (string)i, ema_val, 180, current_y, 10, clrLightGray, "Segoe UI");
      CreateLabel("SB_Row_Tr_" + (string)i, trend_val, 260, current_y, 10, trend_color, "Segoe UI Bold");
      CreateLabel("SB_Row_RSI_" + (string)i, rsi_val, 320, current_y, 10, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_ATR_" + (string)i, atr_val, 370, current_y, 10, clrLightGray, "Segoe UI");

      // Draw AI stats rows
      CreateLabel("SB_Row_AI_W1_" + (string)i, w1_val, 420, current_y, 10, clrOrange, "Courier New Semibold");
      CreateLabel("SB_Row_AI_W2_" + (string)i, w2_val, 500, current_y, 10, clrOrange, "Courier New Semibold");
      CreateLabel("SB_Row_AI_Act_" + (string)i, "[" + act_val + "]", 585, current_y, 9, clrPeachPuff, "Courier New");

      CreateLabel("SB_Row_Stat_" + (string)i, status_val, 735, current_y, 10, status_color, "Segoe UI");

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
   ObjectDelete(0, "SB_H_Sym");
   ObjectDelete(0, "SB_H_P");
   ObjectDelete(0, "SB_H_EMA");
   ObjectDelete(0, "SB_H_Tr");
   ObjectDelete(0, "SB_H_RSI");
   ObjectDelete(0, "SB_H_ATR");
   ObjectDelete(0, "SB_H_Stat");
   ObjectDelete(0, "SB_Timeline_Lbl");
   ObjectDelete(0, "SB_H_AI_W1");
   ObjectDelete(0, "SB_H_AI_W2");
   ObjectDelete(0, "SB_H_AI_Act");

   for(int i = 0; i < 50; i++)
   {
      ObjectDelete(0, "SB_Row_Sym_" + (string)i);
      ObjectDelete(0, "SB_Row_P_" + (string)i);
      ObjectDelete(0, "SB_Row_EMA_" + (string)i);
      ObjectDelete(0, "SB_Row_Tr_" + (string)i);
      ObjectDelete(0, "SB_Row_RSI_" + (string)i);
      ObjectDelete(0, "SB_Row_ATR_" + (string)i);
      ObjectDelete(0, "SB_Row_Stat_" + (string)i);
      ObjectDelete(0, "SB_Row_Trade_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_W1_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_W2_" + (string)i);
      ObjectDelete(0, "SB_Row_AI_Act_" + (string)i);
   }

   ChartRedraw();
}
