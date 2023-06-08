"""
HOW TO USE:
`python deserialize.py <region> <import_path> <export_path>`

REQUIRED DEPENDENCIES:
- UnityPy
"""

import sys
import os
import json

import UnityPy
import UnityPy.config


def open_textasset(import_path, export_path):
    env = UnityPy.load(import_path)
    for obj in env.objects:
        if obj.type.name in ["TextAsset"]:
            data = obj.read()
            with open(export_path, "wb") as f:
                f.write(bytes(data.script))
                print('<DESERIALIZE>', f"({obj.type.name})", import_path, '->', export_path)

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print('Not enough arguments.')
        sys.exit()

    # change FALLBACK_UNITY_VERSION if needed
    UnityPy.config.FALLBACK_VERSION_WARNED = True
    with open(f"{os.getcwd()}/src/unity.json") as f:
        data = json.load(f)
        if sys.argv[1] in data:
            UnityPy.config.FALLBACK_UNITY_VERSION = data[sys.argv[1]]
            print(f"<UnityPy> Using Unity version {UnityPy.config.FALLBACK_UNITY_VERSION}...")

    open_textasset(sys.argv[2], sys.argv[3])
