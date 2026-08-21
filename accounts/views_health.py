from django.http import JsonResponse
from django.db import connection


def health_live(request):
    """
    Liveness probe.
    Returns 200 if Django process is running and responding.
    No external dependencies checked.
    """
    return JsonResponse({"status": "ok"})


def health_ready(request):
    """
    Readiness probe.
    Checks if critical dependencies are available.
    Returns 200 if all OK, 503 if any dependency unavailable.
    """
    result = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "celery": "ok"
    }
    status_code = 200
    
    # Check database
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        result["database"] = "error"
        status_code = 503
    
    # Check Redis/Celery broker via broker connection attempt
    try:
        from celery import current_app
        broker_conn = current_app.connection()
        with broker_conn:
            pass  # Connection opened and closed successfully
    except Exception:
        result["redis"] = "error"
        result["celery"] = "error"
        status_code = 503
    
    if status_code == 503:
        result["status"] = "unavailable"
    
    return JsonResponse(result, status=status_code)
