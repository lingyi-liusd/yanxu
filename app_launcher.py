#!/usr/bin/env python3
"""Independent source-app launcher. Starts/reuses the shared local core automatically."""
import argparse
import os
import sys
from launcher import start


def main(app):
    parser = argparse.ArgumentParser(description='启动讨论室或雷达；无需打开研序')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    try:
        return start(args.port, not args.no_open, app)
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
