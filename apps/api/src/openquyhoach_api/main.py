"""`openquyhoach-api` — uvicorn entrypoint."""

from __future__ import annotations


def main() -> None:
    import uvicorn
    from openquyhoach_core.settings import get_settings

    s = get_settings()
    uvicorn.run(
        "openquyhoach_api.app:app",
        host=getattr(s, "api_host", "0.0.0.0"),
        port=getattr(s, "api_port", 8000),
        reload=False,
    )


if __name__ == "__main__":
    main()
