//+------------------------------------------------------------------+
//|                                  EqatsAutonomousScalperEA.mq5    |
//|                     ELITE QUANTUM AUTONOMOUS TRADING SYSTEM EA   |
//|                                       https://github.com/scalper |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, ELITE QUANTUM AUTONOMOUS TRADING SYSTEM"
#property link      "https://github.com/scalper"
#property version   "10.00"
#property description "Elite Quantum Autonomous Scalper EA v10.00 - Role-Based Trade Executor Stack with Dual Event Polling & Zero-Latency IPC"
#property indicator_chart_window

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

#import "user32.dll"
   int PostMessageW(long hWnd, uint Msg, uint wParam, uint lParam);
#import

// User Interface & Socket IPC Inputs
input string   InpSocketHost               = "127.0.0.1";           // Socket IPC Bridge Host
input int      InpSocketPort               = 9001;                  // Socket IPC Bridge Port
input bool     InpUseSocketIPC             = true;                  // Use Zero-Latency Socket IPC Push
input string   InpFileName                 = "scalper_telemetry.txt"; // Fallback State File Name
input bool     InpUseCommonFolder          = true;                  // Use Common shared folder (FILE_COMMON)
input int      InpTimerInterval            = 1;                     // Update Interval (seconds)
input bool     InpEmergencyCloseOnLockdown = true;                  // Close positions on Emergency Lockdown signal
input color    InpHudThemePrimary          = clrDodgerBlue;         // Primary HUD Accent Color
input color    InpHudThemeBg               = clrDarkSlateGray;      // Panel Card Background Color

// Local Risk & Margin Safeguards (Adapted from BotCilento EA & AatEAv15)
input group "Local EA Risk & Margin Safeguards"
input bool     InpEnableEmergencyClose      = true;                  // Enable emergency close at max drawdown
input double   InpMaxDrawdownPercent        = 15.0;                  // Max drawdown % before panic close
input double   InpDailyLossLimitPercent     = 5.0;                   // Max daily loss limit %
input double   InpMinFreeMarginBuffer       = 100.0;                 // Minimum free margin buffer ($ USD)
input double   InputMinFreeMarginPct        = 30.0;                  // Minimum free margin percentage (%)
input int      InputMaxAllowedSpread        = 40;                    // Max allowed spread (points)
input int      InpMaxPositionAgeHours       = 72;                    // Max position age (hours, 0=disabled)
input int      InpMaxTradesPerSecond        = 2;                     // Max trades per second rate limit

// Dynamic Execution & AAT Advanced Features (Adapted from AatEAv15)
input group "AAT Execution, BreakEven, Trailing & Pyramiding"
input double   InpRiskPercent              = 1.0;                   // Risk per trade (%)
input int      InpMagicNumber              = 123456;                // Magic Number
input int      InpStopLossPoints           = 200;                   // Initial Stop Loss (points)
input int      InpTakeProfitPoints         = 400;                   // Initial Take Profit (points)
input int      InputBreakEvenTrigger       = 250;                   // BreakEven Trigger (points)
input int      InputBreakEvenBuffer        = 30;                    // BreakEven Buffer (points)
input bool     InpTrailingSL               = true;                  // Enable Trailing Stop Loss
input bool     InpTrailingTP               = true;                  // Enable Trailing Take Profit
input int      InpTrailingStep             = 50;                    // Trailing Step (points)
input bool     InpEnablePyramiding         = true;                  // Enable Pyramid Scaling on Winner
input int      InpMaxPyramidPositions      = 5;                     // Max Pyramid Positions
input int      InputPyramidStepPoints      = 200;                   // Pyramid Min Entry Step (points)
input bool     InpAutoCharts               = false;                 // Auto-open & Tile Multi-TF Charts (M1..MN)

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

// System Account & Risk & Auto-Tune Vitals
string m_equity = "10000.00";
string m_balance = "10000.00";
string m_active_count = "0";
string m_active_session = "Global Interbank";
string m_overlaps = "Asian/European";
string m_next_session = "New York";
string m_countdown = "00:00:00";
string m_hw_tier = "HIGH";
string m_ping_ms = "1.2";

