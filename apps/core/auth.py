import logging
import os
import secrets
import threading
import time
import uuid

try:
    import ssl

    from ldap3 import ALL, SIMPLE, Connection, Server, Tls
    from ldap3.core.exceptions import LDAPException

    LDAP3_AVAILABLE = True
except ImportError:
    LDAP3_AVAILABLE = False
    ssl = None
    Tls = None


logger = logging.getLogger("hcc.auth")

AUTH_ENABLED = os.environ.get("HCC_AUTH_ENABLED", "true").lower() not in {"0", "false", "no"}
AUTH_SECRET = os.environ.get("HCC_AUTH_SECRET", "change-me-in-production")
SESSION_TTL_SECONDS = int(os.environ.get("HCC_SESSION_TTL_SECONDS", str(12 * 3600)))
WEB_ORIGIN = os.environ.get("HCC_WEB_ORIGIN", "http://192.168.4.237:3000")
WEB_ORIGINS = [item.strip().rstrip("/") for item in WEB_ORIGIN.split(",") if item.strip()]

LDAP_SERVER = os.environ.get("HCC_LDAP_SERVER", "ldap://192.168.4.100")
LDAP_BASE_DN = os.environ.get("HCC_LDAP_BASE_DN", "DC=web-flip,DC=local")
LDAP_DOMAIN = os.environ.get("HCC_LDAP_DOMAIN", "web-flip.local")
LDAP_NETBIOS = os.environ.get("HCC_LDAP_NETBIOS", "WEB-FLIP")
LDAP_USE_TLS = os.environ.get("HCC_LDAP_USE_TLS", "false").lower() in {"1", "true", "yes"}
LDAP_BIND_USER = os.environ.get("HCC_LDAP_BIND_USER", "")
LDAP_BIND_PASSWORD = os.environ.get("HCC_LDAP_BIND_PASSWORD", "")

AD_BIND_SUBCODE_MESSAGES = {
    "525": "Active Directory does not recognize that username.",
    "52e": "Active Directory rejected the username or password.",
    "530": "This account is not allowed to sign in at this time.",
    "531": "This account is not allowed to sign in from this location.",
    "532": "The password has expired.",
    "533": "This account is disabled.",
    "701": "This account has expired.",
    "773": "The password must be changed before signing in.",
    "775": "This account is locked out.",
}

LOCAL_ADMIN_USER = os.environ.get("HCC_LOCAL_ADMIN_USER", "hccadmin")
LOCAL_ADMIN_PASSWORD = os.environ.get("HCC_LOCAL_ADMIN_PASSWORD", "")

AD_GROUP_ROLES = {
    "HCC-Agent-Observers": "observer",
    "HCC-Agent-Operators": "operator",
    "HCC-Agent-Maintainers": "maintainer",
    "HCC-Agent-Deployers": "deployer",
}

ROLE_RANK = {
    "observer": 1,
    "operator": 2,
    "maintainer": 3,
    "deployer": 4,
}

PUBLIC_GET_PATHS = {
    "/healthz",
    "/api/v1/dashboard/overview",
    "/api/v1/fleet/overview",
    "/api/v1/fleet/vms",
    "/api/v1/fleet/containers",
    "/api/v1/integrations/weather",
    "/api/v1/integrations/security",
    "/api/v1/integrations/climate",
    "/api/v1/integrations/network",
    "/api/v1/system/version",
}
PUBLIC_POST_PATHS = {"/api/v1/auth/login", "/api/v1/agent/heartbeat", "/api/v1/agent/action-result"}
PUBLIC_FRIGATE_CAMERA_PREFIX = "/api/v1/integrations/frigate/camera/"

_sessions = {}
_sessions_lock = threading.Lock()


