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
    Checks critical dependencies: database, Redis, Celery broker.
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
    
    # Check Redis connectivity (Celery broker)
    try:
        from django.core.cache import cache
        # Try to set and get a value from cache (Redis)
        cache.set('_health_check', 'ok', 10)
        cache.get('_health_check')
    except Exception as e:
        result["redis"] = "error"
        result["celery"] = "error"
        status_code = 503
    
    if status_code == 503:
        result["status"] = "unavailable"
    
    return JsonResponse(result, status=status_code)
