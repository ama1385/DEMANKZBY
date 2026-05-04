import os
import sys

# Add deps/ to sys.path so we can import arcraiders
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEPS = os.path.join(_HERE, "deps")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

try:
    from arcraiders.auth import BrowserOAuth, OAuthProvider
except ImportError:
    print("Error: Could not find 'arcraiders' package in 'deps/' folder.")
    sys.exit(1)

# Usage: python get_token.py [steam|epic|xbox|playstation]  (default: xbox)

def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "xbox").strip().lower()
    allowed = {"steam", "epic", "xbox", "playstation"}

    if arg not in allowed:
        print("Unknown provider. Use: steam, epic, xbox, or playstation")
        sys.exit(1)

    try:
        prov = {
            "steam": OAuthProvider.STEAM,
            "epic": OAuthProvider.EPIC,
            "xbox": OAuthProvider.XBOX,
            "playstation": OAuthProvider.PLAYSTATION,
        }[arg]
        print(f"Using OAuth provider: {arg}")
        auth = BrowserOAuth(prov)
        print("\nOpening browser for login...")
        print("Please complete the login process in the opened tab.")
        token = auth.token()

        print("\n" + "="*80)
        print(f"SUCCESS! Your token ({arg}):")
        print("="*80)
        print(token)
        print("="*80)

        with open("token.txt", "w") as f:
            f.write(token)
        print("\nToken has been saved to 'token.txt'.")

    except Exception as e:
        print(f"\nAn error occurred during authentication: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
