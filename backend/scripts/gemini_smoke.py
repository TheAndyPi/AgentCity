"""One small structured-decision request using the configured billing route."""

import asyncio

from google.auth.exceptions import GoogleAuthError

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway


async def main():
    config = AppConfig.from_env()
    config.validate()
    if not config.gemini_enabled:
        raise SystemExit("Gemini is not configured: check mode, model and project/key.")

    async def record(sid, counts):
        pass

    gateway = Gateway(config, record)
    print(f"Backend: {config.gemini_backend}; model: {config.gemini_model}")
    try:
        try:
            await gateway.headers()
            print("Authentication: passed")
        except GoogleAuthError:
            raise SystemExit(
                "Google Cloud credentials unavailable. Run gcloud auth application-default login, "
                "or configure GOOGLE_APPLICATION_CREDENTIALS with a service-account JSON file."
            ) from None
        result = await gateway.decide("smoke-test", {"profile": {"name": "Example"}})
        if result is None:
            print(f"Safe diagnostics: {gateway.last_error}")
            raise SystemExit(
                "No valid decision received. Check API enablement, IAM permissions, billing, "
                "model access and quota in your selected project. No alternate billing route was used."
            )
        print(f"Live structured decision validated: {result.action}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(main())
