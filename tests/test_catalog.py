# -*- coding: utf-8 -*-
"""catalog/components.json 完整性 —— 类型词表的单一真源。

irlib 的类型集合与 ir2tikz 的 to[] 名全部由目录派生；此测试锁定派生结果，
让一份陈旧或写错的目录立即报错（而不是悄悄产生错误的电路）。"""
import irlib


def test_catalog_derives_the_known_type_sets():
    assert irlib.TWO_TERMINAL_TYPES == frozenset([
        "resistor", "potentiometer", "capacitor", "polar_capacitor", "inductor",
        "diode", "zener", "led", "battery", "vsource", "isource", "cvsource",
        "cisource", "switch_spst", "ammeter", "voltmeter"])
    assert irlib.MULTI_TYPES == frozenset(
        ["npn", "pnp", "nmos", "pmos", "opamp", "transformer", "spdt"])
    assert irlib.SINGLE_TYPES == frozenset(["ground", "vcc", "vee"])
    assert irlib.INVERT_TYPES == frozenset(["vsource", "cvsource", "battery"])
    assert irlib.VARIANTS == {
        "opamp": frozenset(["noinv_up"]), "transformer": frozenset(["core"])}


def test_to_name_covers_every_two_terminal():
    assert set(irlib.TO_NAME) == irlib.TWO_TERMINAL_TYPES
    assert irlib.TO_NAME["resistor"] == "R"
    assert irlib.TO_NAME["polar_capacitor"] == "cC"


def test_catalog_entries_are_wellformed():
    cat = irlib.load_json(irlib.CATALOG_PATH)
    order = cat["meta"]["categoryOrder"]
    for t, v in cat["components"].items():
        assert v["kind"] in ("two", "multi", "single"), t
        assert v.get("category") in order, t
        assert v.get("prefix") and v.get("label"), t
        if v["kind"] == "two":
            assert v.get("tikz") and "invert" in v, t
        elif v["kind"] == "multi":
            assert v.get("anchors"), t
        else:
            assert v.get("node"), t
