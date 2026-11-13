"""Opt-in control-plane deletion of one explicitly selected sample container."""

import argparse
import logging

from container_setup import CONTAINERS, az_json

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subscription", "resource-group", "account", "database"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--container", required=True, choices=list(CONTAINERS))
    parser.add_argument("--confirm-delete", help="Must equal ACCOUNT/DATABASE/CONTAINER.")
    args = parser.parse_args(argv)
    confirmation = f"{args.account}/{args.database}/{args.container}"
    if args.confirm_delete is None:
        print("Dry run only. No Azure calls made. Deletion requires --confirm-delete "
              "ACCOUNT/DATABASE/CONTAINER matching the explicit target.")
        return 0
    if args.confirm_delete != confirmation:
        print("Confirmation mismatch. Nothing deleted.")
        return 1
    try:
        az_json("cosmosdb", "sql", "container", "delete",
                "--subscription", args.subscription, "--resource-group", args.resource_group,
                "--account-name", args.account, "--database-name", args.database,
                "--name", args.container, "--yes")
        print("Selected sample container deleted.")
        return 0
    except Exception:
        logger.exception("Container deletion failed.")
        print("Deletion failed. Check the explicit target and control-plane permissions.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
