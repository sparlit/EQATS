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


"""Plain-language explanations (the 5W1H layer).

WHY THIS FILE EXISTS
The owner is not a finance person. Every number the terminal shows must be
explainable in ordinary words, on demand, without jargon. Keeping the wording in
ONE place means the UI, the API and the Telegram alerts can never drift apart,
and fixing a confusing sentence fixes it everywhere.

Structure: each entry answers the same six questions.

    what      - what is this, in one plain sentence
    why       - why it matters for a decision
    look      - what to look for / what a good vs bad value looks like
    where     - where else in the system this same idea shows up (interlinking)
    when      - when to act, wait, or ignore
    how       - how it is worked out (kept non-technical)
    sight     - how to spot this yourself without any tool

Written for someone who has never read a trading book.
"""

# --------------------------------------------------------------------------
# The vocabulary. Keys are lower_snake_case and are what the UI sends.
# --------------------------------------------------------------------------
EXPLAIN = {
    # ---------------------------------------------------------------- regime
    "regime": {
        "title": "Market weather",
        "what": "A one-word read on whether the overall market is going up, "
        "going down, or undecided.",
        "why": "Almost every stock follows the market on a bad day. Checking the "
        "weather first stops us from buying strength into a falling market.",
        "look": "Calm and rising = safest for new buys. Falling = new buys are "
        "held back, and only deep-value bargains are considered.",
        "where": "Decides whether the swing scanner runs normally or switches to "
        "'all-weather' mode. Also scales how much money we suggest "
        "risking, and it is the first gate every signal must pass.",
        "when": "Check it before acting on anything else. If it says the market is "
        "weak, treat every buy idea as fragile.",
        "how": "We compare today's index level with its recent short-term average. "
        "Above it and rising means healthy; below it means weak.",
        "sight": "Open any index chart. Is the line above or below its recent "
        "average, and is that average pointing up or down?",
    },
    "breadth": {
        "title": "How many shares are joining in",
        "what": "The share of tracked stocks trading above their own recent average price.",
        "why": "A rising index can be carried by a handful of large companies "
        "while most shares fall. Breadth tells us whether the rise is "
        "broad or narrow.",
        "look": "More than half above their average, and more shares rising than "
        "falling, is healthy. A narrow market is a warning.",
        "where": "Second gate on every new signal, and it feeds the market-weather reading.",
        "when": "If breadth is weak, expect new buy ideas to fail more often, even "
        "if the index looks fine.",
        "how": "Count the tracked stocks above their 50-day average price, and "
        "count how many rose versus fell.",
        "sight": "Scan a watchlist: is most of it green and above its recent "
        "average, or only a few names?",
    },
    # ---------------------------------------------------------------- setup
    "setup": {
        "title": "The pattern we look for",
        "what": "A stock that rose strongly, then quietly paused, and is now "
        "sitting still just above its recent average price.",
        "why": "Big moves rarely start from nothing. They usually pause first "
        "while the eager sellers leave, then continue. We buy the pause, "
        "not the excitement.",
        "look": "A clear earlier rise, a calm sideways drift of two to four weeks, "
        "much lighter trading volume than before, and the price resting on "
        "its short-term average.",
        "where": "Used by the swing scanner, the daily Top Picks list, the research "
        "pages, and the paper-trading experiment, so all of them judge the "
        "same way.",
        "when": "Only act once the price pushes above the tight pause. Before that "
        "it is a watch item, not a buy.",
        "how": "Five plain checks in order: was there a real rise; did it pause "
        "gently; did trading go quiet; is it resting on its average; is the "
        "pause tight. All five must be yes.",
        "sight": "Find a chart that climbed, then went flat and boring for a few "
        "weeks with small daily moves. That flat, boring patch is the "
        "pattern.",
    },
    "shape_score": {
        "title": "How tidy the pause is",
        "what": "A 0-100 tidiness grade for the sideways pause.",
        "why": "A calm, even pause is more likely to continue than a jagged one. "
        "This lets us rank equally valid patterns.",
        "look": "Higher is tidier. Above 60 is a clean pause; below 40 is messy.",
        "where": "Shown on research pages, and it sets the confidence label on "
        "paper-trading entries.",
        "when": "Use it to choose between two otherwise similar ideas.",
        "how": "We measure how far the price dipped during the pause and how jumpy "
        "the daily moves were. Smoother and shallower scores higher.",
        "sight": "Look at the flat part. A smooth line scores high; a sawtooth scores low.",
    },
    "impulse": {
        "title": "The earlier rise",
        "what": "How much the stock climbed before it started pausing.",
        "why": "We want a genuine move, not a stock that has been flat for years. "
        "But we also avoid ones that already ran too far and are exhausted.",
        "look": "Roughly a fifth to three-quarters higher over a few months is the "
        "sweet spot. Bigger than that is overdone.",
        "where": "Part of the setup pattern, and reused in the research pages and "
        "paper-trading test.",
        "when": "No rise means no setup. Ignore the rest of the pattern.",
        "how": "Compare the highest price in the run with the lowest price just before it began.",
        "sight": "Find where the chart started climbing and where it peaked. Was "
        "that a substantial climb, or barely anything?",
    },
    "pullback": {
        "title": "The pause dip",
        "what": "How far the price has eased back from its recent high.",
        "why": "A small dip means sellers are not aggressive. A large dip means the "
        "move may already be broken.",
        "look": "A gentle few percent to about a quarter off the high. A sudden "
        "sharp drop is not a pause, it is a fall.",
        "where": "Part of the setup pattern; also used in the research pages.",
        "when": "If the dip is too deep or too violent, wait. It is not our pattern.",
        "how": "Compare today's price with the highest recent price.",
        "sight": "How far down is it from the peak? A shallow step back is fine; a cliff is not.",
    },
    "volume": {
        "title": "Trading quietness",
        "what": "Whether the number of shares changing hands has gone quiet.",
        "why": "Quiet trading during a pause means sellers have stopped dumping. "
        "Heavy trading during a pause means something is wrong.",
        "look": "Volume clearly below its recent normal. We compare the last few "
        "days with the average of the past month.",
        "where": "Part of the setup pattern, and a separate flag on the market overview.",
        "when": "Quiet is good. If trading is still heavy while the price drifts sideways, wait.",
        "how": "Compare the average number of shares traded over the last few days "
        "with the average over the past month, and also check whether "
        "today's trading alone is unusually light.",
        "sight": "On a chart, are the recent volume bars visibly shorter than the ones before?",
    },
    # ---------------------------------------------------------------- scores
    "p_win": {
        "title": "Chance of a good move",
        "what": "Our model's estimated probability that this stock climbs at least "
        "10% within the next month of trading.",
        "why": "It lets us rank hundreds of stocks by one consistent yardstick "
        "instead of gut feel.",
        "look": "Higher is better. Around half is a coin flip; meaningfully above "
        "half is the model's genuine interest.",
        "where": "The biggest ingredient in the daily Top Picks ranking, and it "
        "sorts the swing list.",
        "when": "Treat it as a lean, not a promise. It has been wrong before, and "
        "the system's own record says so.",
        "how": "A pattern-recognition model trained on years of past cases, scoring "
        "how similar today looks to cases that worked.",
        "sight": "You cannot see this by eye. It is the machine's opinion, which is "
        "why the plain checklist matters more.",
    },
    "composite": {
        "title": "Overall ranking score",
        "what": "One blended score combining the chance of a good move with other evidence.",
        "why": "One number sorts the whole list, so the best ideas rise to the top.",
        "look": "Higher is better. Small differences near the top are not "
        "meaningful; only clear gaps matter.",
        "where": "Produces the daily Top Picks list shown on the overview.",
        "when": "Use it to decide what to look at first, never as a reason to buy on its own.",
        "how": "A weighted mix: the chance of a good move counts most, then money "
        "quietly accumulating, then the sector's strength, then delivery "
        "activity.",
        "sight": "Not visible by eye. It exists to order the queue.",
    },
    "accum": {
        "title": "Quiet accumulation",
        "what": "How much of recent trading has been buying rather than selling, "
        "judged by which days closed higher on heavier volume.",
        "why": "Large buyers work slowly and quietly. This is our best available "
        "clue that someone substantial is building a position.",
        "look": "Higher means more consistent buying pressure. Around half means no clear story.",
        "where": "Feeds the ranking score and the Top Picks list.",
        "when": "Strong accumulation plus the pause pattern is a good combination. "
        "Weak accumulation is not a reason to reject by itself.",
        "how": "Compare the volume on up days with the volume on down days over recent weeks.",
        "sight": "Look at whether the bigger volume bars line up with the green "
        "days or the red days.",
    },
    "delivery": {
        "title": "Shares actually taken home",
        "what": "The share of traded stock that buyers chose to hold rather than "
        "resell the same day.",
        "why": "Day traders flip shares; long-term holders take delivery. High "
        "delivery suggests genuine buying interest, not just churn.",
        "look": "Persistently high is interesting. One odd day means nothing.",
        "where": "Feeds the ranking score, and appears on the research pages.",
        "when": "Meaningful when it stays high for many days in a row alongside a pause.",
        "how": "Official exchange figures comparing traded quantity with delivered quantity.",
        "sight": "Not visible on a price chart. It comes from separate exchange data.",
    },
    "sector_rs": {
        "title": "Sector strength",
        "what": "How the stock's industry group is performing compared with other groups.",
        "why": "Strong shares often come from strong groups. Being in a leading "
        "group adds wind at your back.",
        "look": "Top-three groups are allowed for new signals. Leading means "
        "beating other groups over the past one to three months.",
        "where": "A gate on new signals, an input to the ranking score, and a "
        "column on the research pages.",
        "when": "If the group is weak, be more sceptical even when the chart looks good.",
        "how": "Rank all industries by their recent one-month and three-month "
        "performance, weighted together.",
        "sight": "Compare a few industry charts over the past month. Which ones look strongest?",
    },
    # ---------------------------------------------------------------- risk
    "stop": {
        "title": "The point where you admit you were wrong",
        "what": "A pre-chosen price below your entry where you sell and accept a small loss.",
        "why": "Deciding the exit before you buy removes emotion. Small planned "
        "losses are how you stay in the game long enough to win.",
        "look": "Usually just below the low of the pause. If that price is more "
        "than about 5% below entry, the trade is too risky and skipped.",
        "where": "Used on every signal, in the risk calculator, and in the "
        "paper-trading experiment.",
        "when": "Set it before you buy. Never move it further away.",
        "how": "We use the low of the pattern day, then check the distance to entry is acceptable.",
        "sight": "Find the lowest point of the flat pause. That is your safety line.",
    },
    "target": {
        "title": "The point where you take profit",
        "what": "A pre-chosen price above your entry where you sell for a gain.",
        "why": "Without a plan, winners get given back. A fixed goal makes the "
        "decision mechanical.",
        "look": "Set at a multiple of what you risked. Aiming for three times the "
        "risk is the system default.",
        "where": "Used on every signal, the risk calculator, and the paper-trading experiment.",
        "when": "Consider taking part of the profit when the price has moved twice "
        "your risk; move your safety line to your entry price then.",
        "how": "Entry price plus three times the distance between entry and your safety line.",
        "sight": "Measure the gap from entry down to your safety line, then count "
        "the same distance three times upward.",
    },
    "risk_pct": {
        "title": "How much you are risking",
        "what": "The percentage of your entry price you would lose if the safety line is hit.",
        "why": "It makes different ideas comparable. A wide safety line means a "
        "smaller position, not a bigger loss.",
        "look": "Up to about 5% is acceptable. More than that and the system skips the idea.",
        "where": "Checked on every signal and used by the position-size calculator.",
        "when": "Before entering. If it is too wide, wait for a tighter setup.",
        "how": "The distance from entry down to the safety line, as a percentage of entry.",
        "sight": "Compare where the pause low sits with the price you would pay.",
    },
    "sizing": {
        "title": "How much money to put in",
        "what": "A suggested number of shares based on your total capital and how "
        "far away your safety line is.",
        "why": "Position size, not stock picking, decides whether a bad streak "
        "hurts you. This keeps every loss a similar, survivable size.",
        "look": "Bigger safety-line distance means fewer shares. There are hard "
        "ceilings so no single idea can dominate.",
        "where": "Shown on research pages; the same idea drives the paper-trading experiment.",
        "when": "Always check it before buying. Never round up 'because you like the stock'.",
        "how": "Risk a small fixed slice of capital, then work out how many shares "
        "that allows given the distance to the safety line.",
        "sight": "Ask yourself: if this fails, is the loss small enough to shrug "
        "off? If not, buy fewer shares.",
    },
    # ------------------------------------------------------- how results read
    "r_multiple": {
        "title": "R - one bite of risk",
        "what": "One R is the money you decided to risk on that trade: the gap "
        "between the price you paid and the safety line under it.",
        "why": "It turns every result into the same size of yardstick. A trade "
        "where you risked ₹500 and one where you risked ₹5,000 can then be "
        "compared honestly.",
        "look": "Plus 2R means you made twice what you risked. Minus 1R means you "
        "lost exactly the amount you had already accepted losing. Zero R "
        "means it ended flat.",
        "where": "Shown next to every closed idea on the performance page, and "
        "inside the MFE and MAE numbers on the research page.",
        "when": "Read it after the trade is finished. It tells you the size of the "
        "result, not whether the idea was good.",
        "how": "The gap from your buy price down to your safety line counts as 1R. "
        "The final profit or loss is then divided by that gap.",
        "sight": "Measure the distance from your buy price down to the safety line "
        "with your finger. If the price later ended up twice that distance "
        "above your buy price, that was +2R.",
    },
    "mfe": {
        "title": "The best it ever looked",
        "what": "The furthest the price went in your favour while the trade was "
        "open, counted in R.",
        "why": "It measures how much was on the table at the best moment. If the "
        "best moment was far ahead but the trade ended flat, the plan gave "
        "back a real opportunity.",
        "look": "A high number means the trade did most of the work at some point. "
        "Around 1R or less means it never really went your way.",
        "where": "Shown as 'MFE in R' on the research page, and in the small "
        "table of past patterns below it.",
        "when": "Use it to judge the plan rather than the outcome. Comparing the "
        "best moment with the final result shows whether profit was given "
        "back.",
        "how": "While the trade is open we keep track of the highest point reached, "
        "then express that gain as a multiple of the risk.",
        "sight": "Find the highest point on the chart between buying and selling. "
        "That peak is the MFE.",
    },
    "mae": {
        "title": "The worst it ever looked",
        "what": "The deepest the price dipped against you while the trade was open, counted in R.",
        "why": "It shows how much discomfort the trade caused on the way. Ideas "
        "that go far against you before working are the ones that make "
        "people panic and sell at the bottom.",
        "look": "A small dip - well under 1R - is a comfortable ride. Reaching or "
        "passing 1R means your safety line was tested or hit.",
        "where": "Shown as 'MAE in R' on the research page, next to the MFE.",
        "when": "Read it when deciding whether you could really sit through this "
        "kind of trade without giving up.",
        "how": "We track the lowest point the price touched while the trade was "
        "open, then express that dip as a multiple of the risk.",
        "sight": "Find the lowest point on the chart between buying and selling. "
        "That dip is the MAE.",
    },
    "hit_rate": {
        "title": "How often it got there",
        "what": "The share of past similar ideas that reached a particular level "
        "before failing - for example +1R, +2R, or +3R.",
        "why": "A single goal hides the odds. Knowing that most ideas reach +1R but "
        "only some reach +3R tells you how realistic each goal is.",
        "look": "Read each level separately. The +1R figure should be the largest "
        "and +3R the smallest, because climbing higher is harder. A big "
        "drop from +1R to +2R means most ideas stall early.",
        "where": "Shown on the research page as 'Hit rate' and in the small "
        "table of past patterns below it.",
        "when": "Use it to choose a realistic profit goal, and to judge whether "
        "waiting for the full target is worth it.",
        "how": "We take past cases that looked like today's and count how many "
        "reached each level. The count is shown as a percentage.",
        "sight": "You cannot see this on one chart. It is a tally across many past "
        "charts, which is why it is worked out for you.",
    },
    "expectancy": {
        "title": "Average result per idea",
        "what": "The typical result of one idea, in R, averaged over every idea "
        "the system recorded.",
        "why": "It answers the only question that matters over time: on average, "
        "does one more idea add to the pot or take from it.",
        "look": "Above zero is a system that pays over many ideas. Below zero means "
        "the average idea loses money, no matter how good the best ones "
        "looked.",
        "where": "Shown on the performance page as 'Average result per idea'.",
        "when": "Judge it only over many ideas. A handful of results can make this "
        "number look good or bad by pure luck.",
        "how": "Add up the R results of every recorded idea and divide by how many there were.",
        "sight": "Not visible on a chart. It is a running average of the system's own scorecard.",
    },
    "profit_factor": {
        "title": "Profit per unit lost",
        "what": "How many rupees of winning ideas there are for every one rupee of losing ideas.",
        "why": "It shows whether the winners are big enough to pay for the losers, "
        "which is what keeps the account alive.",
        "look": "Above 1 means winners outweigh losers. Around 1.5 or more is "
        "solid. Below 1 means the losses are bigger than the gains.",
        "where": "Shown on the performance page as 'Profit per unit lost'.",
        "when": "Check it alongside the win rate. Many small wins can still lose "
        "money if the rare losses are huge.",
        "how": "All the winning R results are added up, then divided by the total "
        "size of the losing R results.",
        "sight": "Not visible on a chart. Compare the total of the green results "
        "with the total of the red results by eye instead.",
    },
    "max_drawdown": {
        "title": "Worst fall from a peak",
        "what": "The deepest the running total fell from its highest point, in R.",
        "why": "This is the number that decides whether you can stay calm and stay "
        "in. A plan you abandon in a bad patch is no plan.",
        "look": "Smaller is easier to live with. Compare it with the average result "
        "per idea - a big fall against a small average means a rough ride.",
        "where": "Shown on the performance page as 'Worst fall from a peak'.",
        "when": "Read it before trusting a good-looking average, and size your "
        "positions so this fall stays survivable.",
        "how": "We follow the running total of results, note each high point, and "
        "find the largest drop that followed a high.",
        "sight": "Not visible on a chart. Look at the losing results in order and "
        "ask how many in a row would make you quit.",
    },
    "veto": {
        "title": "Automatic disqualification",
        "what": "A rule that blocks a stock because its company finances look "
        "unsafe, regardless of how good the chart is.",
        "why": "A beautiful chart on a heavily indebted company can collapse "
        "overnight. This keeps weak balance sheets out of the list.",
        "look": "Blocked when debt is far above profits, when the return on capital "
        "is very low, or when the owners hold very little of their own "
        "company.",
        "where": "Blocks new signals, removes names from Top Picks, and hides bullish patterns.",
        "when": "If a stock is blocked, stop. Do not look for a reason to override it.",
        "how": "Three simple thresholds read from stored company finances. A "
        "missing figure passes by default, which is a known weakness.",
        "sight": "You cannot see this on a chart. It comes from company accounts.",
    },
    # ---------------------------------------------------------------- quality
    "data_quality": {
        "title": "Is our data trustworthy today",
        "what": "Six automatic checks on whether the numbers behind the system are "
        "complete and fresh.",
        "why": "Every decision is only as good as the data under it. Stale prices "
        "silently produce confident nonsense.",
        "look": "Green across the board. Any red means results should be treated as "
        "suspect until fixed.",
        "where": "Runs first thing each day, before anything else. Failures are "
        "messaged to you directly.",
        "when": "Check it whenever a result looks surprising.",
        "how": "We look for gaps in dates, duplicated rows, impossible prices, "
        "sudden unexplained jumps, and missing symbols.",
        "sight": "Compare today's date with the newest date in the data tables.",
    },
    "sources": {
        "title": "Where the numbers come from",
        "what": "A live health list of every outside service the system reads from.",
        "why": "If a source is quietly broken, the system can look healthy while "
        "silently deciding on stale information.",
        "look": "Every source should show as healthy with a recent success. "
        "Warnings and errors are informative, not cosmetic.",
        "where": "Feeds prices, company finances, industry groups, and delivery "
        "figures used everywhere else.",
        "when": "Check here first whenever many results look wrong at once.",
        "how": "Each connector reports its own success count, failure count, and last error.",
        "sight": "Not applicable - this is an internal health readout.",
    },
    "signal": {
        "title": "A recorded buy idea",
        "what": "A moment the system decided a stock matched our pattern, with the "
        "entry, safety line, and goal written down at that time.",
        "why": "Writing it down before the outcome is known is the only honest way "
        "to know whether the system actually works.",
        "look": "Each one is later graded as a win, a loss, expired, or timed out. "
        "The tally over many cases is the real scorecard.",
        "where": "Feeds the performance page, the research pages, and the "
        "paper-trading experiment.",
        "when": "Only meaningful in bulk. A handful of results proves nothing either way.",
        "how": "Recorded only after passing every check: market weather, breadth, "
        "sector strength, the pattern itself, freshness, and the "
        "disqualification rules.",
        "sight": "Not visible by eye. It is the system's receipt for a decision.",
    },
}

# Friendly names for the six questions, in the order the UI shows them.
SECTIONS = [
    ("what", "What is it"),
    ("why", "Why it matters"),
    ("look", "What to look for"),
    ("where", "Where else it is used"),
    ("when", "When to act"),
    ("how", "How it is worked out"),
    ("sight", "How to spot it yourself"),
]


def get(key):
    """One explanation, or None when the key is unknown."""
    return EXPLAIN.get((key or "").strip().lower())


def all_keys():
    return sorted(EXPLAIN)


def catalog():
    """Lightweight list for the UI index (no long text)."""
    return [{"key": k, "title": v["title"], "what": v["what"]} for k, v in sorted(EXPLAIN.items())]
