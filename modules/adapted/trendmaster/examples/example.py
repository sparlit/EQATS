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


# Example usage of merged_module.py

import pyotp
from trendmaster import DataLoader, Inferencer, Trainer, TransAm, plot_predictions, plot_results, set_seed

# Set seed for reproducibility
set_seed(42)

user_id = "YOUR_ZERODHA_USER_ID"
password = "YOUR_ZERODHA_PASSWORD"  # Replace with your password
totp_key = "YOUR_ZERODHA_2FA_KEY"  # Replace with your TOTP secret key

# Generate the TOTP code for two-factor authentication
totp = pyotp.TOTP(totp_key)
twofa = totp.now()

# Initialize DataLoader and authenticate
data_loader = DataLoader()
kite = data_loader.authenticate(user_id=user_id, password=password, twofa=twofa)

# Prepare data
train_data, test_data = data_loader.prepare_data(
    symbol="RELIANCE",
    from_date="2023-01-01",
    to_date="2023-02-27",
    input_window=30,
    output_window=10,
    train_test_split=0.8,
)
import torch

# Initialize model, trainer, and train the model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Training of {device} device.")
model = TransAm(num_layers=2, dropout=0.2).to(device)

trainer = Trainer(model, device, learning_rate=0.001)
train_losses, val_losses = trainer.train(train_data, test_data, epochs=2, batch_size=64)

# Save the trained model
trainer.save_model("transam_model.pth")

# Initialize inferencer and make predictions
inferencer = Inferencer(model, device, data_loader)
predictions = inferencer.predict(
    symbol="RELIANCE", from_date="2023-02-27", to_date="2023-12-31", input_window=30, future_steps=10
)

# Evaluate the model
test_loss = inferencer.evaluate(test_data, batch_size=32)