def auth_status():
    return {
        "enabled": AUTH_ENABLED,
        "ldapConfigured": bool(LDAP_SERVER and LDAP3_AVAILABLE),
        "ldapLookupConfigured": bool(LDAP_BIND_USER and LDAP_BIND_PASSWORD),
        "localAdminConfigured": bool(LOCAL_ADMIN_USER and LOCAL_ADMIN_PASSWORD),
        "webOrigin": WEB_ORIGIN,
        "webOrigins": WEB_ORIGINS,
        "ldapServer": LDAP_SERVER,
    }


def cors_origin_for(request_origin):
    normalized = (request_origin or "").strip().rstrip("/")
    if normalized in WEB_ORIGINS:
        return normalized
    if WEB_ORIGINS:
        return WEB_ORIGINS[0]
    return normalized or WEB_ORIGIN


def normalize_username(username):
    value = str(username or "").strip()
    if not value:
        return ""
    if "\\" in value:
        domain, account = value.split("\\", 1)
        if domain.upper() == LDAP_NETBIOS.upper():
            return account.strip()
        return account.strip()
    if "@" in value:
        account, domain = value.split("@", 1)
        if domain.lower() == LDAP_DOMAIN.lower():
            return account.strip()
        return account.strip()
    return value


def principal_name(username):
    account = normalize_username(username)
    return f"{LDAP_NETBIOS}\\{account}"


def highest_role(roles):
    best = "observer"
    best_rank = 0
    for role in roles:
        rank = ROLE_RANK.get(role, 0)
        if rank > best_rank:
            best = role
            best_rank = rank
    return best


def roles_from_groups(group_names):
    roles = set()
    for name in group_names:
        role = AD_GROUP_ROLES.get(name)
        if role:
            roles.add(role)
    if not roles:
        return set()
    return roles


def user_has_role(user, min_role):
    if not user:
        return False
    if user.get("isLocalAdmin"):
        return True
    role = user.get("role") or "observer"
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(min_role, 99)


def action_required_role(action_id):
    action_id = str(action_id or "")
    if action_id.startswith("software."):
        return "deployer"
    if action_id.startswith("agent."):
        return "maintainer"
    if action_id.startswith("host."):
        return "maintainer"
    if action_id.startswith("service.") or action_id.startswith("vm.") or action_id.startswith("container."):
        return "operator"
    return "operator"


def user_may_execute_action(user, action_id):
    if not user:
        return False
    if user.get("isLocalAdmin"):
        return True
    required = action_required_role(action_id)
    return user_has_role(user, required)


def route_required_role(method, path):
    if method == "GET" and path in PUBLIC_GET_PATHS:
        return None
    if method == "GET" and path.startswith(PUBLIC_FRIGATE_CAMERA_PREFIX) and path.endswith("/latest.jpg"):
        return None
    if method == "POST" and path in PUBLIC_POST_PATHS:
        return None
    if path == "/api/v1/auth/logout":
        return None
    if path == "/api/v1/auth/me":
        return "observer"
    if path.startswith("/api/v1/admin/"):
        return "maintainer"
    if path == "/api/v1/actions/execute" and method == "POST":
        return "operator"
    if path == "/api/v1/integrations/climate/set" and method == "POST":
        return "operator"
    if path.startswith("/api/v1/"):
        return "observer"
    return "observer"


def _local_admin_user():
    if not LOCAL_ADMIN_USER or not LOCAL_ADMIN_PASSWORD:
        return None
    return {
        "username": LOCAL_ADMIN_USER,
        "principal": f"local\\{LOCAL_ADMIN_USER}",
        "displayName": "Local Break-Glass Admin",
        "authSource": "local",
        "isLocalAdmin": True,
        "groups": ["HCC-Local-Admins"],
        "roles": list(ROLE_RANK.keys()),
        "role": "deployer",
    }


def authenticate_local(username, password):
    admin = _local_admin_user()
    if not admin:
        return None
    if normalize_username(username) != LOCAL_ADMIN_USER:
        return None
    if not secrets.compare_digest(password or "", LOCAL_ADMIN_PASSWORD):
        return None
    return dict(admin)


