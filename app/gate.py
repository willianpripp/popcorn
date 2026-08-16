# The front door for visitors who are not on the tailnet.
#
# Copied from the family-calendar's app/gate.py (2026-08-15) and kept
# BYTE-COMPATIBLE with it on purpose: same cookie name, same HMAC format,
# same password scheme. GATE_SECRET and GATE_USERS in this app's .env carry
# THE SAME VALUES as the calendar's CAL_GATE_SECRET / CAL_GATE_USERS, and all
# the household apps share one public hostname, so logging into any of them
# logs you into all of them. Rotating the secret or a password now means
# updating every app's .env; that is the accepted cost of one-login
# (Willian, 2026-08-15).
#
# The trust rule: authenticate only where the trust boundary actually is.
# Visitors arriving over the VPN or from the home LAN are never asked; only a
# request whose real client address is public needs a session. Deciding *who*
# somebody is, for labelling rows and choosing their pictures, is a separate
# concern from deciding whether the request gets in at all. The two must not
# be merged: one is cosmetic, the other is the boundary.
#
# Who the real client is takes care, because X-Forwarded-For is a list that
# anyone can seed. The chain here is at most: forged entries from the visitor,
# then the address tailscale serve actually saw, then the loopback/docker hops
# calgate and the container runtime add. So the address is read from the RIGHT,
# skipping the on-host proxy hops (loopback, the docker nets); the first entry
# that is not one of those is what the nearest trusted proxy observed. Entries
# further left are hearsay and are never consulted. A funnel visitor claiming
# "100.100.1.1" in a forged header still presents a public address in the
# position that counts, and stays outside.
#
# Sessions are an HMAC-signed cookie (stdlib only, same "right size of
# machinery" rule as the rest of the app): user, expiry, signature. Passwords
# are pbkdf2 hashes in the host .env, never in git. Run
#   python gate.py 'the-password'
# to mint a hash for GATE_USERS. Unconfigured means fail CLOSED for public
# visitors: the tailnet never notices, the funnel gets told to configure it.

import hashlib
import hmac
import ipaddress
import os
import time

# "cal_gate", not "gro_gate": the SHARED cookie is the whole single-login
# mechanism. Renaming it here would silently break SSO with the calendar.
COOKIE = "cal_gate"
SESSION_DAYS = 60

# The proxy hops that can legitimately sit between a client and the app on
# this host: loopback (tailscaled, calgate) and the docker bridge nets. These
# are skipped when reading the forwarded chain from the right. The LAN net is
# deliberately NOT here: a 192.168.x peer is a real visitor (trusted, below),
# not a hop to look past.
def _is_proxy_hop(ip) -> bool:
    return ip.is_loopback or ip in ipaddress.ip_network("172.16.0.0/12")


# Trusted without a login: the tailnet (Tailscale's CGNAT range and its IPv6
# ULA), the RFC1918 LAN ranges, and the host itself. Spelled out rather than
# leaning on ipaddress.is_private, because is_private also says yes to the
# documentation and reserved ranges, which are not addresses this boundary
# has any reason to wave through. A public source can never arrive with one of
# these, because the funnel path always presents the address tailscale serve
# observed.
_TRUSTED_NETS = [ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",          # tailnet
    "fd7a:115c:a1e0::/48",    # tailnet IPv6
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",  # RFC1918 LAN
    "fc00::/7",               # IPv6 ULA LAN
)]


def _is_trusted(ip) -> bool:
    return ip.is_loopback or any(ip in net for net in _TRUSTED_NETS)


def real_client(request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The nearest address a proxy we run actually observed."""
    chain = []
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        chain = [p.strip() for p in fwd.split(",") if p.strip()]
    if request.client:
        chain.append(request.client.host)
    for entry in reversed(chain):
        try:
            ip = ipaddress.ip_address(entry)
        except ValueError:
            return None  # a malformed chain is nobody's friend: treat as public
        if _is_proxy_hop(ip):
            continue
        return ip
    # Every hop was one of ours (a host-local curl): that is the host itself.
    return ipaddress.ip_address("127.0.0.1")


def trusted(request) -> bool:
    ip = real_client(request)
    return ip is not None and _is_trusted(ip)


# --- sessions -------------------------------------------------------------------


def _secret() -> bytes:
    return os.environ.get("GATE_SECRET", "").strip().encode()


def _users() -> dict[str, str]:
    """GATE_USERS="willian=pbkdf2:600000:<salt>:<hash>,aline=..." """
    out = {}
    for entry in os.environ.get("GATE_USERS", "").split(","):
        entry = entry.strip()
        if "=" not in entry:
            continue
        name, _, stored = entry.partition("=")
        out[name.strip().lower()] = stored.strip()
    return out


def configured() -> bool:
    return bool(_secret()) and bool(_users())


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def mint(user: str) -> str:
    expires = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{user}:{expires}"
    return f"{payload}:{_sign(payload)}"


def session_user(request) -> str | None:
    """The logged-in user from the cookie, or None. Wrong signature, expired,
    or an unknown user all read the same way: not logged in."""
    if not configured():
        return None
    raw = request.cookies.get(COOKIE, "")
    parts = raw.rsplit(":", 1)
    if len(parts) != 2:
        return None
    payload, sig = parts
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    user, _, expires = payload.partition(":")
    try:
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    return user if user in _users() else None


def check_password(user: str, password: str) -> bool:
    stored = _users().get(user.strip().lower(), "")
    try:
        scheme, iters, salt_hex, hash_hex = stored.split(":")
        if scheme != "pbkdf2":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(derived.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{derived.hex()}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python gate.py 'the-password'  -> a hash for GATE_USERS")
        raise SystemExit(2)
    print(hash_password(sys.argv[1]))
