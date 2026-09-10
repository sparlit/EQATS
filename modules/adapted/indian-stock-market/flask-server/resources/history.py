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


import json
from datetime import datetime, timezone

from flask import Response
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restful import Resource
from mongoengine.errors import DoesNotExist

from database.models import Indicies, Script, User


def date_handler(obj):
    return obj.timestamp() * 1000 if isinstance(obj, datetime) else None


class History(Resource):
    @jwt_required
    def post(self, code, exchange=None):
        try:
            User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            script = Script.objects.get(code=code)
            if exchange == "nse":
                if "nseHist" in script and len(script.nseHist) > 0:
                    response = {"name": script.name, "hist": script.nseHist}
                    return Response(json.dumps(response, default=date_handler), mimetype="application/json", status=200)
                return {"type": "warning", "warning": script.name + " is not traded on NSE."}, 200
            if exchange == "bse":
                if "bseHist" in script and len(script.bseHist) > 0:
                    response = {"name": script.name, "hist": script.bseHist}
                    return Response(json.dumps(response, default=date_handler), mimetype="application/json", status=200)
                return {"type": "warning", "warning": script.name + " is not traded on BSE."}, 200
            if exchange is None:
                if "nseHist" in script and len(script.nseHist) > 0:
                    response = {"name": script.name, "hist": script.nseHist}
                    return Response(json.dumps(response, default=date_handler), mimetype="application/json", status=200)
                if "bseHist" in script and len(script.bseHist) > 0:
                    response = {"name": script.name, "hist": script.bseHist}
                    return Response(json.dumps(response, default=date_handler), mimetype="application/json", status=200)
                return {"type": "warning", "warning": script.name + " is not traded in last 90 days."}, 200
        except DoesNotExist:
            try:
                indicies = Indicies.objects.get(stkexchg__iexact=code)
                response = {"stkexchg": indicies.stkexchg, "name": indicies.stkexchg, "hist": indicies.history}
                return Response(json.dumps(response, default=date_handler), mimetype="application/json", status=200)
            except DoesNotExist:
                return {"type": "error", "error": "Object not Found."}, 200
        except Exception as e:
            print(type(e).__name__, e)
            return {"error": "Internal server error"}, 500
