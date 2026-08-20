from django.conf import settings

class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        directives = []
        csp_prefix = "CSP_"
        default = getattr(settings, "CSP_DEFAULT_SRC", ("'self'",))
        directives.append("default-src " + " ".join(default))
        for attr in sorted(dir(settings)):
            if not attr.startswith(csp_prefix):
                continue
            name = attr[len(csp_prefix):].lower().replace("_", "-")
            value = getattr(settings, attr, None)
            if isinstance(value, (tuple, list)):
                directives.append(f"{name} {' '.join(value)}")
        if directives:
            response["Content-Security-Policy"] = "; ".join(directives)
        return response
