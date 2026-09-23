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


import socket

from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from visitors.service.models import Visitor
from visitors.service.serializers import VisitorSerializer


class VisitorAPI(APIView):
    def get(self, request):
        qs = Visitor.objects.order_by("-timestamp")[:10]
        s = VisitorSerializer(qs, many=True)
        return Response(s.data)

    def post(self, request):
        service_ip = socket.gethostbyname(socket.gethostname())
        client_ip = self.get_client_ip(request)

        v = Visitor(service_ip=service_ip, client_ip=client_ip)
        v.save()

        s = VisitorSerializer(v)
        return Response(s.data)

    @staticmethod
    def get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        return x_forwarded_for.split(",")[0] if x_forwarded_for else request.META.get("REMOTE_ADDR")