// Local Risk Monitoring & AAT State
datetime m_last_daily_reset_check = 0;
double   m_daily_start_balance    = 0.0;
bool     m_daily_loss_limit_hit   = false;
string   m_candle_countdown       = "00:00";
double   m_current_risk           = InpRiskPercent;

// MQL5 Object instances
CTrade         m_trade_engine;
CPositionInfo  pos_info;
CSymbolInfo    symbol_info;

//+------------------------------------------------------------------+
//| Forward Declarations                                             |
//+------------------------------------------------------------------+
void ExecutePanicCloseAll();
void ApplyTrailingLogic();
void ProcessBreakEvenProtection();
void CheckPyramidScaling();
bool IsPyramidStepValid(ENUM_POSITION_TYPE type, double currentPrice, int stepPoints);
bool IsInitialPositionRiskFree(ENUM_POSITION_TYPE type);
string GatherCloseHistory(ENUM_TIMEFRAMES tf);
void UpdateCandleCountdown();
void SetupTimeframeCharts();
void DrawInstitutionalHeader();
void UpdateDashboard();
void CreatePanelCard(string name, int x, int y, int w, int h, color bg_color, color border_color);
void CreateLabel(string name, string text, int x, int y, int size, color col, string font);
void CreateButton(string name, string text, int x, int y, int width, int height, color text_col, color bg_col, int font_size);
void DeleteDashboardObjects();

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!symbol_info.Name(_Symbol)) return(INIT_FAILED);
   m_trade_engine.SetExpertMagicNumber(InpMagicNumber);
   m_current_risk = InpRiskPercent;

   EventSetTimer(InpTimerInterval);

   ChartSetInteger(0, CHART_EVENT_OBJECT_CREATE, true);
   ChartSetInteger(0, CHART_EVENT_OBJECT_DELETE, true);

   // Apply Pitch Dark Theme & Vibrant Candle Styling to prevent candlestick background clutter
   ChartSetInteger(0, CHART_COLOR_BACKGROUND, C'10,14,23');
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, C'226,232,240');
   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, C'16,185,129');
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, C'239,68,68');
   ChartSetInteger(0, CHART_COLOR_CHART_LINE, C'56,189,248');
   ChartSetInteger(0, CHART_COLOR_CHART_UP, C'16,185,129');
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN, C'239,68,68');
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHIFT, true);
   ChartSetDouble(0, CHART_SHIFT_SIZE, 30.0);

   if(InpAutoCharts) SetupTimeframeCharts();

   DrawInstitutionalHeader();
   UpdateDashboard();

   Print("EqatsAutonomousScalperEA v10.00 Initialized cleanly (Role: TRADE_EXECUTOR). IPC: ", InpSocketHost, ":", InpSocketPort);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteDashboardObjects();
   Print("EqatsAutonomousScalperEA v10.00 Deinitialized cleanly.");
}

