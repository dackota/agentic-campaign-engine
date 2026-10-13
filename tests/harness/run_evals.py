"""`make evals` at fast depth: start the fast-depth stack, sign in as a Demand Gen owner, run
the golden set through the Campaign API, and stop the stack. Extra arguments go to the runner
(for example --update-baseline)."""

import os
import sys

from evals.runner import TOKEN_ENV, main
from tests.api.helpers import OWNER
from tests.harness.stack import Stack

# The database lives here between runs, so the step cache does too. `docker volume rm` it to
# start cold.
CACHE_VOLUME = "ace-evals-cache"


def run(args: list[str]) -> int:
    with Stack(data_volume=CACHE_VOLUME) as stack:
        os.environ[TOKEN_ENV] = stack.dex.token(OWNER)
        return main(["--api-url", stack.api_url, *args])


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
