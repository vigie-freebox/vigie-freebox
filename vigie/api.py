"""Client minimal de l'API locale Freebox OS (https://dev.freebox.fr/sdk/os/).

L'application s'enregistre une seule fois auprès de la Freebox : l'abonné valide
la demande sur l'écran (ou le bouton) de la Freebox Server. Le jeton obtenu est
ensuite conservé dans le fichier de configuration local.
"""

from __future__ import annotations

import hashlib
import hmac
import platform
import socket

import requests

from . import APP_ID, APP_NAME, __version__


class FreeboxError(Exception):
    """Erreur renvoyée par la Freebox (ou réseau indisponible)."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class AuthRequired(FreeboxError):
    pass


class PermissionMissing(FreeboxError):
    pass


class FreeboxAPI:
    def __init__(self, base_url: str = "http://mafreebox.freebox.fr", app_token: str | None = None,
                 timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token
        self.timeout = timeout
        self.session_token: str | None = None
        self.permissions: dict = {}
        self.api_prefix: str | None = None
        self.box_info: dict = {}
        self.http = requests.Session()

    # ------------------------------------------------------------------ bas niveau
    def discover(self) -> dict:
        try:
            r = self.http.get(self.base_url + "/api_version", timeout=self.timeout)
            info = r.json()
        except (requests.RequestException, ValueError) as e:
            raise FreeboxError(f"Freebox introuvable à {self.base_url} ({e})", "unreachable") from e
        major = str(info.get("api_version", "8")).split(".")[0]
        base = info.get("api_base_url", "/api/")
        self.api_prefix = f"{base.rstrip('/')}/v{major}"
        self.box_info = info
        return info

    def _url(self, path: str) -> str:
        if self.api_prefix is None:
            self.discover()
        return self.base_url + self.api_prefix + path

    def _raw(self, method: str, path: str, payload=None, auth: bool = True):
        headers = {}
        if auth and self.session_token:
            headers["X-Fbx-App-Auth"] = self.session_token
        try:
            r = self.http.request(method, self._url(path), json=payload, headers=headers, timeout=self.timeout)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise FreeboxError(f"Freebox injoignable ({e})", "unreachable") from e
        if not body.get("success"):
            code = body.get("error_code")
            msg = body.get("msg") or code or "erreur inconnue"
            if code in ("auth_required", "invalid_session"):
                raise AuthRequired(msg, code)
            if code == "insufficient_rights":
                raise PermissionMissing(msg, code)
            raise FreeboxError(msg, code)
        return body.get("result")

    def post_form(self, path: str, form: dict):
        """POST encodé application/x-www-form-urlencoded (exigé par /downloads/add)."""
        headers = {"X-Fbx-App-Auth": self.session_token} if self.session_token else {}
        for attempt in (1, 2):
            try:
                r = self.http.post(self._url(path), data=form, headers=headers, timeout=self.timeout)
                body = r.json()
            except (requests.RequestException, ValueError) as e:
                raise FreeboxError(f"Freebox injoignable ({e})", "unreachable") from e
            if body.get("success"):
                return body.get("result")
            code = body.get("error_code")
            if code in ("auth_required", "invalid_session") and attempt == 1:
                self.login()
                headers = {"X-Fbx-App-Auth": self.session_token}
                continue
            if code == "insufficient_rights":
                raise PermissionMissing(body.get("msg") or code, code)
            raise FreeboxError(body.get("msg") or code or "erreur inconnue", code)

    def call(self, method: str, path: str, payload=None):
        """Appel authentifié ; rouvre la session une fois si elle a expiré."""
        try:
            return self._raw(method, path, payload)
        except AuthRequired:
            self.login()
            return self._raw(method, path, payload)

    def get(self, path: str):
        return self.call("GET", path)

    # ------------------------------------------------------------------ autorisation
    def request_authorization(self) -> tuple[str, int]:
        device = socket.gethostname() or platform.node() or "ordinateur"
        res = self._raw("POST", "/login/authorize/", {
            "app_id": APP_ID,
            "app_name": APP_NAME,
            "app_version": __version__,
            "device_name": device[:60],
        }, auth=False)
        self.app_token = res["app_token"]
        return res["app_token"], res["track_id"]

    def authorization_status(self, track_id: int) -> str:
        """unknown | pending | timeout | granted | denied"""
        return self._raw("GET", f"/login/authorize/{track_id}", auth=False).get("status", "unknown")

    def login(self) -> dict:
        if not self.app_token:
            raise AuthRequired("Application pas encore autorisée sur la Freebox", "no_token")
        challenge = self._raw("GET", "/login/", auth=False)["challenge"]
        password = hmac.new(self.app_token.encode(), challenge.encode(), hashlib.sha1).hexdigest()
        res = self._raw("POST", "/login/session/", {"app_id": APP_ID, "password": password}, auth=False)
        self.session_token = res["session_token"]
        self.permissions = res.get("permissions", {})
        return res