//+------------------------------------------------------------------+
//| CheckDailyLossAndRisk                                            |
//+------------------------------------------------------------------+
void CheckDailyLossAndRisk()
{
   datetime now = TimeCurrent();
   if(m_daily_start_balance <= 0.0)
   {
      m_daily_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   }

   MqlDateTime today, lastCheck;
   TimeToStruct(now, today);
   TimeToStruct(m_last_daily_reset_check, lastCheck);

   if(today.day != lastCheck.day)
   {
      m_daily_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
      m_daily_loss_limit_hit = false;
      m_last_daily_reset_check = now;
   }

   double current_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double loss = m_daily_start_balance - current_bal;
   double loss_pct = (m_daily_start_balance > 0.0) ? (loss / m_daily_start_balance) * 100.0 : 0.0;

   if(!m_daily_loss_limit_hit && InpDailyLossLimitPercent > 0.0 && loss_pct >= InpDailyLossLimitPercent)
   {
      m_daily_loss_limit_hit = true;
      Print("EMERGENCY_HALT 🛑 EqatsAutonomousScalperEA: Daily loss limit triggered (", DoubleToString(loss_pct, 2), "% >= ", DoubleToString(InpDailyLossLimitPercent, 2), "%). Executing Panic Close All!");
      ExecutePanicCloseAll();
   }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double dd_pct = (current_bal > 0.0) ? ((current_bal - equity) / current_bal) * 100.0 : 0.0;
   if(InpEnableEmergencyClose && InpMaxDrawdownPercent > 0.0 && dd_pct >= InpMaxDrawdownPercent)
   {
      Print("EMERGENCY_HALT 🛑 EqatsAutonomousScalperEA: Max drawdown percent reached (", DoubleToString(dd_pct, 2), "% >= ", DoubleToString(InpMaxDrawdownPercent, 2), "%). Executing Panic Close All!");
      ExecutePanicCloseAll();
   }

   if(InpMaxPositionAgeHours > 0)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0 && PositionSelectByTicket(ticket))
         {
            datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
            double age_hours = (double)(now - open_time) / 3600.0;
            if(age_hours >= InpMaxPositionAgeHours)
            {
               Print("EqatsAutonomousScalperEA: Closing position #", ticket, " - Max position age reached (", DoubleToString(age_hours, 1), " hours)");
               m_trade_engine.PositionClose(ticket);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!symbol_info.RefreshRates()) return;

   // Check spread & margin safeguards (Adapted from AatEAv15)
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double margin_pct = (balance > 0.0) ? (free_margin / balance) * 100.0 : 0.0;
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);

   if(InputMaxAllowedSpread > 0 && spread > InputMaxAllowedSpread) return;
   if(InputMinFreeMarginPct > 0.0 && margin_pct < InputMinFreeMarginPct)
   {
      Print("MarginEngine CRITICAL RISK: Free Margin limits breached (", DoubleToString(margin_pct, 2), "% < ", DoubleToString(InputMinFreeMarginPct, 2), "%). Execution Blocked.");
      return;
   }

   CheckDailyLossAndRisk();
   ProcessBreakEvenProtection();
   if(InpTrailingSL || InpTrailingTP) ApplyTrailingLogic();
   if(InpEnablePyramiding) CheckPyramidScaling();
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| Timer event function                                             |
//+------------------------------------------------------------------+
void OnTimer()
{
   UpdateCandleCountdown();
   UpdateDashboard();
}

//+------------------------------------------------------------------+
//| UpdateCandleCountdown (Adapted from AAT-Expert-V1.0.0)           |
//+------------------------------------------------------------------+
void UpdateCandleCountdown()
{
   datetime next_bar = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE) + PeriodSeconds(_Period);
   long remaining = next_bar - TimeCurrent();
   if(remaining < 0) remaining = 0;
   m_candle_countdown = StringFormat("%02d:%02d", (int)remaining/60, (int)remaining%60);
}

//+------------------------------------------------------------------+
//| SetupTimeframeCharts (Adapted from AAT-Expert-V1.0.0)            |
//+------------------------------------------------------------------+
void SetupTimeframeCharts()
{
   ENUM_TIMEFRAMES tfs[] = {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4, PERIOD_D1, PERIOD_W1, PERIOD_MN1};
   for(int i=0; i<ArraySize(tfs); i++) ChartOpen(_Symbol, tfs[i]);

   long main_hwnd = ChartGetInteger(0, CHART_WINDOW_HANDLE);
   PostMessageW(main_hwnd, 0x0111, 33054, 0); // 0x0111 = WM_COMMAND, 33054 = ID_WINDOW_TILE_VERT
}

