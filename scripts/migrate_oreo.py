"""Copy legacy Oreo assets and market history into Invest Service."""

import argparse

from invest_service.migration import migrate_oreo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Oreo SQLAlchemy database URL")
    parser.add_argument("--target", required=True, help="Invest Service SQLAlchemy database URL")
    args = parser.parse_args()
    assets, bars = migrate_oreo(args.source, args.target)
    print(f"Migrated {assets} assets and {bars} market bars")


if __name__ == "__main__":
    main()
