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


from datetime import timedelta

from flask import request
from flask_jwt_extended import create_access_token
from flask_restful import Resource
from mongoengine.errors import DoesNotExist, FieldDoesNotExist, NotUniqueError, ValidationError
from mongoengine.queryset.visitor import Q
from resources.errors import EmailAlreadyExistsError, InternalServerError, SchemaValidationError, UnauthorizedError

from database.models import User


class SignupApi(Resource):
    def post(self):
        try:
            body = request.get_json()
            username = body.get("username").title()
            email = body.get("email")
            password = body.get("password")
            if username is None or password is None or email is None:
                raise ValidationError
            if password != body.get("password2"):
                return {"password": "Passwords do not match."}, 400
            if User.objects(Q(username__iexact=username) or Q(email__iexact=email)).count() > 0:
                raise NotUniqueError
            user = User(username=username, password=password, email=email)
            user.hash_password()
            user.save()

            expires = timedelta(days=7)
            access_token = create_access_token(identity=str(user.id), expires_delta=expires)
            return {
                "type": "success",
                "success": "Login succesfull.",
                "username": user.username,
                "token": "Bearer " + access_token,
            }, 200
        except (FieldDoesNotExist, ValidationError, ValueError):
            return SchemaValidationError, 400
        except NotUniqueError:
            return EmailAlreadyExistsError, 400
        except Exception as e:
            print(e)
            return InternalServerError, 500


class LoginApi(Resource):
    def post(self):
        try:
            body = request.get_json()
            password = body.get("password")
            if password is None:
                return {"error": "Email or Password invalid"}, 401

            user = User.objects.get(username__iexact=body.get("username"))
            authorized = user.check_password(password)
            if not authorized:
                return {"error": "Email or Password invalid"}, 401

            expires = timedelta(days=7)
            access_token = create_access_token(identity=str(user.id), expires_delta=expires)
            return {
                "type": "success",
                "success": "Login succesfull.",
                "username": user.username,
                "token": "Bearer " + access_token,
            }, 200
        except DoesNotExist:
            return UnauthorizedError, 401
        except Exception as e:
            print(type(e).__name__)
            print(e)
            return InternalServerError, 500
