def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST,OPTIONS",     # <-- idem
        "Access-Control-Allow-Headers": "Content-Type,Authorization,apikey"
    }
