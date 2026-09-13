"""Enable ``python -m ston_liquidity_intelligence``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())