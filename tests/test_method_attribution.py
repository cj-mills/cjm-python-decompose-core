"""First-param capture + monkey-patch-assignment detection (the cross-cell method idioms)."""

from cjm_python_decompose_core.parse import monkeypatch_assignments, parse_module


def test_first_param_and_annotation_captured():
    src = ("@patch\n"
           "def get(self: Store, k: str) -> int:\n"
           "    return 1\n")
    s = parse_module(src).symbols[0]
    assert s.name == "get" and s.decorators == ["patch"]
    assert s.first_param == "self" and s.first_param_annotation == "Store"


def test_first_param_forward_ref_annotation():
    s = parse_module("def m(self: 'JobQueue'):\n    pass\n").symbols[0]
    assert s.first_param == "self" and s.first_param_annotation == "JobQueue"


def test_first_param_unannotated_and_classes_have_none():
    fn = parse_module("def f(self, x):\n    return x\n").symbols[0]
    assert fn.first_param == "self" and fn.first_param_annotation == ""
    cls = parse_module("class C:\n    pass\n").symbols[0]
    assert cls.first_param == "" and cls.first_param_annotation == ""


def test_no_arg_function_has_empty_first_param():
    assert parse_module("def f():\n    return 1\n").symbols[0].first_param == ""


def test_monkeypatch_assignments_detected():
    src = ("async def submit(self, x): ...\n"
           "def _enqueue(self, j): ...\n"
           "JobQueue.submit = submit\n"
           "JobQueue._enqueue = _enqueue\n")
    assert monkeypatch_assignments(src) == [("JobQueue", "submit", "submit"),
                                            ("JobQueue", "_enqueue", "_enqueue")]


def test_monkeypatch_is_structural_filtering_is_downstream():
    # The detector matches any top-level `Name.attr = Name` (precision is applied by the
    # compositor, which only re-attributes when the target Name is a known CLASS). Plain
    # constants and non-Name values (a call) are excluded here.
    src = "X = 1\nCONST = {}\nobj.attr = other\nC.m = make()\nStore.put = put\n"
    assert monkeypatch_assignments(src) == [("obj", "attr", "other"), ("Store", "put", "put")]
