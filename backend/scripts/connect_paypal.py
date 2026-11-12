"""
Connect a Khataz account to PayPal from the terminal, and see PayPal's exact answer.
Run from the backend folder (the backend server can keep running):

    python -m scripts.connect_paypal faizan@khataz.demo

1. It prints a PayPal link. Open it, log in with the sandbox account and approve.
2. PayPal sends you to example.com. Copy that whole link from the address bar.
3. Paste it here and press Enter. Do it straight away: PayPal's code is single-use and short-lived.
"""

import re
import sys
import time
import webbrowser
from urllib.parse import unquote

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import create_purpose_token
from app.core.timeutil import utcnow
from app.models import User
from app.services import paypal
from app.services.common import audit


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    email = sys.argv[1].strip().lower()
    print(f"\nPAYPAL_ENV={settings.paypal_env}   PAYPAL_REDIRECT_URI={settings.paypal_redirect_uri}")
    print(f"Client ID starts {settings.paypal_client_id[:6]}... ends ...{settings.paypal_client_id[-4:]}\n")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if not user:
            print(f"No Khataz account with the email {email}.")
            return 1

        url = paypal.connect_url(create_purpose_token(user.id, "paypal_connect"))
        print("1) Open this link (it should open by itself), log in with the SANDBOX Personal account:\n")
        print("   " + url + "\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        link = input("2) Paste the example.com link here and press Enter:\n   ").strip()
        m = re.search(r"[?&]code=([^&#\s]+)", link)
        if not m:
            err = re.search(r"[?&]error_description=([^&#\s]+)", link)
            print("\nThat link has no code= in it." + (f" PayPal said: {unquote(err.group(1))}" if err else ""))
            return 1
        code = unquote(m.group(1))
        print(f"\n   code length {len(code)}, sending to PayPal now...")

        hosts = [paypal._api()] + (["https://api.sandbox.paypal.com"] if settings.paypal_env != "live" else ["https://api.paypal.com"])
        tries = [(h, path, True) for path in paypal.TOKEN_PATHS for h in hosts]
        tries += [(hosts[0], path, False) for path in paypal.TOKEN_PATHS]  # also without redirect_uri
        try:
            with httpx.Client(timeout=30) as c:
                r = None
                for host, path, with_redirect in tries:
                    t = time.time()
                    data = {"grant_type": "authorization_code", "code": code}
                    if with_redirect:
                        data["redirect_uri"] = settings.paypal_redirect_uri
                    try:
                        r = c.post(f"{host}{path}",
                                   auth=(settings.paypal_client_id, settings.paypal_client_secret), data=data)
                    except httpx.HTTPError as e:
                        print(f"   {host}{path} -> couldn't reach ({e.__class__.__name__})")
                        continue
                    print(f"   {host}{path}{'' if with_redirect else ' (no redirect_uri)'} -> {r.status_code} in {time.time() - t:.1f}s"
                          + ("" if r.status_code == 200 else f"  {r.text[:160]}"))
                    if r.status_code == 200:
                        break
                if r is None:
                    print("\nCouldn't reach PayPal at all. Check the internet connection.")
                    return 1
                if r.status_code != 200:
                    print("\nPayPal refused the code at every address (send these lines to Claude).")
                    print("   debug id: " + r.headers.get("paypal-debug-id", "-"))
                    return 1
                tj = r.json()
                print(f"   PayPal granted: {tj.get('scope') or '(no scope listed)'}")
                print(f"   id_token included: {'yes' if tj.get('id_token') else 'no'}")
                print("   reading the PayPal profile...")
                try:
                    info = paypal.profile_from(paypal.fetch_profile(c, r.json()))
                except paypal.PayPalError as e:
                    print("\n" + str(e))
                    print("Send Claude the lines above (from 'PayPal granted').")
                    return 1
        except httpx.HTTPError as e:
            print(f"\nCouldn't reach PayPal ({e.__class__.__name__}). Check the internet connection.")
            return 1

        pp_email, name = info["email"], info["name"]
        other = db.scalar(select(User).where(User.paypal_user_id == info["user_id"], User.id != user.id))
        if other:
            print(f"\nThis PayPal account is already connected to {other.email}. Disconnect it there first.")
            return 1
        user.paypal_user_id, user.paypal_payer_id = info["user_id"], info["payer_id"]
        user.paypal_verified_email, user.paypal_verified_name = pp_email, name
        user.paypal_account_verified = info["verified"]
        user.paypal_connected_at = utcnow()
        audit(db, user, "paypal.connected", "user", user.id, after={"email": pp_email})
        db.commit()
        print(f"\nConnected: {user.email} is now linked to PayPal {pp_email}"
              + (f" ({name})" if name else "") + ". Refresh Khataz to see it.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
