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
from datetime import datetime, timedelta

from flask import Response, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restful import Resource
from mongoengine.errors import DoesNotExist

from database.models import Indicies, Script, User


class Watchlist(Resource):
    @jwt_required
    def post(self):
        try:
            user = User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            codes = list(user.watchlist)
            watchlist = []
            for ob in (
                Script.objects(code__in=codes)
                .exclude("id", "nseHist", "bseHist", "shareholding", "standalone", "consolidated")
                .as_pymongo()
            ):
                watchlist.append(ob)
                watchlist[-1]["lastupd"] = watchlist[-1]["lastupd"].isoformat()
            for ob in Indicies.objects(stkexchg__in=codes).exclude("id", "history").as_pymongo():
                watchlist.append(ob)
                watchlist[-1]["lastupdated"] = watchlist[-1]["lastupdated"].isoformat()

            watchlist.sort(key=lambda i: codes.index(i["stkexchg"]) if "stkexchg" in i else codes.index(i["code"]))
            return watchlist, 200
        except Exception as e:
            print(type(e).__name__, e)
            return {"error": "Internal server error"}, 500


class AddToWatchlist(Resource):
    @jwt_required
    def post(self, code, index=None):
        try:
            user = User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            if index is not None:
                indicies = Indicies.objects.get(stkexchg=code)
                if code in user.watchlist:
                    return {
                        "type": "warning",
                        "warning": indicies["stkexchg"] + " is already present in your watchlist.",
                    }, 200
                user.watchlist.append(indicies.stkexchg)
                user.save()
                return {
                    "type": "success",
                    "success": indicies["stkexchg"] + " successfully added to your watchlist.",
                }, 200
            script = Script.objects.get(code=code)
            if code in user.watchlist:
                return {
                    "type": "warning",
                    "warning": script["full_name"] + " is already present in your watchlist.",
                }, 200
            user.watchlist.append(script.code)
            user.save()
            return {"type": "success", "success": script["full_name"] + " successfully added to your watchlist."}, 200
        except DoesNotExist:
            return {"type": "error", "error": "Does not exist in our database."}, 200
        except Exception as e:
            print(type(e).__name__, e)
            return {"type": "error", "error": "Internal server error"}, 500


class RemoveFromWatchlist(Resource):
    @jwt_required
    def post(self, code):
        try:
            user = User.objects.get(username=get_jwt_identity())
            if code in user.watchlist:
                user.update(pull__watchlist=code)
                user.save()
                return {"type": "success", "success": "Removed from watchlist."}, 200
            return {"type": "warning", "warning": "Not present in watchlist."}, 200
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422
        except Exception as e:
            print(type(e).__name__, e)
            return {"type": "error", "error": "Internal server error"}, 500


class CommonDetails(Resource):
    @jwt_required
    def post(self):
        try:
            User.objects.get(username=get_jwt_identity())
            date_limit = datetime.today() - timedelta(days=180)
            indicies = {}
            for i in Indicies.objects(stkexchg__in=["NIFTY 50", "SENSEX"]).exclude("id").as_pymongo():
                indicies[i["stkexchg"]] = i
                indicies[i["stkexchg"]]["history"] = [
                    {"x": j[0].strftime("%Y-%m-%d"), "y": j[4]} for j in i["history"] if j[0] > date_limit
                ]
            return Response(json.dumps(indicies, default=str), mimetype="application/json", status=200)
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422
        except Exception as e:
            print(type(e).__name__, e)
            return {"type": "error", "error": "Internal server error"}, 500
