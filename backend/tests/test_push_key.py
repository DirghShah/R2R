"""APNS_KEY_CONTENT decoding.

Pasting the .p8 straight into the env var instead of base64 of it produced no
error at all: base64.b64decode with the default validate=False discards the
dashes and newlines and decodes the remainder as data, so a garbage key was
written to disk and the only symptom was PyJWT failing in prepare_key, once per
push, as a warning. Every one of these asserts on a case that used to be silent.
"""
from __future__ import annotations

import base64

from worker.push import _decode_key

PEM = (b"-----BEGIN PRIVATE KEY-----\n"
       b"MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg\n"
       b"-----END PRIVATE KEY-----\n")


def test_base64_of_the_p8_is_accepted():
    assert _decode_key(base64.b64encode(PEM).decode()) == PEM


def test_base64_with_wrapping_newlines_is_accepted():
    """`base64 -i key.p8` wraps at 76 columns unless you strip it."""
    wrapped = base64.encodebytes(PEM).decode()  # has embedded newlines
    assert _decode_key(wrapped) == PEM


def test_the_p8_pasted_directly_is_accepted():
    """The likely mistake, and survivable — the PEM header identifies it."""
    assert _decode_key(PEM.decode()) == PEM


def test_garbage_is_refused_rather_than_written_to_disk():
    """This is the case that used to produce a silent, unusable key file."""
    assert _decode_key("this is not a key") is None


def test_valid_base64_of_something_that_is_not_a_key_is_refused():
    assert _decode_key(base64.b64encode(b"hello there").decode()) is None


def test_empty_is_none():
    assert _decode_key("") is None
    assert _decode_key("   ") is None
