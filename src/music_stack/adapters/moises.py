"""Moises adapter — the door that is actually open to an individual.

Music.AI (``adapters/music_ai.py``) is the same company's REST platform, but
its signup is enterprise-gated. Individuals reach the same engine through a
**Moises** account, and Moises speaks **GraphQL** at a single endpoint:

    POST https://api.moises.ai/graphql
    Authorization: <api-key>
    {"query": "...", "variables": {...}}

Two things this module deliberately does *not* do:

1. **Guess query shapes.** The schema sits behind a login this build could not
   read. Instead of inventing mutations, :meth:`MoisesClient.introspect` asks
   the endpoint to describe itself — GraphQL's one genuine advantage here over
   the REST API. Run it once with a real key and the real operations come back
   from the server, not from someone's blog post.

2. **Guess the auth scheme.** Sources describe "the API key in the
   authorization header" without saying whether it is bare or ``Bearer``-prefixed.
   :meth:`detect_auth_scheme` tries both against a trivial query and reports
   which one the server accepts, rather than hardcoding a coin flip.
"""

from .. import http
from ..errors import HttpError, JobError, MusicStackError

API_URL = "https://api.moises.ai/graphql"

#: The only host this adapter's credential may ever reach.
ALLOWED_HOSTS = ("moises.ai",)

#: Ways to present the key. Order matters: `detect_auth_scheme` tries in turn.
AUTH_SCHEMES = ("raw", "bearer")

#: Cheapest possible authenticated round trip — every GraphQL server answers it.
PROBE_QUERY = "{ __typename }"

#: Trimmed introspection: enough to write real queries, small enough to read.
INTROSPECTION_QUERY = """
query MusicStackIntrospection {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      name
      kind
      description
      fields {
        name
        description
        args { name type { ...TypeRef } }
        type { ...TypeRef }
      }
    }
  }
}
fragment TypeRef on __Type {
  kind
  name
  ofType { kind name ofType { kind name ofType { kind name } } }
}
"""


class MoisesClient:
    """Minimal GraphQL client for the Moises developer API."""

    def __init__(self, api_key, *, url=API_URL, transport=None, auth_scheme="raw"):
        if not api_key:
            raise ValueError("api_key is required")
        if auth_scheme not in AUTH_SCHEMES:
            raise MusicStackError(
                "Unknown auth scheme {!r}; choose one of {}".format(
                    auth_scheme, ", ".join(AUTH_SCHEMES)
                )
            )
        self._api_key = api_key
        self.url = url
        self.auth_scheme = auth_scheme
        self._t = transport or http

    # -- plumbing ---------------------------------------------------------

    def _headers(self, scheme=None):
        scheme = scheme or self.auth_scheme
        value = self._api_key if scheme == "raw" else "Bearer {}".format(self._api_key)
        return {"Authorization": value}

    def execute(self, query, variables=None, *, scheme=None):
        """Run a GraphQL operation and return its ``data``.

        GraphQL reports failures *inside a 200 response* under ``errors``, so a
        successful HTTP status proves nothing on its own. Anything in ``errors``
        is raised rather than quietly returning partial data.
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._t.api_request(
            "POST",
            self.url,
            allowed_hosts=ALLOWED_HOSTS,
            headers=self._headers(scheme),
            json_body=payload,
        )
        body = response.json()

        errors = body.get("errors")
        if errors:
            messages = "; ".join(
                str(e.get("message", e)) for e in errors if isinstance(e, dict)
            ) or str(errors)
            raise JobError("Moises GraphQL error: {}".format(messages), detail=errors)

        if "data" not in body:
            raise JobError(
                "Moises returned neither data nor errors; keys were {}".format(
                    sorted(body)
                ),
                detail=body,
            )
        return body["data"]

    # -- discovery --------------------------------------------------------

    def detect_auth_scheme(self):
        """Return whichever auth scheme the server actually accepts.

        Tries each scheme against a trivial query. Raises if none work, which
        almost always means the key itself is wrong rather than the format.
        """
        failures = []
        for scheme in AUTH_SCHEMES:
            try:
                self.execute(PROBE_QUERY, scheme=scheme)
                self.auth_scheme = scheme
                return scheme
            except (HttpError, JobError) as exc:
                failures.append("{}: {}".format(scheme, exc))
        raise JobError(
            "Moises rejected the API key under every supported auth scheme.\n"
            "  {}\n"
            "Check the key was copied whole from your developer Application "
            "page.".format("\n  ".join(failures))
        )

    def introspect(self):
        """Ask the server to describe its own schema.

        Returns ``{"queries": [...], "mutations": [...]}`` where each entry is
        ``{"name", "description", "returns", "args"}``. This is the honest
        substitute for guessing endpoint shapes.
        """
        data = self.execute(INTROSPECTION_QUERY)
        schema = data.get("__schema") or {}
        types = {t.get("name"): t for t in schema.get("types") or []}

        def operations(root_key):
            root = schema.get(root_key) or {}
            entry = types.get(root.get("name")) or {}
            out = []
            for field in entry.get("fields") or []:
                out.append(
                    {
                        "name": field.get("name"),
                        "description": (field.get("description") or "").strip(),
                        "returns": type_name(field.get("type")),
                        "args": [
                            {"name": a.get("name"), "type": type_name(a.get("type"))}
                            for a in field.get("args") or []
                        ],
                    }
                )
            return sorted(out, key=lambda f: f["name"] or "")

        return {
            "queries": operations("queryType"),
            "mutations": operations("mutationType"),
        }


def type_name(ref):
    """Flatten a GraphQL type reference into readable notation.

    ``NON_NULL(LIST(NON_NULL(String)))`` becomes ``[String!]!`` — the form you
    would actually write in a query.
    """
    if not ref:
        return "?"
    kind = ref.get("kind")
    if kind == "NON_NULL":
        return "{}!".format(type_name(ref.get("ofType")))
    if kind == "LIST":
        return "[{}]".format(type_name(ref.get("ofType")))
    return ref.get("name") or "?"


def format_schema(schema, *, contains=None):
    """Render :meth:`introspect` output as readable lines for a terminal."""
    lines = []
    for label, key in (("QUERIES", "queries"), ("MUTATIONS", "mutations")):
        items = schema.get(key) or []
        if contains:
            needle = contains.lower()
            items = [i for i in items if needle in (i["name"] or "").lower()]
        lines.append("{} ({})".format(label, len(items)))
        if not items:
            lines.append("  (none)")
        for item in items:
            args = ", ".join(
                "{}: {}".format(a["name"], a["type"]) for a in item["args"]
            )
            lines.append("  {}({}) -> {}".format(item["name"], args, item["returns"]))
            if item["description"]:
                lines.append("      {}".format(item["description"]))
        lines.append("")
    return "\n".join(lines).rstrip()