def _escape_ldap_filter(value):
    value = str(value or "")
    return (
        value.replace("\\", "\\5c")
        .replace("*", "\\2a")
        .replace("(", "\\28")
        .replace(")", "\\29")
        .replace("\x00", "\\00")
    )


def _parse_ad_bind_subcode(result):
    message = str((result or {}).get("message") or "")
    if "data " not in message:
        return None
    return message.split("data ")[-1].split(",")[0].strip().lower()


def _ldap_host():
    uri = LDAP_SERVER.strip()
    host = uri
    for prefix in ("ldap://", "ldaps://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
            break
    return host.split("/", 1)[0]


def _ldap_server_candidates():
    if not LDAP3_AVAILABLE:
        return []
    host = _ldap_host()
    tls = Tls(validate=ssl.CERT_NONE)
    candidates = [
        {
            "label": "ldap",
            "server": Server(f"ldap://{host}", get_info=ALL, connect_timeout=10),
            "start_tls": False,
        },
        {
            "label": "ldap+starttls",
            "server": Server(f"ldap://{host}", get_info=ALL, connect_timeout=10, tls=tls),
            "start_tls": True,
        },
        {
            "label": "ldaps",
            "server": Server(f"ldaps://{host}", get_info=ALL, connect_timeout=10, tls=tls),
            "start_tls": False,
        },
    ]
    if LDAP_USE_TLS or LDAP_SERVER.startswith("ldaps://"):
        preferred = [item for item in candidates if item["label"] != "ldap"]
        fallback = [item for item in candidates if item["label"] == "ldap"]
        return preferred + fallback
    return candidates


def _ldap_server():
    candidates = _ldap_server_candidates()
    if candidates:
        return candidates[0]["server"]
    return Server(LDAP_SERVER, get_info=ALL, connect_timeout=10)


def _dedupe_bind_identities(identities):
    seen = set()
    ordered = []
    for item in identities:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _bind_identities(raw_username, sam, lookup=None):
    identities = []
    raw = str(raw_username or "").strip()
    if "@" in raw and "\\" not in raw:
        identities.append(raw)
    if lookup:
        upn = str(lookup.get("upn") or "").strip()
        if upn:
            identities.append(upn)
        dn = str(lookup.get("dn") or "").strip()
        if dn:
            identities.append(dn)
    identities.append(f"{sam}@{LDAP_DOMAIN}")
    identities.append(f"{LDAP_NETBIOS}\\{sam}")
    return _dedupe_bind_identities(identities)


def _ldap_lookup_account(server, sam):
    if not LDAP_BIND_USER or not LDAP_BIND_PASSWORD:
        return None
    conn, _subcode = _try_ldap_bind(
        server,
        LDAP_BIND_USER,
        LDAP_BIND_PASSWORD,
        SIMPLE,
        start_tls=LDAP_USE_TLS or LDAP_SERVER.startswith("ldaps://"),
        mode_label="lookup",
    )
    if not conn:
        logger.warning("ldap lookup bind failed for service account %s", LDAP_BIND_USER)
        return None
    try:
        safe_sam = _escape_ldap_filter(sam)
        conn.search(
            search_base=LDAP_BASE_DN,
            search_filter=f"(sAMAccountName={safe_sam})",
            attributes=["distinguishedName", "userPrincipalName", "displayName"],
            size_limit=1,
        )
        if not conn.entries:
            logger.info("ldap lookup found no account for sAMAccountName=%s", sam)
            return None
        entry = conn.entries[0]
        return {
            "dn": str(entry.entry_dn),
            "upn": str(getattr(entry, "userPrincipalName", "") or ""),
            "displayName": str(getattr(entry, "displayName", sam) or sam),
        }
    finally:
        conn.unbind()


def _group_names_from_member_of(raw_groups):
    names = set()
    if not raw_groups:
        return names
    values = raw_groups.values if hasattr(raw_groups, "values") else raw_groups
    for dn in values:
        cn = str(dn).split(",", 1)[0]
        if cn.upper().startswith("CN="):
            names.add(cn[3:])
    return names


def _ldap_user_profile(conn, sam_account):
    safe_sam = _escape_ldap_filter(sam_account)
    conn.search(
        search_base=LDAP_BASE_DN,
        search_filter=f"(sAMAccountName={safe_sam})",
        attributes=["distinguishedName", "displayName", "memberOf"],
        size_limit=1,
    )
    if not conn.entries:
        return None, None, set()
    entry = conn.entries[0]
    user_dn = str(entry.entry_dn)
    display_name = str(getattr(entry, "displayName", sam_account) or sam_account)
    member_of = _group_names_from_member_of(getattr(entry, "memberOf", None))
    return user_dn, display_name, member_of


def _ldap_groups_for_user(conn, user_dn):
    groups = set()
    safe_dn = user_dn.replace("\\", "\\5c")
    for group_name in AD_GROUP_ROLES:
        safe_group = _escape_ldap_filter(group_name)
        conn.search(
            search_base=LDAP_BASE_DN,
            search_filter=(
                "(&(objectClass=group)(sAMAccountName="
                + safe_group
                + ")(member:1.2.840.113556.1.4.1941:="
                + safe_dn
                + "))"
            ),
            attributes=["sAMAccountName"],
            size_limit=1,
        )
        if conn.entries:
            groups.add(group_name)
    return groups


def _try_ldap_bind(server, bind_user, password, authentication, start_tls=False, mode_label="ldap"):
    conn = Connection(
        server,
        user=bind_user,
        password=password,
        authentication=authentication,
        auto_bind=False,
        auto_referrals=False,
        receive_timeout=10,
    )
    try:
        conn.open()
        if start_tls:
            if not conn.start_tls():
                subcode = _parse_ad_bind_subcode(conn.result)
                logger.info(
                    "ldap start_tls failed for %s via %s: %s (subcode=%s)",
                    bind_user,
                    mode_label,
                    conn.result.get("description"),
                    subcode or "unknown",
                )
                conn.unbind()
                return None, subcode
        if conn.bind():
            return conn, None
        subcode = _parse_ad_bind_subcode(conn.result)
        logger.info(
            "ldap bind failed for %s via %s (%s): %s (subcode=%s)",
            bind_user,
            authentication,
            mode_label,
            conn.result.get("description"),
            subcode or "unknown",
        )
    except (LDAPException, ValueError, OSError) as exc:
        logger.info("ldap bind failed for %s via %s (%s): %s", bind_user, authentication, mode_label, exc)
        subcode = None
    try:
        conn.unbind()
    except Exception:
        pass
    return None, subcode


def authenticate_ldap(username, password):
    if not LDAP3_AVAILABLE:
        return None, "ldap_unavailable"
    sam = normalize_username(username)
    if not sam or not password:
        return None, "missing_credentials"

    lookup = None
    conn = None
    last_subcode = None
    bind_mode = None
    for candidate in _ldap_server_candidates():
        server = candidate["server"]
        if lookup is None:
            lookup = _ldap_lookup_account(server, sam)
        bind_attempts = _bind_identities(username, sam, lookup)
        for bind_user in bind_attempts:
            conn, subcode = _try_ldap_bind(
                server,
                bind_user,
                password,
                SIMPLE,
                start_tls=candidate["start_tls"],
                mode_label=candidate["label"],
            )
            if conn:
                bind_mode = candidate["label"]
                logger.info("ldap bind ok for %s as %s via %s", sam, bind_user, bind_mode)
                break
            if subcode:
                last_subcode = subcode
        if conn:
            break

    if not conn:
        reason = "bind_failed"
        if last_subcode in AD_BIND_SUBCODE_MESSAGES:
            reason = f"bind_failed_{last_subcode}"
        logger.info(
            "ldap bind failed for user %s after trying %s (subcode=%s, password_len=%s)",
            sam,
            bind_attempts,
            last_subcode or "unknown",
            len(password),
        )
        return None, reason

    try:
        user_dn, display_name, member_of = _ldap_user_profile(conn, sam)
        if not user_dn and lookup and lookup.get("dn"):
            user_dn = lookup["dn"]
            display_name = lookup.get("displayName") or sam
        if not user_dn:
            logger.info("ldap user not found after bind: %s", sam)
            return None, "user_not_found"

        groups = set(member_of)
        groups.update(_ldap_groups_for_user(conn, user_dn))
        groups = {name for name in groups if name in AD_GROUP_ROLES}
        roles = roles_from_groups(groups)
        if not roles:
            logger.info("ldap user %s authenticated but lacks HCC-Agent-* groups", sam)
            return None, "missing_hcc_groups"

        role = highest_role(roles)
        return (
            {
                "username": sam,
                "principal": principal_name(sam),
                "displayName": display_name,
                "authSource": "ad",
                "isLocalAdmin": False,
                "groups": sorted(groups),
                "roles": sorted(roles, key=lambda item: ROLE_RANK.get(item, 0)),
                "role": role,
            },
            None,
        )
    finally:
        conn.unbind()


def authenticate_with_reason(username, password):
    if not AUTH_ENABLED:
        return authenticate("", ""), None

    user = authenticate_local(username, password)
    if user:
        return user, None

    ad_user, reason = authenticate_ldap(username, password)
    if ad_user:
        return ad_user, None
    return None, reason


def authenticate(username, password):
    user, _reason = authenticate_with_reason(username, password)
    return user


def login_error_message(reason):
    if reason and reason.startswith("bind_failed_"):
        subcode = reason.split("_", 2)[-1]
        if subcode in AD_BIND_SUBCODE_MESSAGES:
            return AD_BIND_SUBCODE_MESSAGES[subcode]
    messages = {
        "bind_failed": "Active Directory rejected the username or password. Try your exact UPN from Get-ADUser, not just your first name.",
        "user_not_found": "The account authenticated but could not be resolved in AD.",
        "missing_hcc_groups": "Sign-in succeeded, but this account is not in any HCC-Agent-* group.",
        "ldap_unavailable": "Active Directory login is unavailable on the core server.",
        "missing_credentials": "Username and password are required.",
    }
    return messages.get(reason, "Login failed.")


def create_session(user):
    session_id = uuid.uuid4().hex
    record = {
        "id": session_id,
        "user": dict(user),
        "createdAt": time.time(),
        "expiresAt": time.time() + SESSION_TTL_SECONDS,
    }
    with _sessions_lock:
        _sessions[session_id] = record
    return session_id


def destroy_session(session_id):
    if not session_id:
        return
    with _sessions_lock:
        _sessions.pop(session_id, None)


def get_session(session_id):
    if not session_id:
        return None
    now = time.time()
    with _sessions_lock:
        record = _sessions.get(session_id)
        if not record:
            return None
        if record["expiresAt"] <= now:
            _sessions.pop(session_id, None)
            return None
        record["expiresAt"] = now + SESSION_TTL_SECONDS
        return dict(record)


def resolve_request_user(session_id):
    if not AUTH_ENABLED:
        return authenticate("", "")
    if not session_id:
        return None
    session = get_session(session_id)
    if not session:
        return None
    return session.get("user")


def cookie_header(session_id):
    secure = os.environ.get("HCC_AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    parts = [
        f"hcc_session={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=None" if secure else "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    parts.append(f"Max-Age={SESSION_TTL_SECONDS}")
    return "; ".join(parts)


def clear_cookie_header():
    secure = os.environ.get("HCC_AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    parts = ["hcc_session=", "Path=/", "HttpOnly", "SameSite=None" if secure else "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_session_cookie(cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("hcc_session="):
            return part.split("=", 1)[1].strip()
    return None