//+------------------------------------------------------------------+
//| ApplyTrailingLogic (Adapted from AAT-Expert-V1.0.0)              |
//+------------------------------------------------------------------+
void ApplyTrailingLogic()
{
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && pos_info.SelectByTicket(ticket))
      {
         if(pos_info.Symbol() == _Symbol && (pos_info.Magic() == InpMagicNumber || InpMagicNumber == 0))
         {
            double current_sl = pos_info.StopLoss();
            double current_tp = pos_info.TakeProfit();
            double new_sl = current_sl;
            double new_tp = current_tp;

            if(pos_info.PositionType() == POSITION_TYPE_BUY)
            {
               double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
               if(InpTrailingSL && InpStopLossPoints > 0)
               {
                  double target_sl = NormalizeDouble(bid - InpStopLossPoints * point, digits);
                  if(target_sl > current_sl + InpTrailingStep * point || current_sl == 0.0) new_sl = target_sl;
               }
               if(InpTrailingTP && InpTakeProfitPoints > 0)
               {
                  double target_tp = NormalizeDouble(bid + InpTakeProfitPoints * point, digits);
                  if(target_tp > current_tp + InpTrailingStep * point || current_tp == 0.0) new_tp = target_tp;
               }
            }
            else if(pos_info.PositionType() == POSITION_TYPE_SELL)
            {
               double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
               if(InpTrailingSL && InpStopLossPoints > 0)
               {
                  double target_sl = NormalizeDouble(ask + InpStopLossPoints * point, digits);
                  if(target_sl < current_sl - InpTrailingStep * point || current_sl == 0.0) new_sl = target_sl;
               }
               if(InpTrailingTP && InpTakeProfitPoints > 0)
               {
                  double target_tp = NormalizeDouble(ask - InpTakeProfitPoints * point, digits);
                  if(target_tp < current_tp - InpTrailingStep * point || current_tp == 0.0) new_tp = target_tp;
               }
            }

            if(new_sl != current_sl || new_tp != current_tp)
            {
               m_trade_engine.PositionModify(ticket, new_sl, new_tp);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| ProcessBreakEvenProtection (Adapted from AatEAv15)                |
//+------------------------------------------------------------------+
void ProcessBreakEvenProtection()
{
   if(InputBreakEvenTrigger <= 0) return;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double beTrigger = InputBreakEvenTrigger * point;
   double beBuffer = InputBreakEvenBuffer * point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && pos_info.SelectByTicket(ticket))
      {
         if(pos_info.Symbol() == _Symbol && (pos_info.Magic() == InpMagicNumber || InpMagicNumber == 0))
         {
            ENUM_POSITION_TYPE type = pos_info.PositionType();
            double openPrice = pos_info.PriceOpen();
            double currentSL = pos_info.StopLoss();
            double currentTP = pos_info.TakeProfit();

            if(type == POSITION_TYPE_BUY)
            {
               double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
               if(currentSL < openPrice && (bid - openPrice > beTrigger))
               {
                  m_trade_engine.PositionModify(ticket, NormalizeDouble(openPrice + beBuffer, digits), currentTP);
               }
            }
            else if(type == POSITION_TYPE_SELL)
            {
               double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
               if((currentSL == 0.0 || currentSL > openPrice) && (openPrice - ask > beTrigger))
               {
                  m_trade_engine.PositionModify(ticket, NormalizeDouble(openPrice - beBuffer, digits), currentTP);
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| IsInitialPositionRiskFree (Adapted from AatEAv13)                |
//+------------------------------------------------------------------+
bool IsInitialPositionRiskFree(ENUM_POSITION_TYPE type)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && pos_info.SelectByTicket(ticket))
      {
         if(pos_info.Symbol() == _Symbol && pos_info.PositionType() == type)
         {
            double openPrice = pos_info.PriceOpen();
            double currentSL = pos_info.StopLoss();

            if(type == POSITION_TYPE_BUY && currentSL < openPrice) return false;
            if(type == POSITION_TYPE_SELL && (currentSL > openPrice || currentSL == 0.0)) return false;
         }
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| GatherCloseHistory (Adapted from AatEAv13)                        |
//+------------------------------------------------------------------+
string GatherCloseHistory(ENUM_TIMEFRAMES tf)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, tf, 0, 15, rates);
   if(copied <= 0) return "0.0";
   string res = "";
   for(int i = copied - 1; i >= 0; i--)
   {
      res = res + StringFormat("%.5f", rates[i].close) + ((i > 0) ? "," : "");
   }
   return res;
}

//+------------------------------------------------------------------+
//| GatherAllTimeframeHistory (Adapted from AatEAv3)                 |
//+------------------------------------------------------------------+
string GatherAllTimeframeHistory()
{
   return StringFormat("M1:[%s]|M5:[%s]|M15:[%s]|M30:[%s]|H1:[%s]|H4:[%s]|D1:[%s]|W1:[%s]|MN:[%s]",
                       GatherCloseHistory(PERIOD_M1),
                       GatherCloseHistory(PERIOD_M5),
                       GatherCloseHistory(PERIOD_M15),
                       GatherCloseHistory(PERIOD_M30),
                       GatherCloseHistory(PERIOD_H1),
                       GatherCloseHistory(PERIOD_H4),
                       GatherCloseHistory(PERIOD_D1),
                       GatherCloseHistory(PERIOD_W1),
                       GatherCloseHistory(PERIOD_MN1));
}

//+------------------------------------------------------------------+
//| IsPyramidStepValid (Adapted from AatEAv15)                        |
//+------------------------------------------------------------------+
bool IsPyramidStepValid(ENUM_POSITION_TYPE type, double currentPrice, int stepPoints)
{
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double minDistance = stepPoints * point;

   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && pos_info.SelectByTicket(ticket))
      {
         if(pos_info.Symbol() == _Symbol && pos_info.PositionType() == type)
         {
            if(MathAbs(currentPrice - pos_info.PriceOpen()) < minDistance) return false;
         }
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| CheckPyramidScaling (Adapted from AatEAv13 & AatEAv15)           |
//+------------------------------------------------------------------+
void CheckPyramidScaling()
{
   int pos_count = 0;
   double last_open = 0.0;
   ENUM_POSITION_TYPE type = POSITION_TYPE_BUY;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && pos_info.SelectByTicket(ticket))
      {
         if(pos_info.Symbol() == _Symbol && (pos_info.Magic() == InpMagicNumber || InpMagicNumber == 0))
         {
            pos_count++;
            if(pos_count == 1)
            {
               last_open = pos_info.PriceOpen();
               type = pos_info.PositionType();
            }
         }
      }
   }

   if(pos_count == 0 || pos_count >= InpMaxPyramidPositions) return;

   // Enforce that base initial position is already risk-free (SL at or above/below entry)
   if(!IsInitialPositionRiskFree(type)) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double price = (type == POSITION_TYPE_BUY) ? ask : bid;

   if(!IsPyramidStepValid(type, price, InputPyramidStepPoints)) return;

   double profit_points = (type == POSITION_TYPE_BUY) ? (bid - last_open) / point : (last_open - ask) / point;

   if(profit_points >= InpStopLossPoints) // Add every 1:1 RR distance
   {
      ENUM_ORDER_TYPE order_type = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double base_scale_lot = 0.01;
      double final_scale_lot = base_scale_lot; // 1.0x standard scale

      if(m_trade_engine.PositionOpen(_Symbol, order_type, final_scale_lot, price, last_open, 0, StringFormat("EQATS Pyramid L%d", pos_count+1)))
      {
         for(int i = PositionsTotal() - 1; i >= 0; i--)
         {
            ulong ticket = PositionGetTicket(i);
            if(ticket > 0 && pos_info.SelectByTicket(ticket))
            {
               if(pos_info.Symbol() == _Symbol && (pos_info.Magic() == InpMagicNumber || InpMagicNumber == 0))
               {
                  m_trade_engine.PositionModify(ticket, last_open, pos_info.TakeProfit());
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| OnChartEvent function                                            |
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
         Print("EqatsAutonomousScalperEA: Operator requested manual IPC telemetry resync.");
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Panic")
      {
         Print("EqatsAutonomousScalperEA: 🚨 EMERGENCY PANIC CLOSE ALL CLICKED BY OPERATOR!");
         ExecutePanicCloseAll();
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_Toggle")
      {
         m_show_extended_details = !m_show_extended_details;
         Print("EqatsAutonomousScalperEA: Extended Neural telemetry details set to: ", m_show_extended_details);
         UpdateDashboard();
      }
      else if(sparam == "SB_Btn_CardToggle")
      {
         m_show_account_card = !m_show_account_card;
         Print("EqatsAutonomousScalperEA: Account summary card set to: ", m_show_account_card);
         UpdateDashboard();
      }
   }
}

//+------------------------------------------------------------------+
//| ExecutePanicCloseAll                                             |
//+------------------------------------------------------------------+
void ExecutePanicCloseAll()
{
   Print("MANUAL OVERRIDE: Panic button pressed. Purging open positions...");
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
   Print("EqatsAutonomousScalperEA: Emergency Panic Close All finished. Closed positions: ", closed_count);
}

//+------------------------------------------------------------------+
//| FetchSocketData                                                  |
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
//+------------------------------------------------------------------+
bool ParseStateData()
{
   string state_content = "";

   if(InpUseSocketIPC)
   {
      state_content = FetchSocketData();
   }

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

            if(StringFind(line, "LOCKDOWN") >= 0 || StringFind(line, "PANIC") >= 0)
            {
               Print("EqatsAutonomousScalperEA: EMERGENCY LOCKDOWN / PANIC SIGNAL DETECTED IN TELEMETRY STREAM!");
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
         if(split_count >= 7 && m_total_symbols < 50)
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

   return true;
}

//+------------------------------------------------------------------+
//| CreatePanelCard                                                  |
//+------------------------------------------------------------------+
void CreatePanelCard(string name, int x, int y, int w, int h, color bg_color, color border_color)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   }

   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg_color);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, border_color);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_BACK, false); // Render in FRONT of candlesticks as solid dark HUD shield
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| DrawInstitutionalHeader                                          |
//+------------------------------------------------------------------+
void DrawInstitutionalHeader()
{
   CreatePanelCard("SB_Card_Header", 10, 10, 1060, 38, C'15,23,42', C'30,58,138');

   CreateLabel("SB_Title", "⚡ ELITE QUANTUM AUTONOMOUS TRADING SYSTEM (EQATS v10.00 | ROLE: EXECUTOR)", 20, 18, 11, clrLightCyan, "Segoe UI Bold");
   CreateLabel("SB_CandleClock", "⏱️ BAR T-: " + m_candle_countdown, 480, 18, 10, clrYellow, "Segoe UI Bold");

   // Precise Non-Overlapping Action Button Offsets (Width=100..130, Spacing=8px)
   CreateButton("SB_Btn_Resync", "🔄 RESYNC IPC", 580, 16, 105, 24, clrWhite, C'37,99,235', 8);
   CreateButton("SB_Btn_Toggle", "📊 TOGGLE AI", 693, 16, 95, 24, clrWhite, C'126,34,206', 8);
   CreateButton("SB_Btn_CardToggle", "💳 ACCOUNT CARD", 796, 16, 115, 24, clrWhite, C'13,148,136', 8);
   CreateButton("SB_Btn_Panic", "🚨 PANIC CLOSE ALL", 919, 16, 140, 24, clrWhite, C'185,28,28', 8);
   ObjectSetInteger(0, "SB_Btn_Panic", OBJPROP_BORDER_COLOR, clrWhite);
}

//+------------------------------------------------------------------+
//| UpdateDashboard                                                  |
//| Re-built HUD matrix visualizer with dynamic non-overlapping Y    |
//+------------------------------------------------------------------+
void UpdateDashboard()
{
   bool has_data = ParseStateData();

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

   if(!has_data)
   {
      CreatePanelCard("SB_Card_Notice", 10, 54, 1060, 40, C'30,41,59', C'217,119,6');
      CreateLabel("SB_Status", "⚠️ TELEMETRY STREAM OFFLINE: Socket IPC Port 9001 Listening... Start main.py to stream telemetry data.", 20, 64, 10, clrGold, "Segoe UI Bold");
      return;
   }
   else
   {
      ObjectDelete(0, "SB_Card_Notice");
      ObjectDelete(0, "SB_Status");
   }

   double float_eq = StringToDouble(m_equity);
   double float_bal = StringToDouble(m_balance);
   double pnl = float_eq - float_bal;
   double drawdown_pct = (float_bal > 0) ? (pnl / float_bal) * 100.0 : 0.0;

   int current_y = 54;

   if(m_show_account_card)
   {
      CreatePanelCard("SB_Card_Account", 10, current_y, 1060, 34, C'15,23,42', C'59,130,246');
      string metrics_text = "Balance: $" + m_balance + "  |  Equity: $" + m_equity + "  |  Floating PnL: $" + DoubleToString(pnl, 2) + " (" + DoubleToString(drawdown_pct, 2) + "%)  |  Session: " + m_active_session + "  |  Tier: " + m_hw_tier + " [Ping: " + m_ping_ms + "ms]";
      CreateLabel("SB_Metrics", metrics_text, 20, current_y + 8, 9, clrWhite, "Segoe UI Semibold");
      current_y += 40;
   }
   else
   {
      ObjectDelete(0, "SB_Card_Account");
      ObjectDelete(0, "SB_Metrics");
   }

   CreatePanelCard("SB_Card_Timeline", 10, current_y, 1060, 30, C'30,41,59', C'217,119,6');
   string timeline_text = "⏳ SESSION TIMELINE  |  Active Overlaps: " + m_overlaps + "  |  Next Window: " + m_next_session + " in " + m_countdown;
   CreateLabel("SB_Timeline_Lbl", timeline_text, 20, current_y + 7, 9, clrOrange, "Segoe UI Bold");
   current_y += 36;

   int trades_height = (m_total_trades == 0) ? 46 : (30 + m_total_trades * 22);
   CreatePanelCard("SB_Card_Trades", 10, current_y, 1060, trades_height, C'15,23,42', C'14,165,233');

   CreateLabel("SB_TradeSec", "💼 ACTIVE RUNNING EXECUTIONS (" + m_active_count + " POSITIONS OPEN):", 20, current_y + 7, 10, clrSkyBlue, "Segoe UI Bold");
   current_y += 28;

   int line_height = 22;

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

   current_y += 12;
   int scan_rows = (m_total_symbols > 15) ? 15 : m_total_symbols;
   int scans_height = 30 + (scan_rows + 1) * 22;
   CreatePanelCard("SB_Card_Scans", 10, current_y, 1060, scans_height, C'15,23,42', C'99,102,241');

   CreateLabel("SB_ScanSec", "🧠 MULTI-ASSET NEURAL MATRIX & QUANTITATIVE SIGNALS (" + (string)m_total_symbols + " ASSETS SCANNED):", 20, current_y + 7, 10, clrSkyBlue, "Segoe UI Bold");
   current_y += 28;

   color head_col = clrDeepSkyBlue;

   // Precise Non-Overlapping X Column Offsets
   int col_x_sym   = 20;
   int col_x_price = 115;
   int col_x_ema   = 205;
   int col_x_trend = 295;
   int col_x_rsi   = 365;
   int col_x_atr   = 425;
   int col_x_w1    = 495;
   int col_x_w2    = 595;
   int col_x_act   = 705;
   int col_x_stat  = 885;

   CreateLabel("SB_H_Sym", "SYMBOL", col_x_sym, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_P", "PRICE", col_x_price, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_EMA", "EMA-200", col_x_ema, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_Tr", "TREND", col_x_trend, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_RSI", "RSI", col_x_rsi, current_y, 9, head_col, "Segoe UI Bold");
   CreateLabel("SB_H_ATR", "ATR", col_x_atr, current_y, 9, head_col, "Segoe UI Bold");

   if(m_show_extended_details)
   {
      CreateLabel("SB_H_AI_W1", "IN-WEIGHTS", col_x_w1, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_AI_W2", "OUT-WEIGHTS", col_x_w2, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_AI_Act", "NEURAL ACTIVATIONS", col_x_act, current_y, 9, clrOrange, "Segoe UI Bold");
      CreateLabel("SB_H_Stat", "DECISION TELEMETRY", col_x_stat, current_y, 9, head_col, "Segoe UI Bold");
   }
   else
   {
      CreateLabel("SB_H_Stat", "DECISION TELEMETRY", col_x_w1, current_y, 9, head_col, "Segoe UI Bold");
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

      CreateLabel("SB_Row_Sym_" + (string)i, sym_name, col_x_sym, current_y, 9, clrYellow, "Segoe UI Semibold");
      CreateLabel("SB_Row_P_" + (string)i, price_val, col_x_price, current_y, 9, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_EMA_" + (string)i, ema_val, col_x_ema, current_y, 9, clrLightGray, "Segoe UI");
      CreateLabel("SB_Row_Tr_" + (string)i, trend_val, col_x_trend, current_y, 9, trend_color, "Segoe UI Bold");
      CreateLabel("SB_Row_RSI_" + (string)i, rsi_val, col_x_rsi, current_y, 9, clrWhite, "Segoe UI");
      CreateLabel("SB_Row_ATR_" + (string)i, atr_val, col_x_atr, current_y, 9, clrLightGray, "Segoe UI");

      if(m_show_extended_details)
      {
         CreateLabel("SB_Row_AI_W1_" + (string)i, w1_val, col_x_w1, current_y, 9, clrOrange, "Courier New");
         CreateLabel("SB_Row_AI_W2_" + (string)i, w2_val, col_x_w2, current_y, 9, clrOrange, "Courier New");
         CreateLabel("SB_Row_AI_Act_" + (string)i, "[" + act_val + "]", col_x_act, current_y, 8, clrPeachPuff, "Courier New");
         CreateLabel("SB_Row_Stat_" + (string)i, status_val, col_x_stat, current_y, 9, status_color, "Segoe UI");
      }
      else
      {
         CreateLabel("SB_Row_Stat_" + (string)i, status_val, col_x_w1, current_y, 9, status_color, "Segoe UI");
      }

      current_y += line_height;
   }

   ChartRedraw();
}

//+------------------------------------------------------------------+
//| CreateLabel                                                      |
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
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTED, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
//| CreateButton                                                     |
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
//+------------------------------------------------------------------+
void DeleteDashboardObjects()
{
   ObjectDelete(0, "SB_Card_Header");
   ObjectDelete(0, "SB_Title");
   ObjectDelete(0, "SB_CandleClock");
   ObjectDelete(0, "SB_Card_Notice");
   ObjectDelete(0, "SB_Status");
   ObjectDelete(0, "SB_Card_Account");
   ObjectDelete(0, "SB_Metrics");
   ObjectDelete(0, "SB_Card_Timeline");
   ObjectDelete(0, "SB_Timeline_Lbl");
   ObjectDelete(0, "SB_Card_Trades");
   ObjectDelete(0, "SB_TradeSec");
   ObjectDelete(0, "SB_No_Trades");
   ObjectDelete(0, "SB_Card_Scans");
   ObjectDelete(0, "SB_ScanSec");
   ObjectDelete(0, "SB_H_Sym");
   ObjectDelete(0, "SB_H_P");
   ObjectDelete(0, "SB_H_EMA");
   ObjectDelete(0, "SB_H_Tr");
   ObjectDelete(0, "SB_H_RSI");
   ObjectDelete(0, "SB_H_ATR");
   ObjectDelete(0, "SB_H_Stat");
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
