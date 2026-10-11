"""Run the fake S3 store: `python -m fake_s3`."""

import uvicorn

from fake_s3.app import create_app

HOST = "0.0.0.0"  # in a container: reachable through its Service
PORT = 8000


def main() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
