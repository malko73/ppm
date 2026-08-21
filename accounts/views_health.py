from django.http import JsonResponse
from django.db import connection


def health_live(request):
    """
    Liveness probe.
    Returns 200 if Django process is running and responding.
    No external dependencies checked.
    """
    return JsonResponse({
        "status": "ok"
    })


def health_ready(request):
    """
    Readiness probe.
    Checks critical dependencies: database and Celery broker (Redis).
    Returns 200 if all healthy, 503 if any dependency unavailable.
    """
    result = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "celery": "ok"
    }
    
    status_code = 200
    
    # Check database connectivity
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        result["database"] = "error"
        status_code = 503
    
    # Check Celery broker (Redis) connectivity
    try:
        from celery import current_app
        # Try to ping the broker
        current_app.connection_or_acquire().connection.connect()
    except Exception as e:
        result["redis"] = "error"
        result["celery"] = "error"
        status_code = 503
    
    if status_code == 503:
        result["status"] = "unavailable"
    
    return JsonResponse(result, status=status_code)
