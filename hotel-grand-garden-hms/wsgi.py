import os

# Vercel / serverless: always production
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    os.environ.setdefault("FLASK_ENV", "production")

from app import create_app

app = create_app()

# Vercel expects the WSGI callable named `app`
if __name__ == "__main__":
    app.run()
