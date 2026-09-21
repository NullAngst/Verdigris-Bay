#!/usr/bin/env python3
"""Entry point. Run: python3 play.py [savefile] [--seed N]"""
import sys
import traceback

from verdigris.game import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        # A double-clicked executable closes its console window on exit, so a
        # crash would vanish unread. Hold the window open long enough to see it.
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            try:
                input("\nVerdigris Bay crashed. Press Enter to close.")
            except BaseException:
                pass
        sys.exit(1)
