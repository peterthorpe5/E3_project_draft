# Code documentation standard

All Python modules, classes, functions and methods in `src/e3_discovery` must
use PEP 257-compatible docstrings. Function and method docstrings use a
consistent Google-style structure because it remains readable in source code
and can be rendered by common API-documentation tools.

## Required function and method content

Every function and method must include:

1. A one-line imperative summary ending with a full stop.
2. Additional explanation where scientific behaviour, file semantics, side
   effects or compatibility rules are not obvious.
3. An `Args` section naming every argument other than `self` or `cls`.
4. A `Returns` section, including functions whose result is `None`, or a
   `Yields` section for generators and context managers.
5. A `Raises` section when the implementation deliberately raises or commonly
   propagates an exception that callers should handle.

Types remain in function annotations and are not duplicated mechanically. The
argument descriptions explain meaning, units, valid ranges and expected file or
table roles. Return descriptions explain structure and semantics rather than
merely repeating the type.

## Classes and dataclasses

Every class has a one-line summary. Dataclasses additionally document every
field under an `Attributes` section, including biological or workflow meaning.
The package exception hierarchy uses focused class summaries because the class
name and inheritance already define the interface.

## Private helpers

Leading-underscore functions are documented to the same standard as public
functions. They implement scientifically relevant parsing, validation and SQL
construction and therefore form part of the maintainability and audit trail.

## Automated enforcement

`tests/unit/test_docstring_quality.py` parses the source tree and checks that:

- every source module, class, function and method has a docstring;
- summary lines end with a full stop;
- every named argument is documented;
- every function documents its return value or yielded values; and
- functions containing explicit `raise` statements include a `Raises` section.

These checks run as part of `./run_tests.sh` and the release-check script.
