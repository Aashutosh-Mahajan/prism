"""Restaurant ordering views."""

from rest_framework.response import Response
from rest_framework.views import APIView


class OrderViewSet(APIView):
    def update_status(self, request, order_id):
        status = request.data.get("status")
        if status not in ("accepted", "preparing", "ready", "delivered"):
            return Response({"error": {"message": "Unknown status"}}, status=400)
        return Response({"id": order_id, "status": status})

    def sync_tracking(self, order):
        """Advance the customer-facing tracking status after the restaurant acts."""
        return {"order": order, "tracking": "in_progress"}
