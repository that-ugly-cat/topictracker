"""
Authentication for TopicTracker.

Two modes, chosen at runtime, and `local` is the default on purpose:

    AUTH_MODE=local     (default)   email + password against the users table
    AUTH_MODE=gateway               an upstream SSO gate vouches via X-Borant-*

`local` is not negotiable as the default. An app that believes an identity
header with no gate in front of it lets anyone be anyone, so the gateway path
is dead code until someone turns it on deliberately. The app must also keep
working with no gate anywhere: someone will deploy this elsewhere.

Strategy in `local`: JWT stored in an httpOnly cookie named 'session'.
- Token lifetime: 7 days (renewed on login only).
- Secret key via JWT_SECRET env var; startup crashes if missing.
- is_admin flag on User for admin-only routes.
"""
import ipaddress
import logging
import os
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from models import User, get_db

log = logging.getLogger("topictracker.auth")

SECRET_KEY  = os.environ["JWT_SECRET"]
ALGORITHM   = "HS256"
EXPIRE_DAYS = 7

AUTH_MODE = os.environ.get("AUTH_MODE", "local").strip().lower()

# In gateway mode the identity headers are believed only from here — the
# reverse proxy, never the internet. Under Docker this is a bridge gateway and
# NOT 127.0.0.1: read the real value off the running container's log after a
# real request rather than deducing it from the network layout.
TRUSTED_PROXY = os.environ.get("BORANT_TRUSTED_PROXY", "127.0.0.1")
BORANT_LOGOUT_URL = os.environ.get("BORANT_LOGOUT_URL", "https://id.borant.eu/logout")


def _parse_trusted(raw: str) -> list:
    nets = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            log.warning("BORANT_TRUSTED_PROXY: ignoring %r, not an address or CIDR", chunk)
    return nets


TRUSTED_PROXIES = _parse_trusted(TRUSTED_PROXY)


def gateway_mode() -> bool:
    return AUTH_MODE == "gateway"


def _from_trusted_proxy(request: Request) -> bool:
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_PROXIES)


def user_from_gateway(request: Request, db: Session) -> User | None:
    """The user the gate vouched for, or None.

    Lookup is by `borant_sub` and never by email: a typo in the gate's admin
    panel must not hand one person another person's runs. An unknown subject
    gets a fresh profile that owns nothing and is not an admin — here that is a
    harmless outcome, because a user with no runs sees an empty list rather
    than someone else's. `map_borant.py` does the linking once, by hand, and
    prints what it did.
    """
    if not gateway_mode():
        return None
    sub = request.headers.get("x-borant-sub")
    if not sub:
        return None
    if not _from_trusted_proxy(request):
        log.warning("X-Borant-Sub from %s, outside BORANT_TRUSTED_PROXY (%s): ignored",
                    request.client.host if request.client else "?", TRUSTED_PROXY)
        return None

    user = db.query(User).filter(User.borant_sub == sub).first()
    if user is not None:
        return user if user.is_active else None

    email = (request.headers.get("x-borant-email", "") or f"{sub}@borant.invalid").strip().lower()
    taken = db.query(User).filter(User.email == email).first()
    if taken is not None:
        # Qualcuno con questo indirizzo c'e' gia', e non e' legato. NON si
        # adotta quella riga: agganciare per email a runtime e' esattamente
        # cio' che map_borant.py esiste per tenere manuale, e quella riga puo'
        # essere quella dell'admin. Si fallisce chiusi, dicendo cosa lanciare.
        log.error("gateway: %s arrives as %s, but a local row already holds that "
                  "address and has no borant_sub. Run "
                  "`python map_borant.py --map %s=%s` instead of letting the gate guess.",
                  email, sub, email, sub)
        return None

    # Una password locale che non conosce nessuno, invece di nessuna password:
    # AUTH_MODE=local deve restare una strada di ritorno, e una riga senza
    # password utilizzabile non lo e'. L'admin puo' resettarla dal pannello.
    # L'hint del gate puo' proporre `admin`, e da oggi viene onorato.
    #
    # Qui `is_admin` apre la gestione degli utenti — disattivare, resettare
    # password e secondo fattore — e non le funzioni del prodotto, che sono
    # aperte a chiunque abbia un grant. La deroga alla regola «mai provisionare
    # privilegio da un header» regge sul solito presupposto: la registrazione
    # aperta su Borant ID e' spenta, e anche una richiesta d'accesso fa
    # scegliere il ruolo all'amministratore approvando, quindi `admin` in
    # quell'header c'e' solo perche' un umano l'ha digitato.
    #
    # Un hint non conosciuto e' un refuso, non un ruolo, e non concede niente.
    hint = (request.headers.get("x-borant-hint", "") or "").strip().lower()
    fa_admin = hint == "admin"
    if hint and not fa_admin:
        log.warning("gateway: hint %r non e' un ruolo di questa app, ignorato", hint)
    if fa_admin:
        log.warning("gateway: %s (%s) creato come ADMIN su suggerimento del gate. "
                    "Quel ruolo gestisce gli utenti di questa app. Revocare da "
                    "/admin se non era voluto.", email, sub)
    user = User(email=email,
                name=request.headers.get("x-borant-name", "").strip() or email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                borant_sub=sub, is_active=True, is_admin=fa_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("gateway: new profile for %s (%s), admin=%s", email, sub, fa_admin)
    return user


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def get_current_user(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if gateway_mode():
        # L'header vince sul cookie locale, sempre, e non c'e' ripiego: un
        # cookie rimasto in giro non deve sopravvivere a una sessione che il
        # gate ha revocato.
        user = user_from_gateway(request, db)
        if user is not None:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = _decode_token(session)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_user_or_none(session: str | None, db: Session,
                     request: Request | None = None) -> User | None:
    """Funzione semplice (non una Depends) per le pagine che rendono anche da
    sloggati. In `gateway` serve la request, perche' l'identita' sta negli
    header e non nel cookie."""
    if gateway_mode():
        return user_from_gateway(request, db) if request is not None else None
    if not session:
        return None
    try:
        user_id = _decode_token(session)
    except HTTPException:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
