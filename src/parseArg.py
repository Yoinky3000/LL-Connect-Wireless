import argparse
import re
from datetime import datetime

from models import VersionInfo

def extractVersion(raw_tag: str, release_note: str | None = None, installer_url: str | None = None):
    release_num = 1
    rc_num = 0
    
    semver_match = re.match(r'^(\d+\.\d+(?:\.\d+)?)', raw_tag)
    if semver_match:
        version_base = semver_match.group(1)
    else:
        version_base = "0.0.0"

    rel_match = re.search(r'-rel(\d+)', raw_tag)
    if rel_match:
        release_num = int(rel_match.group(1))

    rc_match = re.search(r'-rc(\d+)', raw_tag)
    if rc_match:
        rc_num = int(rc_match.group(1))
        version_attr = f"{version_base}~rc{rc_num}"
    else:
        version_attr = version_base
    return VersionInfo(semver=version_base, rc=rc_num, release=release_num, compile_ver=version_attr, raw_tag=raw_tag, release_note=release_note, installer_url=installer_url)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--releaseVer", type=str, default=datetime.now().strftime("%Y%m%d.%H%M.%M%S"))
    args, unknown = parser.parse_known_args()

    raw_tag = args.releaseVer

    ver = extractVersion(raw_tag)
    print(ver)

    print(f"export COMPILE_VER='{ver.compile_ver}'")
    print(f"export VERSION='{ver.semver}'")
    print(f"export RELEASE='{ver.release}'")
    print(f"export RC='{ver.rc}'")
    print(f"export RAW_VERSION='{raw_tag}'")

if __name__ == "__main__":
    main()