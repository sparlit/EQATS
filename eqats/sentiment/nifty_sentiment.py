# eqats/sentiment/nifty_sentiment.py
"""
Sentiment analysis wrapper for Nifty-500 live sentiment analysis.
Provides a function to compute FinBERT-based sentiment score for a given text.
"""

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import torch.nn.functional as F
from functools import lru_cache

_MODEL_NAME = \"yiyanghkust/finbert-tone\"

@lru_cache(maxsize=1)
def _get_model():
    tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(_MODEL_NAME)
    model.eval()
    return tokenizer, model

def get_sentiment(text: str) -> float:
    """
    Return sentiment score in range [-1, 1] where:
      -1 -> negative sentiment,
       0 -> neutral,
       1 -> positive sentiment.
    Uses FinBERT-tone (labels: negative, neutral, positive).
    """
    if not text:
        return 0.0
    tokenizer, model = _get_model()
    inputs = tokenizer(text, return_tensors=\"pt\", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**inputs).logits
        probs = F.softmax(logits, dim=-1).squeeze().tolist()
    # order: model.config.id2label => {0: 'negative', 1: 'neutral', 2: 'positive'}
    negative, neutral, positive = probs
    # map to [-1, 1]: sentiment = positive - negative
    return positive - negative

# Simple self-test
if __name__ == \"__main__\":
    examples = [
        \"Market rallies on strong earnings.\",
        \"Stocks crash amid fears of recession.\",
        \"No clear direction today.\"
    ]
    for ex in examples:
        print(f\"'{ex}' -> {get_sentiment(ex):.3f}\")