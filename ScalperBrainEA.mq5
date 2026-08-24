//+------------------------------------------------------------------+
//|                                              ScalperBrainEA.mq5 |
//|                     ELITE QUANTUM AUTONOMOUS TRADING SYSTEM EA   |
//|                                       https://github.com/scalper |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, ELITE QUANTUM AUTONOMOUS TRADING SYSTEM"
#property link      "https://github.com/scalper"
#property version   "7.00"
#property description "Elite Quantum Autonomous Scalper EA v7.00 - Sub-Millisecond Socket IPC & Institutional Interactive HUD Visualizer"
#property indicator_chart_window

#include <Trade\Trade.mqh>

// Input Parameters
input string   InpSocketHost               = "127.0.0.1";           // Socket IPC Bridge Host
input int      InpSocketPort               = 9001;                  // Socket IPC Bridge Port
input bool     InpUseSocketIPC             = true;                  // Use Zero-Latency Socket IPC Push
input string   InpFileName                 = "scalper_telemetry.txt"; // Fallback State File Name
input bool     InpUseCommonFolder          = true;                  // Use Common shared folder (FILE_COMMON)
input int      InpTimerInterval            = 1;                     // Update Interval (seconds)
input bool     InpEmergencyCloseOnLockdown = true;                  // Close positions on Emergency Lockdown signal
input color    InpHudThemePrimary          = clrDodgerBlue;         // Primary HUD Accent Color
input color    InpHudThemeBg               = clrDarkSlateGray;      // Panel Card Background Color

// Extended Symbol Scan Metrics
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

// Detailed Active Position Telemetry
string m_trade_tickets[20];
string m_trade_symbols[20];
string m_trade_dirs[20];
string m_trade_open_prices[20];
string m_trade_sls[20];
string m_trade_tps[20];
string m_trade_pnls[20];
string m_trades_text[20];
int m_total_trades = 0;

// System Account & Risk Metrics
string m_equity = "0.00";
string m_balance = "0.00";
string m_active_count = "0";
string m_active_session = "Quiet Session";
string m_overlaps = "No active overlap";
string m_next_session = "Tokyo";
string m_countdown = "00:00:00";
bool m_show_extended_details = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Interactivity States
bool m_show_extended_details = true;
bool m_show_account_card = true;

// Persistent socket buffer for partial read accumulation
string m_accumulated_buffer = "";

