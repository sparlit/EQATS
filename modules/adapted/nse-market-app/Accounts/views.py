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


from Broker.models import *
from django.contrib import messages
from django.contrib.auth.models import User, auth
from django.http import HttpResponse
from django.shortcuts import redirect, render


# Create your views here.
def register_user(request):
    if not request.user.is_authenticated:
        if request.method == "POST":
            first_name = request.POST["first_name"]
            last_name = request.POST["last_name"]
            username = request.POST["username"]
            email = request.POST["email"]
            password1 = request.POST["password1"]
            password2 = request.POST["password2"]

            if password1 == password2:
                if User.objects.filter(username=username).exists():
                    messages.info(request, "username is taken, choose another!")
                    return redirect("Accounts:register_user")

                elif User.objects.filter(email=email).exists():
                    messages.info(request, "Email is taken, choose another!")
                    return redirect("Accounts:register_user")

                else:
                    user = User.objects.create_user(
                        username=username,
                        password=password1,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    user.save()

                    return redirect("Accounts:login_user")

            else:
                messages.info(request, "Password didn't match")
                return redirect("Accounts:register_user")

        return render(request, "Accounts/register.html")


def login_user(request):
    logout_user(request)
    if not request.user.is_authenticated:
        if request.method == "POST":
            username = request.POST["username"]
            password = request.POST["password"]

            user = auth.authenticate(username=username, password=password)
            if user is not None:
                auth.login(request, user)
                return redirect("Broker:userpage")

            else:
                messages.info(request, "invalid credentials!")
                return redirect("Accounts:login_user")

        else:
            return render(request, "Accounts/login.html")

    else:
        return HttpResponse("you are not permitted to view this page!")


def logout_user(request):
    auth.logout(request)
    return redirect("Accounts:login_user")
