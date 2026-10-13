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


import os

import yaml
from finrobot.agents.financial_agent import FinancialAgent


class IndianEarningsAnalyzerPipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        """
        Initializes the FinRobot and Fincept-inspired text analytics engine.
        """
        self.api_key = self._load_api_key(config_path)
        # Set environment variable required by the underlying FinRobot LLM connectors
        os.environ["OPENAI_API_KEY"] = self.api_key

    def _load_api_key(self, path: str) -> str:
        try:
            with open(path, "file") as f:
                config = yaml.safe_load(f)
                return config.get("OPENAI_API_KEY", "")
        except Exception:
            # Fallback check if user prefers system environment variables directly
            return os.getenv("OPENAI_API_KEY", "MOCK_KEY_FOR_TESTING")

    def get_transcript_payload(self, ticker: str) -> str:
        """
        Fetches or simulates an Indian corporate earnings call transcript.
        Includes typical regional nuances like SEBI compliance references, CapEx in Crores, etc.
        """
        # In production, this pulls from local data/raw/ transcripts or BSE/NSE scrapers.
        print(f"[1/3] Loading transcript text payload for {ticker}...")

        mock_transcript = f"""
        {ticker} Q3 FY26 Earnings Conference Call Transcript
        Management Speakers: Managing Director & Chief Financial Officer.

        Executive Opening Remarks:
        We are pleased to report a steady quarter with revenue growth of 12% Year-on-Year.
        Our domestic enterprise business scaled efficiently, though global headwinds continue
        to pressure our margins in the legacy segment by 80 basis points.

        Crucially, our board has greenlit an additional Capital Expenditure (CapEx) of ₹4,500 Crores
        for infrastructure expansion across South India and upcoming 6G pilot frameworks.

        Analyst Q&A Session:
        Analyst (Kotak Institutional Equities): Can you give color on rural consumption recovery?
        CFO: Rural demand is showing green shoots, but full recovery is delayed by a quarter.
        We expect localized margin pressure to persist through Q4 before normalization in FY27.
        """
        return mock_transcript

    def analyze_transcript(self, ticker: str):
        """
        Deploys multi-agent consensus workflows inspired by Fincept and FinRobot templates.
        """
        transcript_text = self.get_transcript_payload(ticker)

        print("[2/3] Orchestrating FinRobot AI Agents for transcript decoding...")

        # Checking for API key configuration to avoid abrupt runtime termination
        if self.api_key == "MOCK_KEY_FOR_TESTING" or not self.api_key:
            print(
                "\n⚠️  [System Warning]: Real OpenAI API Key not detected in config/settings.yaml."
            )
            print("Executing deterministic programmatic semantic breakdown instead...\n")
            self._execute_deterministic_fallback(ticker, transcript_text)
            return

        # Define specialized financial personas
        forecasting_agent = FinancialAgent(
            name="Forward Guidance Analyst",
            system_instruction="You are an expert Indian equity research analyst. Extract exact forward-looking statements, growth guidance, or warnings mentioned by management.",
        )

        capex_agent = FinancialAgent(
            name="CapEx & Allocation Auditor",
            system_instruction="You are a corporate forensic accountant. Track balance sheet commitments, allocation numbers in Crores, and capital expenditure targets.",
        )

        # Trigger parallel inference tasks
        print(f"-> Agent 1 ({forecasting_agent.name}) processing trends...")
        guidance_report = forecasting_agent.chat(
            f"Analyze this transcript and summarize outlook/guidance: {transcript_text}"
        )

        print(f"-> Agent 2 ({capex_agent.name}) calculating allocations...")
        capex_report = capex_agent.chat(
            f"Identify capital allocation and infrastructure deployment data points: {transcript_text}"
        )

        self._print_formatted_output(ticker, guidance_report, capex_report)

    def _execute_deterministic_fallback(self, ticker: str, text: str):
        """
        Ensures the script returns structured intelligence even if no API key is active.
        """
        # Programmatic parsing for key market triggers frequently scanned by FinceptTerminal heuristics
        lines = text.split("\n")
        capex_lines = [line.strip() for line in lines if "CapEx" in line or "₹" in line]
        guidance_lines = [
            line.strip()
            for line in lines
            if "expect" in line or "pressure" in line or "FY27" in line
        ]

        print("-" * 60)
        print(f"DETECTIONS FOR {ticker.upper()} (RUNNING VIA DETERMINISTIC FALLBACK MODE)")
        print("-" * 60)
        print("\n[Identified Capital Expenditure Signals]:")
        for line in capex_lines:
            print(f" • {line}")

        print("\n[Identified Risk & Guidance Signals]:")
        for line in guidance_lines:
            print(f" • {line}")
        print("-" * 60)

    def _print_formatted_output(self, ticker: str, guidance: str, capex: str):
        print("-" * 60)
        print(f"FINROBOT / FINCEPT MULTI-AGENT TRANSCRIPT BREAKDOWN: {ticker.upper()}")
        print("-" * 60)
        print("\n### LAYER 1: MANAGEMENT FORWARD GUIDANCE SUMMARY")
        print(guidance)
        print("\n### LAYER 2: CAPEX AND CAPITAL ALLOCATION AUDIT")
        print(capex)
        print("-" * 60)


if __name__ == "__main__":
    # Test our pipeline with a standard Indian tech benchmark: TCS
    pipeline = IndianEarningsAnalyzerPipeline()
    pipeline.analyze_transcript("TCS.NS")
