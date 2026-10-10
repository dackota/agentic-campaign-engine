"""Build process settings from environment variables: one loader for the API, the worker,
and the fake Marketo. Each dataclass field `name` is read from `<prefix><NAME>`.

A missing or malformed variable fails at start with the variable's name, never its value.
"""

import dataclasses
import typing
from collections.abc import Callable, Collection, Mapping
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from ace_engine.settings import Depth, Settings

PREFIX = "ACE_"
DATABASE_PASSWORD_ENV = "ACE_DATABASE_PASSWORD"
OIDC_FIELDS = ("oidc_issuer", "oidc_client_id")

_PARSERS: dict[Any, Callable[[str], Any]] = {str: str, float: float, Depth: Depth.parse}


def env_name(field: str, prefix: str = PREFIX) -> str:
    return f"{prefix}{field.upper()}"


def from_env[T](
    cls: type[T],
    environ: Mapping[str, str],
    *,
    prefix: str = PREFIX,
    skip: Collection[str] = (),
    require: Collection[str] = (),
    overrides: Mapping[str, Any] | None = None,
) -> T:
    """`cls` built from `environ`. A field with no default, or named in `require`, must be
    set; a field in `skip` keeps its default; `overrides` replaces a read value."""
    hints = typing.get_type_hints(cls)
    values: dict[str, Any] = {}
    for field in dataclasses.fields(cls):  # type: ignore[arg-type]
        if field.name in skip:
            continue
        name = env_name(field.name, prefix)
        raw = environ.get(name)
        if raw is None:
            has_default = field.default is not dataclasses.MISSING
            if not has_default or field.name in require:
                raise ValueError(f"{name} is required: set it in the environment")
            continue
        values[field.name] = _parse(name, hints[field.name], raw)
    values.update(overrides or {})
    return cls(**values)


def _parse(name: str, kind: Any, raw: str) -> Any:
    try:
        return _PARSERS[kind](raw)
    except ValueError:
        # The parser's own message may echo the value; name the variable only.
        raise ValueError(f"{name} is not a valid {kind.__name__}") from None


def settings_from_env(environ: Mapping[str, str], *, is_api: bool) -> Settings:
    """Settings for the API (`is_api`, which must trust an OIDC issuer) or the worker,
    which never checks tokens and leaves the OIDC fields unset.

    `ACE_DATABASE_PASSWORD`, when set, is put into `ACE_DATABASE_URL`, so the URL can be a
    plain value and the password can come from a Secret."""
    url_name = env_name("database_url")
    overrides = {}
    password = environ.get(DATABASE_PASSWORD_ENV)
    if password is not None and url_name in environ:
        try:
            url = make_url(environ[url_name]).set(password=password)
        except ArgumentError:
            raise ValueError(f"{url_name} is not a valid database URL") from None
        overrides["database_url"] = url.render_as_string(hide_password=False)
    return from_env(
        Settings,
        environ,
        skip=() if is_api else OIDC_FIELDS,
        require=("oidc_issuer",) if is_api else (),
        overrides=overrides,
    )
