"""Moises GraphQL adapter tests."""

import unittest

from fakes import FakeTransport, Sequence
from music_stack import http
from music_stack.adapters.moises import (
    AUTH_SCHEMES,
    MoisesClient,
    format_schema,
    type_name,
)
from music_stack.errors import JobError, MusicStackError

KEY = "test-moises-key"


def client(routes, **kwargs):
    transport = FakeTransport(routes)
    return MoisesClient(KEY, transport=transport, **kwargs), transport


class AuthTests(unittest.TestCase):
    def test_raw_scheme_sends_bare_key(self):
        c, t = client({("POST", "/graphql"): {"data": {"__typename": "Query"}}})
        c.execute("{ __typename }")
        self.assertEqual(t.api_calls()[0][3]["Authorization"], KEY)

    def test_bearer_scheme_prefixes(self):
        c, t = client(
            {("POST", "/graphql"): {"data": {"__typename": "Query"}}},
            auth_scheme="bearer",
        )
        c.execute("{ __typename }")
        self.assertEqual(t.api_calls()[0][3]["Authorization"], "Bearer " + KEY)

    def test_unknown_scheme_rejected_at_construction(self):
        with self.assertRaises(MusicStackError):
            MoisesClient(KEY, auth_scheme="basic")

    def test_credential_scoped_to_moises_host(self):
        # Pointing the Moises client at another vendor must be refused before
        # the key is transmitted.
        c, _ = client({}, url="https://api.music.ai/graphql")
        with self.assertRaises(Exception) as ctx:
            c.execute("{ __typename }")
        self.assertIn("credentials", str(ctx.exception).lower())

    def test_detect_falls_through_to_second_scheme(self):
        c, t = client(
            {
                ("POST", "/graphql"): Sequence(
                    {"errors": [{"message": "Unauthorized"}]},
                    {"data": {"__typename": "Query"}},
                )
            }
        )
        self.assertEqual(c.detect_auth_scheme(), "bearer")
        self.assertEqual(c.auth_scheme, "bearer")

    def test_detect_returns_first_working_scheme(self):
        c, _ = client({("POST", "/graphql"): {"data": {"__typename": "Query"}}})
        self.assertEqual(c.detect_auth_scheme(), AUTH_SCHEMES[0])

    def test_detect_raises_when_no_scheme_works(self):
        c, _ = client({("POST", "/graphql"): {"errors": [{"message": "Unauthorized"}]}})
        with self.assertRaises(JobError) as ctx:
            c.detect_auth_scheme()
        self.assertIn("copied whole", str(ctx.exception))


class GraphQLErrorTests(unittest.TestCase):
    def test_errors_in_a_200_response_still_raise(self):
        """The GraphQL trap: HTTP 200 does not mean the operation succeeded."""
        c, _ = client(
            {
                ("POST", "/graphql"): {
                    "data": None,
                    "errors": [{"message": "Field 'nope' doesn't exist"}],
                }
            }
        )
        with self.assertRaises(JobError) as ctx:
            c.execute("{ nope }")
        self.assertIn("doesn't exist", str(ctx.exception))

    def test_partial_data_alongside_errors_is_not_returned(self):
        c, _ = client(
            {
                ("POST", "/graphql"): {
                    "data": {"partial": 1},
                    "errors": [{"message": "boom"}],
                }
            }
        )
        with self.assertRaises(JobError):
            c.execute("{ partial }")

    def test_response_with_neither_data_nor_errors(self):
        c, _ = client({("POST", "/graphql"): {"unexpected": True}})
        with self.assertRaises(JobError) as ctx:
            c.execute("{ x }")
        self.assertIn("neither data nor errors", str(ctx.exception))

    def test_variables_are_sent_when_given(self):
        c, t = client({("POST", "/graphql"): {"data": {}}})
        c.execute("query($id: ID!) { job(id: $id) { id } }", {"id": "abc"})
        # FakeTransport records headers; assert the call was made and scoped.
        self.assertEqual(len(t.api_calls()), 1)
        self.assertIn("moises.ai", t.api_calls()[0][2])

    def test_http_failure_propagates(self):
        c, _ = client({("POST", "/graphql"): http.HttpError("HTTP 500", status=500)})
        with self.assertRaises(http.HttpError):
            c.execute("{ x }")


class TypeNameTests(unittest.TestCase):
    def test_scalar(self):
        self.assertEqual(type_name({"kind": "SCALAR", "name": "String"}), "String")

    def test_non_null(self):
        self.assertEqual(
            type_name(
                {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "ID"}}
            ),
            "ID!",
        )

    def test_list_of_non_null(self):
        ref = {
            "kind": "NON_NULL",
            "ofType": {
                "kind": "LIST",
                "ofType": {
                    "kind": "NON_NULL",
                    "ofType": {"kind": "OBJECT", "name": "Job"},
                },
            },
        }
        self.assertEqual(type_name(ref), "[Job!]!")

    def test_missing_ref(self):
        self.assertEqual(type_name(None), "?")


SCHEMA_PAYLOAD = {
    "data": {
        "__schema": {
            "queryType": {"name": "Query"},
            "mutationType": {"name": "Mutation"},
            "types": [
                {
                    "name": "Query",
                    "kind": "OBJECT",
                    "fields": [
                        {
                            "name": "job",
                            "description": "Fetch one job",
                            "args": [
                                {
                                    "name": "id",
                                    "type": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "SCALAR", "name": "ID"},
                                    },
                                }
                            ],
                            "type": {"kind": "OBJECT", "name": "Job"},
                        }
                    ],
                },
                {
                    "name": "Mutation",
                    "kind": "OBJECT",
                    "fields": [
                        {
                            "name": "createJob",
                            "description": "",
                            "args": [
                                {
                                    "name": "input",
                                    "type": {"kind": "INPUT_OBJECT", "name": "JobInput"},
                                }
                            ],
                            "type": {"kind": "OBJECT", "name": "Job"},
                        }
                    ],
                },
            ],
        }
    }
}


class IntrospectionTests(unittest.TestCase):
    def test_extracts_queries_and_mutations(self):
        c, _ = client({("POST", "/graphql"): SCHEMA_PAYLOAD})
        schema = c.introspect()
        self.assertEqual([q["name"] for q in schema["queries"]], ["job"])
        self.assertEqual([m["name"] for m in schema["mutations"]], ["createJob"])
        self.assertEqual(schema["queries"][0]["args"][0]["type"], "ID!")

    def test_handles_schema_with_no_mutations(self):
        payload = {
            "data": {
                "__schema": {
                    "queryType": {"name": "Query"},
                    "mutationType": None,
                    "types": [{"name": "Query", "kind": "OBJECT", "fields": []}],
                }
            }
        }
        c, _ = client({("POST", "/graphql"): payload})
        schema = c.introspect()
        self.assertEqual(schema["mutations"], [])

    def test_format_is_readable_and_filterable(self):
        c, _ = client({("POST", "/graphql"): SCHEMA_PAYLOAD})
        rendered = format_schema(c.introspect())
        self.assertIn("job(id: ID!) -> Job", rendered)
        self.assertIn("createJob(input: JobInput) -> Job", rendered)
        self.assertIn("Fetch one job", rendered)

    def test_format_contains_filter(self):
        c, _ = client({("POST", "/graphql"): SCHEMA_PAYLOAD})
        rendered = format_schema(c.introspect(), contains="createjob")
        self.assertIn("createJob", rendered)
        self.assertIn("QUERIES (0)", rendered)


if __name__ == "__main__":
    unittest.main()
