import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = PACKAGE / "pastel-mcp-bridge.py"
if not SOURCE.is_file():
    SOURCE = PACKAGE.parent / "Tools/pastel-mcp-bridge.py"
spec = importlib.util.spec_from_file_location("pastel_read_only_under_test", SOURCE)
transport = importlib.util.module_from_spec(spec)
exec(compile(SOURCE.read_bytes(), str(SOURCE), "exec"), transport.__dict__)


class ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.bridge = transport.PastelBridge(paths=[], launch=False, read_only=True)
        self.addCleanup(self.bridge.close)
        # Simulate reuse of a live descriptor from a fully editable app. The
        # fake token never leaves this process and no network request is made.
        self.connection = {"pid": 123, "port": 4567, "token": "fixture-not-a-real-token"}
        self.calls = []
        self.definitions = [
            {"name": "pastel_document_state", "annotations": {"readOnlyHint": True}},
            {"name": "pastel_draw_strokes", "annotations": {"readOnlyHint": False}},
        ]
        self.bridge.connection = mock.Mock(return_value=self.connection)
        self.bridge.request = mock.Mock(side_effect=self.request)

    def request(self, value, connection):
        self.assertIs(connection, self.connection)
        self.calls.append(copy.deepcopy(value))
        if value["method"] == "tools/list":
            return {"jsonrpc": "2.0", "id": value["id"], "result": {"tools": copy.deepcopy(self.definitions)}}
        return {"jsonrpc": "2.0", "id": value.get("id"), "result": {"ok": True}}

    def tool(self, name, **extra):
        return {"jsonrpc": "2.0", "id": "client-request", "method": "tools/call", "params": {"name": name, "arguments": {}, **extra}}

    def test_reused_editable_connection_cannot_write(self):
        with self.assertRaises(transport.BridgeError):
            self.bridge.forward(self.tool("pastel_draw_strokes"))
        self.assertEqual([value["method"] for value in self.calls], ["tools/list"])

    def test_read_tool_uses_live_authenticated_annotations(self):
        value = self.tool("pastel_document_state")
        self.assertEqual(self.bridge.forward(value)["result"], {"ok": True})
        self.assertEqual([item["method"] for item in self.calls], ["tools/list", "tools/call"])
        self.assertEqual(self.calls[-1], value)

    def test_client_supplied_read_only_hint_cannot_allow_write(self):
        value = self.tool("pastel_draw_strokes", annotations={"readOnlyHint": True}, readOnlyHint=True)
        value["annotations"] = {"readOnlyHint": True}
        with self.assertRaises(transport.BridgeError):
            self.bridge.forward(value)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_mutating_and_subscription_methods_blocked_before_connection(self):
        for method in ("pastel/mutate", "pastel/localConnection/subscribe", "resources/subscribe", "unknown", "notifications/mutate"):
            with self.subTest(method=method), self.assertRaises(transport.BridgeError):
                self.bridge.forward({"jsonrpc": "2.0", "id": 1, "method": method})
        self.assertEqual(self.calls, [])
        self.bridge.connection.assert_not_called()

    def test_unknown_duplicate_or_malformed_tool_definitions_fail_closed(self):
        variants = [[], [{"name": "x"}], [{"name": "x", "annotations": []}],
                    [{"name": "x", "annotations": {"readOnlyHint": 1}}],
                    [{"name": "x", "annotations": {"readOnlyHint": "true"}}],
                    [{"name": "x", "annotations": {"readOnlyHint": True}}] * 2,
                    [None, "x", 1]]
        for definitions in variants:
            with self.subTest(definitions=definitions):
                self.definitions = definitions
                before = len(self.calls)
                with self.assertRaises(transport.BridgeError):
                    self.bridge.forward(self.tool("x"))
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(self.calls[-1]["method"], "tools/list")

    def test_missing_or_invalid_tool_name_never_calls_tool(self):
        for params in (None, [], {}, {"name": None}, {"name": ["pastel_document_state"]}):
            with self.subTest(params=params), self.assertRaises(transport.BridgeError):
                self.bridge.forward({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        self.assertTrue(all(value["method"] == "tools/list" for value in self.calls))

    def test_current_permissions_are_refetched_without_cache(self):
        self.bridge.forward(self.tool("pastel_document_state"))
        self.definitions[0]["annotations"]["readOnlyHint"] = False
        with self.assertRaises(transport.BridgeError):
            self.bridge.forward(self.tool("pastel_document_state"))
        self.assertEqual([value["method"] for value in self.calls], ["tools/list", "tools/call", "tools/list"])

    def test_list_failure_never_replays_or_sends_original_call(self):
        self.bridge.request = mock.Mock(side_effect=transport.BridgeError("fixed safe fixture error"))
        with self.assertRaises(transport.BridgeError):
            self.bridge.forward(self.tool("pastel_document_state"))
        self.assertEqual(self.bridge.request.call_count, 1)
        self.assertEqual(self.bridge.request.call_args[0][0]["method"], "tools/list")

    def test_error_or_bad_shape_from_listing_fails_closed(self):
        for response in (None, [], {}, {"result": []}, {"result": {"tools": {}}}, {"error": {"code": -1}}):
            with self.subTest(response=response):
                self.bridge.request = mock.Mock(return_value=response)
                with self.assertRaises(transport.BridgeError):
                    self.bridge.forward(self.tool("pastel_document_state"))
                self.assertEqual(self.bridge.request.call_count, 1)

    def test_explicit_edit_connection_does_not_invent_read_only_restrictions(self):
        self.bridge.read_only = False
        self.bridge.forward(self.tool("pastel_draw_strokes"))
        self.assertEqual([value["method"] for value in self.calls], ["tools/call"])

    def test_read_session_setup_and_cancellation_are_permitted(self):
        for method in ("initialize", "server/discover", "ping", "tools/list", "resources/list", "resources/templates/list", "resources/read", "prompts/list", "prompts/get", "notifications/initialized", "notifications/cancelled"):
            with self.subTest(method=method):
                self.bridge.forward({"jsonrpc": "2.0", "id": "read", "method": method})
        self.assertEqual(len(self.calls), 11)

    def test_modern_tool_probe_preserves_protocol_metadata_without_client_hints(self):
        metadata = {transport.PROTOCOL_VERSION_META: transport.MODERN_PROTOCOL,
                    transport.CLIENT_CAPABILITIES_META: {}, "io.modelcontextprotocol/clientInfo": {"name": "test"}}
        value = self.tool("pastel_document_state", _meta=metadata, annotations={"readOnlyHint": True})
        self.bridge.forward(value)
        self.assertEqual(self.calls[0]["params"], {"_meta": metadata})
        self.assertEqual(self.calls[1], value)
        self.assertIsNot(self.calls[0]["params"]["_meta"], metadata)

    def test_modern_discovery_cannot_bypass_write_guard(self):
        self.bridge.forward({"jsonrpc": "2.0", "id": "discover", "method": "server/discover",
                             "params": {"_meta": {transport.PROTOCOL_VERSION_META: transport.MODERN_PROTOCOL}}})
        value = self.tool("pastel_draw_strokes", _meta={transport.PROTOCOL_VERSION_META: transport.MODERN_PROTOCOL})
        with self.assertRaises(transport.BridgeError):
            self.bridge.forward(value)
        self.assertEqual([item["method"] for item in self.calls], ["server/discover", "tools/list"])


if __name__ == "__main__":
    unittest.main()
