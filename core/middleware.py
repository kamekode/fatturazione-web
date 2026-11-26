class IntestazioniSicurezzaMiddleware:
    """Aggiunge intestazioni di sicurezza che Django 5.2 non imposta da solo.

    La Content-Security-Policy predefinita permette solo risorse servite
    dall'applicazione stessa. Una vista può impostarne una propria (ad esempio
    l'anteprima della fattura, che usa stili inline del foglio di stile ufficiale).
    """

    POLITICA_PREDEFINITA = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.POLITICA_PREDEFINITA)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.user.is_authenticated:
            # I dati fiscali non devono restare nella cache del browser o di proxy.
            response.headers.setdefault("Cache-Control", "no-store, private")
        return response
