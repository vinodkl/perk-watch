"""Ask a question about prepared PerkWatch data."""
import argparse

from perk_watch.app import answer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("question", nargs="+", help="question about your card benefits")
args = parser.parse_args()
try:
    print(answer(" ".join(args.question)))
except (FileNotFoundError, RuntimeError) as exc:
    parser.error(str(exc))
