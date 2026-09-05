import sys
import datetime as dt
import feedparser
import db

MODEL = None

def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS sentiment_headlines(
        symbol TEXT, created_at TEXT, title TEXT, age_days INTEGER,
        label TEXT, prob REAL)""")

def get_model():
    global MODEL
    if MODEL is None:
        from transformers import pipeline
        MODEL = pipeline("text-classification",
                         model="ProsusAI/finbert")
    return MODEL

def fetch_headlines(symbol, name):
    q = name if name else symbol
    url = ("https://news.google.com/rss/search?q="
           + q.replace(" ", "+")
           + "+stock&hl=en-IN&gl=IN&ceid=IN:en")
    feed = feedparser.parse(url)
    out = []
    seen = set()
    now = dt.datetime.now(dt.timezone.utc)
    for e in feed.entries[:40]:
        title = e.get("title", "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        pub = e.get("published_parsed")
        age = 7
        if pub:
            pubdt = dt.datetime(*pub[:6], tzinfo=dt.timezone.utc)
            age = (now - pubdt).days
        if age > 14:
            continue
        out.append((title, age))
    return out

def score_symbol(symbol):
    conn = db.get_conn()
    ensure(conn)
    nrow = conn.execute(
        "SELECT name FROM stocks WHERE symbol=?", (symbol,)).fetchone()
    name = nrow[0] if nrow else None
    headlines = fetch_headlines(symbol, name)
    if not headlines:
        print(symbol, ": no recent headlines found")
        return None
    model = get_model()
    preds = model([t for t, a in headlines], truncation=True)
    pos = neu = neg = 0
    wsum = 0.0
    ssum = 0.0
    now = dt.datetime.now().isoformat()
    conn.execute("DELETE FROM sentiment_headlines WHERE symbol=?",
                 (symbol,))
    for (title, age), p in zip(headlines, preds):
        label = p["label"]
        prob = p["score"]
        conn.execute(
            "INSERT INTO sentiment_headlines VALUES (?,?,?,?,?,?)",
            (symbol, now, title, age, label, prob))
        if label == "positive":
            pos += 1
            s = 1.0
        elif label == "negative":
            neg += 1
            s = -1.0
        else:
            neu += 1
            s = 0.0
        w = 1.0 / (1.0 + age)
        wsum += w
        ssum += w * s
    avg = ssum / wsum if wsum else 0.0
    score = round(50 + 50 * avg, 1)
    major = "YES" if score < 35 else "no"
    conn.execute(
        "INSERT INTO sentiment_results "
        "VALUES (?,?,?,?,?,?,?,?)",
        (symbol, now, len(headlines), pos, neu, neg, score, major))
    conn.commit()
    conn.close()
    print(f"{symbol}: sentiment {score}/100 "
          f"(pos {pos}, neu {neu}, neg {neg})")
    return score

if len(sys.argv) > 2 and sys.argv[1] == "run":
    for s in sys.argv[2:]:
        score_symbol(s.upper())