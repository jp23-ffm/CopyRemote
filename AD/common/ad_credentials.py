"""
Runtime access to the AD service account password.

The password is no longer stored in the code base. It is read from CyberArk
through the `get-cred` command and kept in memory for the life of the process.

How it works
------------
- The password is loaded lazily on first use (not at Django start-up, so a
  CyberArk outage cannot prevent the application from booting) and cached in
  RAM, per process.
- A safety TTL (AD_PASSWORD_TTL) forces a periodic refresh.
- When an LDAP bind is refused with "invalid credentials", CyberArk is queried
  once more and the bind is retried once:
    * the new password differs from the one that failed -> the password was
      rotated: log a warning and carry on with the new one;
    * the new password is identical -> this is NOT a rotation (locked account,
      wrong account, DC not yet synchronised, ...). Do not retry, and suspend
      every bind for AD_BIND_COOLDOWN seconds (circuit breaker) so failed
      attempts do not pile up and lock the service account.
- Only "invalid credentials" triggers a refresh. Network errors, timeouts, etc.
  are propagated untouched.
- The password is never logged.

Settings (see settings.py)
--------------------------
AD_GET_CRED_CMD      Arguments of the get-cred command, as a list. If empty,
                     the password is read from the LDAP_BIND_PASSWORD
                     environment variable instead (local development only).
AD_GET_CRED_TIMEOUT  Seconds before get-cred is killed (default: 10).
AD_PASSWORD_TTL      Seconds before a proactive refresh (default: 6 hours).
AD_BIND_COOLDOWN     Seconds without any bind after a non-rotation failure
                     (default: 60).

Usage
-----
    def _bind(password):
        conn = ldap.initialize(uri)
        conn.simple_bind_s(settings.LDAP_BIND_DN, password)
        return conn

    conn = with_ad_password(_bind)
"""
import logging
import os
import subprocess
import threading
import time

import ldap
from django.conf import settings

logger = logging.getLogger("common.ad_credentials")


class CredentialError(ldap.LDAPError):
    """
    The password could not be obtained (get-cred failed, timed out, ...).

    Subclasses ldap.LDAPError on purpose: existing `except ldap.LDAPError`
    handlers keep working, so the user simply cannot be verified instead of
    getting an HTTP 500 during login.
    """


class BindBlocked(ldap.LDAPError):
    """Binds are temporarily suspended to protect the service account from a lockout."""


# Process-wide state. Every access goes through _lock.
_lock = threading.Lock()
_password = None
_fetched_at = 0.0
_blocked_until = 0.0


def _reset():
    """Forget everything (used by the tests)."""
    global _password, _fetched_at, _blocked_until
    with _lock:
        _password = None
        _fetched_at = 0.0
        _blocked_until = 0.0


def _ldap_detail(exc):
    """
    Extract the diagnostic text from a python-ldap error. AD puts the reason
    there, e.g. "... data 52e" (bad password), "... data 775" (locked account),
    "... data 532" (expired password). It never contains the password.
    """
    try:
        arg = exc.args[0]
        return arg.get("info") or arg.get("desc") or ""
    except (IndexError, AttributeError):
        return ""


def _fetch():
    """Run get-cred and return the password. No shell, with a timeout."""
    cmd = getattr(settings, "AD_GET_CRED_CMD", None)

    if not cmd:
        # Development fallback: CyberArk is not reachable from a laptop or a tablet.
        password = os.environ.get("LDAP_BIND_PASSWORD", "")
        if not password:
            logger.error("AD_GET_CRED_CMD is empty and LDAP_BIND_PASSWORD is not set in the environment")
            raise CredentialError("no source configured for the AD service account password")
        logger.debug("AD password read from the LDAP_BIND_PASSWORD environment variable")
        return password

    timeout = getattr(settings, "AD_GET_CRED_TIMEOUT", 10)
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False, shell=False
        )
    except subprocess.TimeoutExpired:
        logger.error("get-cred timed out after %ss", timeout)
        raise CredentialError("get-cred timed out")
    except OSError as exc:
        logger.error("get-cred could not be started (%s)", exc.__class__.__name__)
        raise CredentialError("get-cred could not be started")

    if result.returncode != 0:
        # stdout/stderr are deliberately not logged, to be safe.
        logger.error("get-cred failed with exit code %s", result.returncode)
        raise CredentialError(f"get-cred exit code {result.returncode}")

    password = result.stdout.rstrip("\r\n")
    if not password:
        logger.error("get-cred returned an empty output")
        raise CredentialError("get-cred returned an empty output")

    logger.info("get-cred OK (%.0f ms)", (time.monotonic() - start) * 1000)
    return password


def _store(new_password, reason):
    """Update the cache (caller must hold _lock) and report a rotation if there is one."""
    global _password, _fetched_at
    if _password is not None and new_password != _password:
        logger.warning("AD service account password rotation detected (%s)", reason)
    _password = new_password
    _fetched_at = time.monotonic()


def get_password():
    """Return the cached password, (re)loading it if absent or older than the TTL."""
    ttl = getattr(settings, "AD_PASSWORD_TTL", 6 * 3600)
    with _lock:
        if _password is None or (time.monotonic() - _fetched_at) > ttl:
            reason = "first load" if _password is None else "TTL expired"
            _store(_fetch(), reason)
            logger.info("AD password loaded in memory (%s)", reason)
        return _password


def _refresh_after_failure(failed_password):
    """
    Read CyberArk again after a refused bind made with `failed_password`.
    If another thread has already refreshed the cache in the meantime, reuse
    its value instead of calling get-cred a second time.
    """
    with _lock:
        if _password != failed_password:
            logger.info("Password already refreshed by another thread, skipping get-cred")
            return _password
        new_password = _fetch()
        _store(new_password, "bind refused")
        return new_password


def _check_not_blocked():
    with _lock:
        remaining = _blocked_until - time.monotonic()
    if remaining > 0:
        raise BindBlocked(f"AD binds suspended for another {remaining:.0f}s after a failed bind")


def _block():
    """Open the circuit breaker: no AD bind until the cooldown has elapsed."""
    global _blocked_until
    cooldown = getattr(settings, "AD_BIND_COOLDOWN", 60)
    with _lock:
        _blocked_until = time.monotonic() + cooldown
    logger.warning("AD binds suspended for %ss to avoid locking the service account", cooldown)


def with_ad_password(bind_fn):
    """
    Call bind_fn(password) and return its result.

    On ldap.INVALID_CREDENTIALS, read CyberArk again and retry once (see the
    module docstring). Any other error is propagated without a retry.
    """
    _check_not_blocked()
    password = get_password()

    try:
        return bind_fn(password)
    except ldap.INVALID_CREDENTIALS as exc:
        first_error = exc
        logger.warning("AD bind refused (invalid credentials) [%s], reading CyberArk again",
                       _ldap_detail(exc))

    new_password = _refresh_after_failure(password)
    if new_password == password:
        logger.error(
            "AD bind refused and the CyberArk password is unchanged: not a rotation, "
            "no retry (locked account? wrong account?) [%s]", _ldap_detail(first_error)
        )
        _block()
        raise first_error

    try:
        result = bind_fn(new_password)
    except ldap.INVALID_CREDENTIALS as exc:
        logger.error("AD bind still refused with the new password, giving up [%s]", _ldap_detail(exc))
        _block()
        raise
    logger.info("AD bind succeeded with the new password (rotation handled)")
    return result