// CTrade object for autonomous panic executions
CTrade m_trade_engine;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//| Initializes timer, chart settings and HUD objects                |
//+------------------------------------------------------------------+
int OnInit()
{
   // Set timer for visual dashboard updates
   EventSetTimer(InpTimerInterval);

   // Enable chart events for interactive HUD controls
   ChartSetInteger(0, CHART_EVENT_OBJECT_CREATE, true);
   ChartSetInteger(0, CHART_EVENT_OBJECT_DELETE, true);

   // Redraw initial institutional layout
   DrawInstitutionalHeader();
   UpdateDashboard();

   Print("ScalperBrainEA v7.00 Master HUD Initialized. IPC Target: ", InpSocketHost, ":", InpSocketPort);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//| Cleans up GUI objects cleanly on EA stop                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteDashboardObjects();
   Print("ScalperBrainEA v7.00 Deinitialized cleanly.");
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
//| OnChartEvent function                                            |
//| Handles interactive HUD button actions (Resync, Panic, Toggle)   |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if(id == CHARTEVENT_OBJECT_CLICK)
   {
      if(sparam == "SB_Btn_Resync")
      {
         Print("ScalperBrainEA: Operator requested manual IPC telemetry resync.");
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Panic")
      {
         Print("ScalperBrainEA: 🚨 EMERGENCY PANIC CLOSE ALL CLICKED BY OPERATOR!");
         ExecutePanicCloseAll();
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Toggle")
      {
         m_show_extended_details = !m_show_extended_details;
         Print("ScalperBrainEA: Extended Neural telemetry details set to: ", m_show_extended_details);
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_CardToggle")
      {
         m_show_account_card = !m_show_account_card;
         Print("ScalperBrainEA: Account summary card set to: ", m_show_account_card);
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_CardToggle")
      {
         m_show_account_card = !m_show_account_card;
         Print("ScalperBrainEA: Account summary card set to: ", m_show_account_card);
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Panic")
      {
         Print("ScalperBrainEA: 🚨 EMERGENCY PANIC CLOSE ALL CLICKED BY OPERATOR!");
         ExecutePanicCloseAll();
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Toggle")
      {
         m_show_extended_details = !m_show_extended_details;
         Print("ScalperBrainEA: Extended Neural telemetry details set to: ", m_show_extended_details);
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_CardToggle")
      {
         m_show_account_card = !m_show_account_card;
         Print("ScalperBrainEA: Account summary card set to: ", m_show_account_card);
         UpdateDashboard();
      }
   }
}

//+------------------------------------------------------------------+
//| ExecutePanicCloseAll                                             |
//| Instantly liquidates all open positions across terminal          |
//+------------------------------------------------------------------+
void ExecutePanicCloseAll()
{
   int closed_count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(m_trade_engine.PositionClose(ticket))
         {
            closed_count++;
         }
      }
   }
   Print("ScalperBrainEA: Emergency Panic Close All finished. Closed positions: ", closed_count);
}

//+------------------------------------------------------------------+
//| ExecutePanicCloseAll                                             |
//| Instantly liquidates all open positions across terminal          |
//+------------------------------------------------------------------+
void ExecutePanicCloseAll()
{
   int closed_count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(m_trade_engine.PositionClose(ticket))
         {
            closed_count++;
         }
      }
   }
   Print("ScalperBrainEA: Emergency Panic Close All finished. Closed positions: ", closed_count);
}

//+------------------------------------------------------------------+
//| ExecutePanicCloseAll                                             |
//| Instantly liquidates all open positions across terminal          |
//+------------------------------------------------------------------+
void ExecutePanicCloseAll()
{
   int closed_count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(m_trade_engine.PositionClose(ticket))
         {
            closed_count++;
         }
      }
   }
   Print("ScalperBrainEA: Emergency Panic Close All finished. Closed positions: ", closed_count);
}

//+------------------------------------------------------------------+
//| FetchSocketData                                                  |
//| Performs a single-shot TCP request to Python SocketIPCBridge     |
//+------------------------------------------------------------------+
string FetchSocketData()
{
   ResetLastError();
   int sock = SocketCreate();
   if(sock == INVALID_HANDLE) return "";

   if(!SocketConnect(sock, InpSocketHost, InpSocketPort, 500))
   {
      SocketClose(sock);
      return "";
   }

   // Poll for readable payload up to 300ms
   uint rsp_len = 0;
   int wait_ms = 0;
   while(wait_ms < 300)
   {
      rsp_len = SocketIsReadable(sock);
      if(rsp_len > 0) break;
      Sleep(10);
      wait_ms += 10;
   }

   string result = "";
   if(rsp_len > 0)
   {
      uchar buf[];
      ArrayResize(buf, (int)rsp_len);
      ArrayInitialize(buf, 0);
      int read_bytes = SocketRead(sock, buf, (int)rsp_len, 500);
      if(read_bytes > 0)
      {
         result = CharArrayToString(buf, 0, read_bytes, CP_UTF8);
      }
   }

   SocketClose(sock);
   return result;
}

//+------------------------------------------------------------------+
//| ParseStateData                                                   |
//| Reads state stream via Socket IPC or fallback shared file        |
//+------------------------------------------------------------------+
bool ParseStateData()
{
   string state_content = "";

   // 1. Try Socket IPC Push Reading
   if(InpUseSocketIPC)
   {
      state_content = FetchSocketData();
   }

   // 2. Fallback to Shared Telemetry File if Socket empty
   if(StringLen(state_content) == 0)
   {
      ResetLastError();
      int flags = FILE_READ|FILE_TXT|FILE_ANSI;
      if(InpUseCommonFolder) flags |= FILE_COMMON;

      int file_handle = FileOpen(InpFileName, flags);
      if(file_handle == INVALID_HANDLE)
      {
         return false;
      }

      while(!FileIsEnding(file_handle))
      {
         state_content += FileReadString(file_handle) + "\n";
      }
      FileClose(file_handle);
   }

   if(StringLen(state_content) < 5) return false;

   // Parse Content Lines
   m_total_symbols = 0;
   m_total_trades = 0;
   bool in_scans_section = false;

   string lines[];
   int line_count = StringSplit(state_content, '\n', lines);

   for(int i = 0; i < line_count; i++)
   {
      string line = lines[i];
      StringTrimRight(line);
      StringTrimLeft(line);
      if(StringLen(line) < 3) continue;

      if(i == 0)
      {
         // Header line: equity|balance|active_count|active_session|overlaps|next_session|countdown
         string parts[];
         int split_count = StringSplit(line, '|', parts);
         if(split_count >= 3)
         {
            m_equity = parts[0];
            m_balance = parts[1];
            m_active_count = parts[2];
            if(split_count >= 4) m_active_session = parts[3];
            if(split_count >= 5) m_overlaps = parts[4];
            if(split_count >= 6) m_next_session = parts[5];
            if(split_count >= 7) m_countdown = parts[6];

            // Emergency Lockdown Circuit Breaker Signal Check
            if(StringFind(line, "LOCKDOWN") >= 0 || StringFind(line, "PANIC") >= 0)
            {
               Print("ScalperBrainEA: EMERGENCY LOCKDOWN / PANIC SIGNAL DETECTED IN TELEMETRY STREAM!");
               if(InpEmergencyCloseOnLockdown)
               {
                  ExecutePanicCloseAll();
               }
            }
         }
         continue;
      }

      if(line == "SCANS_HEADER")
      {
         in_scans_section = true;
         continue;
      }

      string parts[];
      int split_count = StringSplit(line, '|', parts);

      if(!in_scans_section)
      {
         // Trade row: TRADE|ticket|symbol|direction|open_price|sl|tp|profit
         if(split_count >= 8 && parts[0] == "TRADE" && m_total_trades < 20)
         {
            m_trade_tickets[m_total_trades] = parts[1];
            m_trade_symbols[m_total_trades] = parts[2];
            m_trade_dirs[m_total_trades] = parts[3];
            m_trade_open_prices[m_total_trades] = parts[4];
            m_trade_sls[m_total_trades] = parts[5];
            m_trade_tps[m_total_trades] = parts[6];
            m_trade_pnls[m_total_trades] = parts[7];

            m_trades_text[m_total_trades] = parts[2] + " " + parts[3] + " | Ticket: " + parts[1] + " | Open: " + parts[4] + " | SL: " + parts[5] + " | TP: " + parts[6] + " | PnL: $" + parts[7];
            m_total_trades++;
         }
      }
      else
      {
         // Scan row: Symbol|Price|EMA200|Trend|RSI|ATR|Status|avg_w_ih|avg_w_ho|bias_output|hidden_activations
         if(split_count >= 6 && m_total_symbols < 50)
         {
            m_symbols[m_total_symbols] = parts[0];
            m_prices[m_total_symbols] = parts[1];
            m_ema200[m_total_symbols] = parts[2];
            m_trends[m_total_symbols] = parts[3];
            m_rsis[m_total_symbols] = parts[4];
            m_atrs[m_total_symbols] = parts[5];
            m_statuses[m_total_symbols] = parts[6];

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

   m_accumulated_buffer = "";
   return true;
}

//+------------------------------------------------------------------+
//| DrawInstitutionalHeader                                          |
//| Renders re-architected top control toolbar & action buttons      |
//+------------------------------------------------------------------+
void DrawInstitutionalHeader()
{
   CreateLabel("SB_Title", "⚡ ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EAQTS v7.00)", 20, 18, 13, clrLightCyan, "Segoe UI Bold");

   // Interactive Navigation Buttons
   CreateButton("SB_Btn_Resync", "🔄 RESYNC IPC", 580, 14, 100, 24, clrWhite, clrDarkBlue, 8);
   CreateButton("SB_Btn_Toggle", "📊 TOGGLE AI", 690, 14, 90, 24, clrWhite, clrDarkSlateBlue, 8);
   CreateButton("SB_Btn_CardToggle", "💳 ACCOUNT CARD", 790, 14, 110, 24, clrWhite, clrTeal, 8);
   CreateButton("SB_Btn_Panic", "🔒 PANIC CLOSE ALL", 910, 14, 130, 24, clrWhite, clrDarkRed, 8);
}

//+------------------------------------------------------------------+
//| UpdateDashboard                                                  |
//| Re-built HUD matrix visualizer with detailed execution cards     |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   if(!ParseStateData())
   {
      CreateLabel("SB_Status", "Status: STREAMING TELEMETRY VIA ZERO-LATENCY IPC SOCKET...", 20, 48, 10, clrGold, "Segoe UI");
      return;
   }

   // Clean up dynamic rows
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

   // Account Metric Card Calculation
   double float_eq = StringToDouble(m_equity);
   double float_bal = StringToDouble(m_balance);
   double pnl = float_eq - float_bal;
   double drawdown_pct = (float_bal > 0) ? (pnl / float_bal) * 100.0 : 0.0;
   color pnl_color = (pnl >= 0.0) ? clrSpringGreen : clrDeepPink;

   int current_y = 48;

   if(m_show_account_card)
   {
      string metrics_text = "Balance: $" + m_balance + "  |  Equity: $" + m_equity + "  |  Floating PnL: $" + DoubleToString(pnl, 2) + " (" + DoubleToString(drawdown_pct, 2) + "%)  |  Active Session: " + m_active_session;
      CreateLabel("SB_Metrics", metrics_text, 20, current_y, 10, clrWhite, "Segoe UI Semibold");
      current_y += 22;
   }
   else
   {
      ObjectDelete(0, "SB_Metrics");
   }

   // Section 1: Sessions Timeline Window
   string timeline_text = "⏳ SESSION TIMELINE  |  Active Overlaps: " + m_overlaps + "  |  Next Window: " + m_next_session + " in " + m_countdown;
   CreateLabel("SB_Timeline_Lbl", timeline_text, 20, current_y, 9, clrOrange, "Segoe UI Bold");
   current_y += 22;

   // Section 2: Active Trades visualizer card
   CreateLabel("SB_TradeSec", "💼 ACTIVE RUNNING EXECUTIONS (" + m_active_count + "/10 OPEN POSITIONS):", 20, current_y, 10, clrSkyBlue, "Segoe UI Bold");
   current_y += 20;

   int line_height = 18;

   if(m_total_trades == 0)
   {
      CreateLabel("SB_No_Trades", "No active open positions. Neural brain actively scanning multi-asset liquidity pools...", 20, current_y, 9, clrGray, "Segoe UI Italic");
      current_y += line_height;
   }
   else
   {
      for(int i = 0; i < m_total_trades; i++)
      {
         color trade_col = clrLightGray;
         if(StringFind(m_trades_text[i], "BUY") >= 0) trade_col = clrSpringGreen;
         if(StringFind(m_trades_text[i], "SELL") >= 0) trade_col = clrDeepPink;

         CreateLabel("SB_Row_Trade_" + (string)i, "• " + m_trades_text[i], 20, current_y, 9, trade_col, "Segoe UI");
         current_y += line_height;
      }
   }

   // Section 3: Multi-Asset Cognitive Matrix Table
   current_y += 8;
   CreateLabel("SB_ScanSec", "🧠 MULTI-ASSET NEURAL MATRIX & QUANTITATIVE SIGNALS:", 20, current_y, 10, clrSkyBlue, "Segoe UI Bold");
   current_y += 20;

   // Headers
   color head_col = clrDeepSkyBlue;
   CreateLabel("SB_H_Sym", "SYMBOL", 20, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_P", "PRICE", 110, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_EMA", "EMA-200", 200, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_Tr", "TREND", 290, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_RSI", "RSI", 360, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_ATR", "ATR", 420, current_y, 9, head_col, "Segoe UI Bold");

   if(m_show_extended_details)
   {
      CreateLabel("SB_H_AI_W1", "IN-WEIGHTS", 490, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_AI_W2", "OUT-WEIGHTS", 590, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_AI_Act", "NEURAL ACTIVATIONS", 700, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_Stat", "DECISION TELEMETRY", 880, current_y, 9, head_col, "Segoe UI Bold");
   }
   else
   {
      CreateLabel("SB_H_Stat", "DECISION TELEMETRY", 490, current_y, 9, head_col, "Segoe UI Bold");
   }

   current_y += line_height;

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
      if(StringFind(status_val, "BUY") >= 0) status_color = clrSpringGreen;
      else if(StringFind(status_val, "SELL") >= 0) status_color = clrDeepPink;
      else if(StringFind(status_val, "Hold") >= 0) status_color = clrGray;

      color trend_color = (trend_val == "UP") ? clrSpringGreen : clrDeepPink;

      CreateLabel("SB_Row_Sym_" + (string)i, sym_name, 20, current_y, 9, clrYellow, "Segoe UI Semibold");
      CreateLabel("SB_Row_P_" + (string)i, price_val, 110, current_y, 9, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_EMA_" + (string)i, ema_val, 200, current_y, 9, clrLightGray, "Segoe UI");
      CreateLabel("SB_Row_Tr_" + (string)i, trend_val, 290, current_y, 9, trend_color, "Segoe UI Bold");
      CreateLabel("SB_Row_RSI_" + (string)i, rsi_val, 360, current_y, 9, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_ATR_" + (string)i, atr_val, 420, current_y, 9, clrLightGray, "Segoe UI");

      if(m_show_extended_details)
      {
         CreateLabel("SB_Row_AI_W1_" + (string)i, w1_val, 490, current_y, 9, clrOrange, "Courier New");
         CreateLabel("SB_Row_AI_W2_" + (string)i, w2_val, 590, current_y, 9, clrOrange, "Courier New");
         CreateLabel("SB_Row_AI_Act_" + (string)i, "[" + act_val + "]", 700, current_y, 8, clrPeachPuff, "Courier New");
         CreateLabel("SB_Row_Stat_" + (string)i, status_val, 880, current_y, 9, status_color, "Segoe UI");
      }
      else
      {
         CreateLabel("SB_Row_Stat_" + (string)i, status_val, 490, current_y, 9, status_color, "Segoe UI");
      }

      current_y += line_height;
   }

   ChartRedraw();
}

//+------------------------------------------------------------------+
//| CreateLabel                                                      |
//| Helper routine to create or update drawing text labels           |
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
//| CreateButton                                                     |
//| Helper routine to create or update interactive UI buttons        |
//+------------------------------------------------------------------+
void CreateButton(string name, string text, int x, int y, int width, int height, color text_col, color bg_col, int font_size)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   }

   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, width);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, height);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, text_col);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg_col);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, font_size);
   ObjectSetString(0, name, OBJPROP_FONT, "Segoe UI Semibold");
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| DeleteDashboardObjects                                           |
//| Clear all HUD elements cleanly on shutdown                       |
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
   ObjectDelete(0, "SB_Btn_Resync");
   ObjectDelete(0, "SB_Btn_Toggle");
   ObjectDelete(0, "SB_Btn_CardToggle");
   ObjectDelete(0, "SB_Btn_Panic");

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
