import os
import sys
import io
import json

if sys.platform == "win32":
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

def setup_profile_templates():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profiles_dir = os.path.join(base_dir, "data", "profiles")
    os.makedirs(profiles_dir, exist_ok=True)

    templates = {
        "opera_home": {
            "description": "Opera GX profile using direct home connection (no proxy).",
            "prefs": {
                "vpn": {"enabled": False}
            }
        },
        "opera_vpn": {
            "description": "Opera GX profile pre-configured with Opera's built-in free VPN.",
            "prefs": {
                "vpn": {
                    "enabled": True,
                    "last_established": True
                },
                "sec_vpn": {
                    "enabled": True
                }
            }
        },
        "edge_home": {
            "description": "Microsoft Edge profile using direct home connection.",
            "prefs": {}
        },
        "edge_proxy": {
            "description": "Microsoft Edge profile ready for a local proxy or VPN endpoint (e.g. Cloudflare WARP or SOCKS5).",
            "prefs": {}
        }
    }

    for name, info in templates.items():
        p_dir = os.path.join(profiles_dir, name)
        default_dir = os.path.join(p_dir, "Default")
        os.makedirs(default_dir, exist_ok=True)

        # Write readme in profile
        readme_path = os.path.join(p_dir, "PROFILE_INFO.txt")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(f"Profile: {name}\nDescription: {info['description']}\n")

        # Write Default/Preferences
        prefs_path = os.path.join(default_dir, "Preferences")
        if not os.path.exists(prefs_path):
            with open(prefs_path, "w", encoding="utf-8") as f:
                json.dump(info["prefs"], f, indent=2)

    print(f"✅ Successfully initialized {len(templates)} profile templates in: {profiles_dir}")

if __name__ == "__main__":
    setup_profile_templates()
