# helpers/cors_headers.py
ALLOWED_ORIGINS = [
    "https://editor.weweb.io",
    "https://sandbox.smartisupply.com.br"
]

def cors_headers(origin: str | None) -> dict:
    headers = {
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,internal-token,x-api-key"
    }

    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"

    return headers