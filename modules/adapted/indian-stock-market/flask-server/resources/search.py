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

from flask import Response, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restful import Resource
from mongoengine.errors import DoesNotExist
from mongoengine.queryset.visitor import Q

from database.models import Indicies, Script, User


class Search(Resource):
    @jwt_required
    def post(self, searchStr):
        try:
            User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            scripts = (
                Script.objects.filter(Q(name__istartswith=searchStr) | Q(full_name__istartswith=searchStr))
                .only("code", "name", "full_name", "priceObj")
                .exclude("id")
                .as_pymongo()
            )
            indicies = (
                Indicies.objects(stkexchg__istartswith=searchStr)
                .only("stkexchg", "exchange")
                .exclude("id")
                .as_pymongo()
            )
            results = []
            for i in indicies:
                results.append({"stkexchg": i["stkexchg"], "index": i["exchange"], "full_name": i["stkexchg"]})
            results.extend(scripts)

            return results, 200
        except Exception as e:
            print(type(e).__name__, e)
            return {"error": "Internal server error"}, 500
