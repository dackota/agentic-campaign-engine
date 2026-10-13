"""Build process settings from environment variables: one loader for the API, the worker,
and the fake Marketo. Each dataclass field `name` is read from `<prefix><NAME>`.

A missing or malformed variable fails at start with the variable's name, never its value.
"""

import dataclasses
import typing
from collections.abc import Callable, Collection, Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from ace_engine.settings import Depth, Settings

PREFIX = "ACE_"
DATABASE_PASSWORD_ENV = "ACE_DATABASE_PASSWORD"
OIDC_FIELDS = ("oidc_issuer", "oidc_client_id")

type Parsed = str | float | Depth

_PARSERS: dict[type[object], Callable[[str], Parsed]] = {
    str: str,
    float: float,
    Depth: Depth.parse,
}


def env_name(field: str, prefix: str = PREFIX) -> str:
    return f"{prefix}{field.upper()}"


def from_env[T](
    cls: type[T],
    environ: Mapping[str, str],
    *,
    prefix: str = PREFIX,
    skip: Collection[str] = (),
    require: Collection[str] = (),
) -> T:
    """`cls` built from `environ`. A field with no default, or named in `require`, must be
    set; a field in `skip` keeps its default."""
    hints = typing.get_type_hints(cls)
    values: dict[str, Parsed] = {}
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
    return cls(**values)


def _parse(name: str, kind: type[object], raw: str) -> Parsed:
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
    return from_env(
        Settings,
        _with_database_password(environ),
        skip=() if is_api else OIDC_FIELDS,
        require=("oidc_issuer",) if is_api else (),
    )


def database_url_from_env(environ: Mapping[str, str]) -> str:
    """`ACE_DATABASE_URL` with `ACE_DATABASE_PASSWORD` put in when it is set. Fails naming
    the variable, never its value, when the URL is unset or malformed."""
    name = env_name("database_url")
    if name not in environ:
        raise ValueError(f"{name} is required: set it in the environment")
    return _with_database_password(environ)[name]


def _with_database_password(environ: Mapping[str, str]) -> Mapping[str, str]:
    """`environ`, or a new mapping whose database URL carries `ACE_DATABASE_PASSWORD`."""
    url_name = env_name("database_url")
    password = environ.get(DATABASE_PASSWORD_ENV)
    if password is None or url_name not in environ:
        return environ
    try:
        url = make_url(environ[url_name]).set(password=password)
    except ArgumentError:
        raise ValueError(f"{url_name} is not a valid database URL") from None
    return {**environ, url_name: url.render_as_string(hide_password=False)}
