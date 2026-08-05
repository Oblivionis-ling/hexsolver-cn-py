"""Dump readable CIL for selected classes from a managed Unity assembly.

This is a development-only reverse-engineering aid.  It never writes to the
game directory; callers may redirect stdout to a file under the project.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBytes
from dncil.clr.token import Token


TABLE_BY_NUMBER = {
    0x01: "TypeRef",
    0x02: "TypeDef",
    0x04: "Field",
    0x06: "MethodDef",
    0x0A: "MemberRef",
    0x11: "StandAloneSig",
    0x1B: "TypeSpec",
    0x2B: "MethodSpec",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


class Resolver:
    def __init__(self, pe: dnfile.dnPE) -> None:
        self.pe = pe
        self.method_owners: dict[int, str] = {}
        self.field_owners: dict[int, str] = {}
        for type_row in pe.net.mdtables.TypeDef:
            owner = self.type_name(type_row)
            for index in type_row.MethodList:
                self.method_owners[id(index.row)] = owner
            for index in type_row.FieldList:
                self.field_owners[id(index.row)] = owner

    @staticmethod
    def type_name(row: Any) -> str:
        namespace = _text(getattr(row, "TypeNamespace", ""))
        name = _text(getattr(row, "TypeName", ""))
        return f"{namespace}.{name}" if namespace else name

    def coded_parent(self, coded: Any) -> str:
        if coded is None or coded.row is None:
            return "?"
        table_name = coded.table.name
        row = coded.row
        if table_name in {"TypeDef", "TypeRef"}:
            return self.type_name(row)
        if table_name == "TypeSpec":
            return f"TypeSpec[{coded.row_index}]"
        if table_name == "MethodDef":
            owner = self.method_owners.get(id(row), "?")
            return f"{owner}::{_text(row.Name)}"
        if table_name == "MemberRef":
            return self.member_ref(row)
        return f"{table_name}[{coded.row_index}]"

    def member_ref(self, row: Any) -> str:
        return f"{self.coded_parent(row.Class)}::{_text(row.Name)}"

    def token(self, token: Token) -> str:
        if token.table == 0x70:
            try:
                return repr(str(self.pe.net.user_strings.get(token.rid)))
            except Exception:  # pragma: no cover - corrupt metadata fallback
                return f"user-string[{token.rid}]"

        table_name = TABLE_BY_NUMBER.get(token.table)
        if table_name is None:
            return str(token)
        table = getattr(self.pe.net.mdtables, table_name, None)
        if table is None or not 1 <= token.rid <= len(table.rows):
            return str(token)
        row = table.rows[token.rid - 1]

        if table_name in {"TypeDef", "TypeRef"}:
            return self.type_name(row)
        if table_name == "Field":
            owner = self.field_owners.get(id(row), "?")
            return f"{owner}::{_text(row.Name)}"
        if table_name == "MethodDef":
            owner = self.method_owners.get(id(row), "?")
            return f"{owner}::{_text(row.Name)}"
        if table_name == "MemberRef":
            return self.member_ref(row)
        if table_name == "MethodSpec":
            return f"{self.coded_parent(row.Method)}<...>"
        return f"{table_name}[{token.rid}]"

    def operand(self, value: Any) -> str:
        if isinstance(value, Token):
            return self.token(value)
        if isinstance(value, list):
            return "[" + ", ".join(self.operand(item) for item in value) + "]"
        return repr(value)


def find_types(pe: dnfile.dnPE, names: Iterable[str]) -> list[Any]:
    requested = set(names)
    found = [row for row in pe.net.mdtables.TypeDef if _text(row.TypeName) in requested]
    missing = requested - {_text(row.TypeName) for row in found}
    if missing:
        raise SystemExit(f"Types not found: {', '.join(sorted(missing))}")
    return found


def dump_type(
    pe: dnfile.dnPE,
    resolver: Resolver,
    type_row: Any,
    method_names: set[str] | None = None,
) -> None:
    print(f"\n.type {resolver.type_name(type_row)}")
    if type_row.FieldList:
        print("  .fields " + ", ".join(_text(index.row.Name) for index in type_row.FieldList))

    for method_index in type_row.MethodList:
        method = method_index.row
        if method_names and _text(method.Name) not in method_names:
            continue
        print(f"\n  .method {_text(method.Name)}  // RVA 0x{method.Rva:X}")
        if not method.Rva:
            print("    <no body>")
            continue
        try:
            body = CilMethodBody(CilMethodBodyReaderBytes(pe.get_data(method.Rva)))
        except Exception as exc:  # pragma: no cover - corrupt/unsupported body fallback
            print(f"    <cannot parse: {exc}>")
            continue
        print(f"    // maxstack={body.max_stack} locals={body.local_var_sig_tok}")
        for instruction in body.instructions:
            operand = "" if instruction.operand is None else " " + resolver.operand(instruction.operand)
            print(f"    IL_{instruction.offset:04X}: {instruction.opcode.name}{operand}")
        if body.exception_handlers:
            print("    // exception handlers")
            for handler in body.exception_handlers:
                print(f"    // {handler}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("assembly", type=Path)
    parser.add_argument("types", nargs="*")
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="List every managed type and its method names, then exit.",
    )
    parser.add_argument(
        "--find-string",
        help="Find methods that load a user string containing this text, then exit.",
    )
    parser.add_argument(
        "--find-call",
        help="Find methods that call a member containing this text, then exit.",
    )
    parser.add_argument(
        "--method",
        action="append",
        dest="methods",
        help="Only dump a named method. May be repeated.",
    )
    args = parser.parse_args()

    pe = dnfile.dnPE(str(args.assembly))
    if pe.net is None:
        raise SystemExit(f"Not a managed assembly: {args.assembly}")
    resolver = Resolver(pe)
    if args.list_types:
        for type_row in pe.net.mdtables.TypeDef:
            methods = ", ".join(_text(index.row.Name) for index in type_row.MethodList)
            print(f"{resolver.type_name(type_row)}: {methods}")
        return
    if args.find_string is not None:
        needle = args.find_string.casefold()
        for type_row in pe.net.mdtables.TypeDef:
            owner = resolver.type_name(type_row)
            for method_index in type_row.MethodList:
                method = method_index.row
                if not method.Rva:
                    continue
                try:
                    body = CilMethodBody(CilMethodBodyReaderBytes(pe.get_data(method.Rva)))
                except Exception:
                    continue
                for instruction in body.instructions:
                    operand = instruction.operand
                    if not isinstance(operand, Token) or operand.table != 0x70:
                        continue
                    value = str(pe.net.user_strings.get(operand.rid))
                    if needle in value.casefold():
                        print(f"{owner}::{_text(method.Name)} IL_{instruction.offset:04X}: {value!r}")
        return
    if args.find_call is not None:
        needle = args.find_call.casefold()
        for type_row in pe.net.mdtables.TypeDef:
            owner = resolver.type_name(type_row)
            for method_index in type_row.MethodList:
                method = method_index.row
                if not method.Rva:
                    continue
                try:
                    body = CilMethodBody(CilMethodBodyReaderBytes(pe.get_data(method.Rva)))
                except Exception:
                    continue
                for instruction in body.instructions:
                    operand = instruction.operand
                    if not isinstance(operand, Token) or operand.table not in {0x06, 0x0A, 0x2B}:
                        continue
                    called = resolver.token(operand)
                    if needle in called.casefold():
                        print(f"{owner}::{_text(method.Name)} IL_{instruction.offset:04X}: {called}")
        return
    if not args.types:
        parser.error("at least one type is required unless --list-types is used")
    for type_row in find_types(pe, args.types):
        dump_type(pe, resolver, type_row, set(args.methods) if args.methods else None)


if __name__ == "__main__":
    main()
