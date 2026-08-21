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
        import redis
        from django.conf import settings
        
        # Parse CELERY_BROKER_URL to get Redis connection details
        broker_url = settings.CELERY_BROKER_URL
        # redis://localhost:6379/0 or redis://[password]@localhost:6379/0
        
        if broker_url.startswith('redis://'):
            # Simple Redis connection test
            r = redis.StrictRedis.from_url(broker_url, decode_responses=True)
            r.ping()
    except Exception as e:
        result["redis"] = "error"
        result["celery"] = "error"
        status_code = 503
    
    if status_code == 503:
        result["status"] = "unavailable"
    
    return JsonResponse(result, status=status_code)
