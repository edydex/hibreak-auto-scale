#!/usr/bin/env python3
"""Cross-platform entry point for the HiBreak setup wizard."""
import sys


def main():
    try:
        if '--install-only' in sys.argv[1:]:
            from install_on_mac import main as run
            return run([arg for arg in sys.argv[1:] if arg != '--install-only'])
        from setup_on_mac import main as run
    except Exception as error:
        print('Setup cannot start. Extract the complete, unmodified kit into one folder.\n'
              + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1
    return run()

if __name__ == "__main__":
    raise SystemExit(main())
