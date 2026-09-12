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
from mongoengine.errors import DoesNotExist, InvalidDocumentError, ValidationError
from resources.errors import SchemaValidationError

from database.models import Script, Trade, User


class AddTradeApi(Resource):
    @jwt_required
    def post(self):
        try:
            user = User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            body = request.get_json()
            script = Script.objects.get(code=body.get("code"))
            trade = Trade(**body, user=user, full_name=script.full_name)
            trade.save()
            return {"type": "success", "success": "Trade successfully added."}, 200
        except (ValidationError, InvalidDocumentError):
            return SchemaValidationError, 400
        except DoesNotExist:
            return {"type": "error", "error": "Code does not exist."}, 200
        except Exception as e:
            print(type(e).__name__)
            print(e)
            return {"error": "Internal server error"}, 500


class TradesApi(Resource):
    @jwt_required
    def post(self):
        try:
            user = User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            trades = list(Trade.objects(user=user.username).exclude("user", "id").order_by("-date").as_pymongo())
            return Response(json.dumps(trades, default=str), mimetype="application/json", status=200)
        except DoesNotExist:
            return {"error": "No trades in this account"}, 200
        except Exception as e:
            print(type(e).__name__, e)
            return {"error": "Internal server error"}, 500


class PortfolioApi(Resource):
    @jwt_required
    def post(self):
        try:
            User.objects.get(username=get_jwt_identity())
        except DoesNotExist:
            return {"msg": "Signature verification failed"}, 422

        try:
            username = get_jwt_identity()
            trades = Trade.objects(user=username).exclude("user", "id").order_by("date").as_pymongo()
            codes = list({i["code"] for i in trades})
            companies = (
                Script.objects(code__in=codes)
                .exclude("id", "nseHist", "bseHist", "url", "shareholding", "standalone", "consolidated")
                .order_by("name")
                .as_pymongo()
            )
            curr_val, investment, realised_pl, daily_net_change, response = 0, 0, 0, 0, {"scripts": []}
            for i in companies:
                price, prev_close = i[i["priceObj"]]["price"], i[i["priceObj"]]["prev_close"]
                buy_list = [ob for ob in trades if ob["code"] == i["code"] and ob["trade"] == "b"]
                sold_list = [ob for ob in trades if ob["code"] == i["code"] and ob["trade"] == "s"]

                net_sold, sell_val, net_buy, buy_val, net_pos, j = 0, 0, 0, 0, 0, 0
                for sold in sold_list:
                    net_sold += sold["qty"]
                    sell_val += sold["qty"] * sold["price"]
                while (net_buy + buy_list[j]["qty"]) <= net_sold:
                    net_buy += buy_list[j]["qty"]
                    buy_val += buy_list[j]["qty"] * buy_list[j]["price"]
                    j += 1
                i["realisedProfit"] = sell_val - (buy_val + (buy_list[j]["price"] * (net_sold - net_buy)))
                net_pos = buy_list[j]["qty"] + net_buy - net_sold
                unrealised_val = buy_list[j]["price"] * net_pos
                j += 1
                while j < len(buy_list):
                    net_pos += buy_list[j]["qty"]
                    unrealised_val += buy_list[j]["qty"] * buy_list[j]["price"]
                    j += 1
                avg_price = round(unrealised_val / net_pos, 2)
                i["unrealised_pl"] = round(net_pos * price - unrealised_val, 2)
                i["change"] = round((price - prev_close) * net_pos, 2)
                i["net_change"] = round((price - avg_price) * 100 / avg_price, 2) if avg_price != 0 else 100
                i["daily_change"] = round((price - prev_close) * 100 / avg_price, 2) if avg_price != 0 else 0
                i["netPos"] = net_pos
                i["avg_price"] = avg_price
                daily_net_change += round(net_pos * (price - prev_close))
                investment += round(net_pos * avg_price)
                curr_val += round(net_pos * price)
                realised_pl += i["realisedProfit"]
                response["scripts"].append(i)
            response.update(
                {
                    "currVal": curr_val,
                    "investment": investment,
                    "pl": curr_val - investment,
                    "holding": len(response["scripts"]),
                }
            )
            response.update({"realisedPL": realised_pl, "daily_net_change": daily_net_change})
            return Response(json.dumps(response, default=str), mimetype="application/json", status=200)
        except Exception as e:
            print(type(e).__name__, e)
            return {"error": "Internal server error"}, 500
